"""OpenID Connect (authorization code flow + PKCE) for SSO: Keycloak, Entra ID, ADFS, Google, GitLab, Okta...

Flow: /api/auth/oidc/{slug}/login redirects to the IdP with state, nonce and a PKCE challenge kept in a short-lived
signed cookie -> the IdP redirects back to /callback -> code is exchanged for tokens -> the id_token signature is
checked against the IdP JWKS together with iss, aud, exp and nonce.
"""
import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field, fields
from urllib.parse import urlencode

import httpx
import jwt

log = logging.getLogger("lodestone.oidc")

ASYMMETRIC = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]
_CACHE_TTL = 3600
_discovery: dict[str, tuple[float, dict]] = {}
_jwks: dict[str, tuple[float, jwt.PyJWKSet]] = {}


class OidcError(Exception):
    pass


@dataclass
class OidcConfig:
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: str = "openid profile email"
    username_claim: str = "preferred_username"
    email_claim: str = "email"
    name_claim: str = "name"
    groups_claim: str = "groups"
    allowed_groups: list[str] = field(default_factory=list)
    admin_groups: list[str] = field(default_factory=list)
    auto_create: bool = True
    link_by_email: bool = False  # attach to an existing user with the same verified e-mail
    timeout: int = 10

    @classmethod
    def from_dict(cls, data: dict) -> "OidcConfig":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class OidcUser:
    sub: str
    username: str
    email: str | None
    email_verified: bool
    display_name: str
    groups: list[str]
    is_admin: bool | None  # None = admin_groups not configured, don't touch is_admin


def http_client(timeout: int) -> httpx.Client:
    """Separate function so tests can swap in a fake IdP (httpx.MockTransport)."""
    return httpx.Client(timeout=timeout, follow_redirects=False)


def _get_json(cfg: OidcConfig, url: str) -> dict:
    try:
        with http_client(cfg.timeout) as c:
            r = c.get(url, headers={"Accept": "application/json"})
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise OidcError(f"GET {url}: {e}") from e


def discover(cfg: OidcConfig, fresh: bool = False) -> dict:
    issuer = cfg.issuer.rstrip("/")
    hit = _discovery.get(issuer)
    if hit and not fresh and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    meta = _get_json(cfg, f"{issuer}/.well-known/openid-configuration")
    for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not meta.get(k):
            raise OidcError(f"discovery document has no {k}")
    if meta.get("issuer", "").rstrip("/") != issuer:
        raise OidcError(f"issuer mismatch: configured {issuer}, IdP says {meta.get('issuer')}")
    _discovery[issuer] = (time.monotonic(), meta)
    return meta


def _keys(cfg: OidcConfig, uri: str, fresh: bool = False) -> jwt.PyJWKSet:
    hit = _jwks.get(uri)
    if hit and not fresh and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    keyset = jwt.PyJWKSet.from_dict(_get_json(cfg, uri))
    _jwks[uri] = (time.monotonic(), keyset)
    return keyset


def new_flow() -> dict:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return {"state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24), "verifier": verifier,
            "challenge": challenge}


def authorize_url(cfg: OidcConfig, redirect_uri: str, flow: dict) -> str:
    meta = discover(cfg)
    params = {"response_type": "code", "client_id": cfg.client_id, "redirect_uri": redirect_uri,
              "scope": cfg.scopes or "openid", "state": flow["state"], "nonce": flow["nonce"],
              "code_challenge": flow["challenge"], "code_challenge_method": "S256"}
    sep = "&" if "?" in meta["authorization_endpoint"] else "?"
    return meta["authorization_endpoint"] + sep + urlencode(params)


