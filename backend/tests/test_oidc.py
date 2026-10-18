"""SSO through OpenID Connect against a fake IdP (httpx.MockTransport): discovery, PKCE, JWKS signature check."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text

from app import oidc
from app.db import engine

from .conftest import make_client

ISSUER = "https://idp.test/realms/corp"


class FakeIdp:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codes: dict[str, dict] = {}
        self.sign_with = self.key
        self.override: dict = {}

    def jwks(self):
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/auth", "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/certs", "userinfo_endpoint": f"{ISSUER}/userinfo",
                "token_endpoint_auth_methods_supported": ["client_secret_basic"]})
        if path.endswith("/certs"):
            return httpx.Response(200, json=self.jwks())
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            grant = self.codes.pop(form["code"][0], None)
            expected_auth = "Basic " + base64.b64encode(b"lodestone:s3cret").decode()
            if not grant or request.headers.get("authorization") != expected_auth:
                return httpx.Response(400, json={"error": "invalid_grant"})
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest())
            if challenge.rstrip(b"=").decode() != grant["challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE"})
            now = int(time.time())
            claims = {"iss": ISSUER, "aud": "lodestone", "iat": now, "exp": now + 300, "nonce": grant["nonce"],
                      **grant["claims"], **self.override}
            token = jwt.encode(claims, self.sign_with, algorithm="RS256", headers={"kid": "k1"})
            return httpx.Response(200, json={"id_token": token, "access_token": "at", "token_type": "Bearer"})
        if path.endswith("/userinfo"):
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture
def idp(monkeypatch):
    fake = FakeIdp()
    oidc._discovery.clear()
    oidc._jwks.clear()
    monkeypatch.setattr(oidc, "http_client", lambda timeout: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    return fake


@pytest.fixture
def sso(admin, idp):
    r = admin.post("/api/admin/auth-providers", json={
        "slug": "kc", "type": "oidc", "name": "Keycloak", "config": {
            "issuer": ISSUER, "client_id": "lodestone", "client_secret": "s3cret",
            "allowed_groups": ["tracker"], "admin_groups": ["tracker-admins"]}})
    assert r.status_code == 201, r.text
    return r.json()


CLAIMS = {"sub": "u-1", "preferred_username": "Dana", "email": "dana@corp.local", "email_verified": True,
          "name": "Dana Ospanova", "groups": ["tracker", "devops"]}


def sso_login(idp, claims=CLAIMS, next_="/", tamper_state=False):
    c = make_client()
    r = c.get(f"/api/auth/oidc/kc/login?next={next_}", follow_redirects=False)
    assert r.status_code == 303, r.text
    url = urlparse(r.headers["location"])
    assert url.netloc == "idp.test"
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert q["code_challenge_method"] == "S256" and q["client_id"] == "lodestone"
    assert q["redirect_uri"].endswith("/api/auth/oidc/kc/callback")
    idp.codes["code-1"] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "claims": claims}
    state = "forged" if tamper_state else q["state"]
    r = c.get(f"/api/auth/oidc/kc/callback?code=code-1&state={state}", follow_redirects=False)
    return c, r


def test_config_lists_sso_button(sso):
    cfg = make_client().get("/api/auth/config").json()
    assert {"slug": "kc", "type": "oidc", "name": "Keycloak"} in cfg["sso"]
    assert cfg["password"] is True and cfg["setup_required"] is False


def test_secret_is_encrypted_and_never_returned(admin, sso):
    assert "s3cret" not in json.dumps(sso)
    assert sso["secrets_set"] == ["client_secret"]
    with engine().connect() as c:
        row = c.execute(text("SELECT config::text, secrets FROM auth_providers WHERE slug = 'kc'")).one()
    assert "s3cret" not in row[0] and "s3cret" not in row[1]


def test_sso_login_creates_user_with_groups(idp, sso):
    c, r = sso_login(idp, next_="/p/OPS")
    assert r.status_code == 303 and r.headers["location"] == "/p/OPS"
    me = c.get("/api/auth/me").json()
    assert (me["username"], me["display_name"], me["source"], me["is_admin"]) == \
        ("dana", "Dana Ospanova", "oidc", False)
    # second login: same account (matched by provider + sub), admin rights follow the IdP group
    c2, _ = sso_login(idp, {**CLAIMS, "groups": ["tracker", "tracker-admins"]})
    me2 = c2.get("/api/auth/me").json()
    assert me2["id"] == me["id"] and me2["is_admin"] is True


def test_sso_username_collision_gets_suffix(admin, idp, sso):
    admin.post("/api/users", json={"username": "dana", "display_name": "Local Dana", "password": "local-password"})
    c, _ = sso_login(idp)
    assert c.get("/api/auth/me").json()["username"] == "dana-2"


def test_sso_rejects_forged_state(idp, sso):
    _, r = sso_login(idp, tamper_state=True)
    assert r.headers["location"] == "/?login_error=sso_state"


def test_sso_rejects_user_outside_allowed_groups(idp, sso):
    c, r = sso_login(idp, {**CLAIMS, "groups": ["devops"]})
    assert r.headers["location"] == "/?login_error=sso_not_allowed"
    assert c.get("/api/auth/me").status_code == 401


def test_sso_rejects_token_signed_by_another_key(idp, sso):
    idp.sign_with = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _, r = sso_login(idp)
    assert r.headers["location"] == "/?login_error=sso_failed"


def test_sso_rejects_wrong_nonce_and_audience(idp, sso):
    idp.override = {"nonce": "replayed"}
    assert sso_login(idp)[1].headers["location"] == "/?login_error=sso_failed"
    idp.override = {"aud": "another-app"}
    assert sso_login(idp)[1].headers["location"] == "/?login_error=sso_failed"


def test_sso_next_is_not_an_open_redirect(idp, sso):
    _, r = sso_login(idp, next_="//evil.example")
    assert r.headers["location"] == "/"


def test_sso_user_cannot_use_password_form(idp, sso):
    sso_login(idp)
    assert make_client().post("/api/auth/login", json={"username": "dana", "password": "x"}).status_code == 401


def test_idp_group_gives_project_role(admin, idp, sso):
    admin.post("/api/projects", json={"key": "OPS", "name": "Ops", "is_private": True})
    c, _ = sso_login(idp)
    assert c.get("/api/projects/OPS").status_code == 404
    r = admin.post("/api/projects/OPS/group-bindings", json={"group": "DevOps", "role": "member", "provider": "kc"})
    assert r.status_code == 201, r.text
    p = c.get("/api/projects/OPS").json()
    assert "issues.create" in p["my_permissions"] and p["my_role"] is None
    me = c.get("/api/auth/me").json()["id"]
    r = c.post("/api/projects/OPS/issues", json={"title": "via group", "assignee_ids": [me]})
    assert r.status_code == 201, r.text  # group members count as project members for assignment


def test_disabled_provider_cannot_be_used(admin, idp, sso):
    admin.patch(f"/api/admin/auth-providers/{sso['id']}", json={"enabled": False})
    assert make_client().get("/api/auth/oidc/kc/login", follow_redirects=False).status_code == 404


def test_provider_test_endpoint(admin, idp, sso):
    r = admin.post("/api/admin/auth-providers/test", json={"provider_id": sso["id"]})
    assert r.json() == {"ok": True, "message": f"Discovery OK: {ISSUER}"}
    r = admin.post("/api/admin/auth-providers/test", json={"provider": {
        "slug": "x", "type": "oidc", "name": "X", "config": {"issuer": "https://idp.test/other", "client_id": "a"}}})
    assert r.json()["ok"] is False