def _exchange(cfg: OidcConfig, meta: dict, code: str, redirect_uri: str, verifier: str) -> dict:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "code_verifier": verifier, "client_id": cfg.client_id}
    auth = None
    if cfg.client_secret:
        methods = meta.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        if "client_secret_basic" in methods:
            auth = (cfg.client_id, cfg.client_secret)
        else:
            data["client_secret"] = cfg.client_secret
    try:
        with http_client(cfg.timeout) as c:
            r = c.post(meta["token_endpoint"], data=data, auth=auth, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise OidcError(f"token endpoint: {e}") from e
    if r.status_code != 200:
        raise OidcError(f"token endpoint answered {r.status_code}: {r.text[:200]}")
    tokens = r.json()
    if not tokens.get("id_token"):
        raise OidcError("token response has no id_token (is the 'openid' scope requested?)")
    return tokens


def _validate(cfg: OidcConfig, meta: dict, id_token: str, nonce: str) -> dict:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as e:
        raise OidcError(f"bad id_token: {e}") from e
    alg = header.get("alg")
    if alg in ASYMMETRIC:
        kid = header.get("kid")
        keyset = _keys(cfg, meta["jwks_uri"])
        match = [k for k in keyset.keys if kid is None or k.key_id == kid]
        if not match:  # key rotation: refetch once
            match = [k for k in _keys(cfg, meta["jwks_uri"], fresh=True).keys if kid is None or k.key_id == kid]
        if not match:
            raise OidcError(f"no JWKS key with kid {kid}")
        key = match[0].key
    elif alg in ("HS256", "HS384", "HS512") and cfg.client_secret:
        key = cfg.client_secret
    else:
        raise OidcError(f"unsupported id_token alg {alg}")
    try:
        claims = jwt.decode(id_token, key, algorithms=[alg], audience=cfg.client_id, issuer=meta["issuer"],
                            options={"require": ["exp", "iat", "sub"]}, leeway=60)
    except jwt.PyJWTError as e:
        raise OidcError(f"id_token rejected: {e}") from e
    if claims.get("nonce") != nonce:
        raise OidcError("id_token nonce mismatch")
    return claims


def _claim(claims: dict, path: str):
    """Dotted path, e.g. realm_access.roles (Keycloak)."""
    cur = claims
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def complete(cfg: OidcConfig, code: str, redirect_uri: str, flow: dict) -> OidcUser:
    """Exchanges the code and maps claims to a user. Raises OidcError."""
    meta = discover(cfg)
    tokens = _exchange(cfg, meta, code, redirect_uri, flow["verifier"])
    claims = _validate(cfg, meta, tokens["id_token"], flow["nonce"])
    # groups often only come from userinfo (e.g. GitLab), merge it in when the id_token lacks them
    if meta.get("userinfo_endpoint") and tokens.get("access_token") and _claim(claims, cfg.groups_claim) is None:
        try:
            with http_client(cfg.timeout) as c:
                r = c.get(meta["userinfo_endpoint"], headers={"Authorization": f"Bearer {tokens['access_token']}"})
            if r.status_code == 200:
                info = r.json()
                if info.get("sub") == claims["sub"]:
                    claims = {**info, **claims}
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as e:
            log.warning("userinfo failed: %s", e)

    raw_groups = _claim(claims, cfg.groups_claim) or []
    if isinstance(raw_groups, str):
        raw_groups = [raw_groups]
    groups = sorted({str(g).lower() for g in raw_groups})[:500]
    allowed = {g.lower() for g in cfg.allowed_groups if g}
    if allowed and not allowed & set(groups):
        raise OidcError("not_allowed")
    admin = {g.lower() for g in cfg.admin_groups if g}

    email = _claim(claims, cfg.email_claim)
    username = str(_claim(claims, cfg.username_claim) or (email or "").split("@")[0] or claims["sub"])
    return OidcUser(
        sub=str(claims["sub"]), username=username.lower()[:150], email=email,
        email_verified=bool(claims.get("email_verified")),
        display_name=str(_claim(claims, cfg.name_claim) or username)[:255],
        groups=groups, is_admin=bool(admin & set(groups)) if admin else None)


def test_connection(cfg: OidcConfig) -> dict:
    try:
        meta = discover(cfg, fresh=True)
        _keys(cfg, meta["jwks_uri"], fresh=True)
        return {"ok": True, "message": f"Discovery OK: {meta['issuer']}"}
    except OidcError as e:
        return {"ok": False, "message": str(e)}
