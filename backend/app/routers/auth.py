import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import ldap_auth, oidc, providers, rbac
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import AuthProvider, GroupBinding, LoginAttempt, User, UserGroup, utcnow
from ..schemas import AuthConfig, LoginIn, MeOut, ProviderBrief
from ..security import COOKIE, create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("lodestone.auth")

BAD = "Wrong username or password"
_DUMMY_HASH = hash_password("timing-equalizer")
FLOW_COOKIE = "lodestone_oidc"


def me_out(db: Session, user: User) -> MeOut:
    out = MeOut.model_validate(user, from_attributes=True)
    out.permissions = sorted(rbac.global_permissions(db, user), key=rbac.ALL_PERMISSIONS.index)
    return out


def set_session(response: Response, user: User):
    s = get_settings()
    response.set_cookie(COOKIE, create_token(user.id), httponly=True, secure=s.cookie_secure, samesite="lax",
                        max_age=s.session_hours * 3600, path="/")


def sync_groups(db: Session, user: User, provider: AuthProvider, groups: list[str]):
    db.execute(delete(UserGroup).where(UserGroup.user_id == user.id, UserGroup.provider_id == provider.id))
    for g in sorted(set(groups)):
        db.add(UserGroup(user_id=user.id, provider_id=provider.id, name=g.lower()[:500]))


@router.get("/config", response_model=AuthConfig)
def auth_config(db: Session = Depends(get_db)):
    pw, sso = [], []
    for p in providers.enabled(db):
        b = ProviderBrief(slug=p.slug, type=p.type, name=p.name)
        (sso if p.type == "oidc" else pw).append(b)
    return AuthConfig(setup_required=providers.setup_required(db), password=bool(pw), password_providers=pw, sso=sso)


def _locked(db: Session, username: str) -> bool:
    s = get_settings()
    since = datetime.now(timezone.utc) - timedelta(minutes=s.login_lock_minutes)
    fails = db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.username == username, LoginAttempt.ok.is_(False), LoginAttempt.created_at > since))
    return (fails or 0) >= s.login_max_failures


def _record(db: Session, username: str, ip: str, ok: bool):
    db.add(LoginAttempt(username=username, ip=ip, ok=ok))
    if ok:  # successful login clears the lock window
        db.query(LoginAttempt).filter(LoginAttempt.username == username, LoginAttempt.ok.is_(False)).delete()
    db.commit()


def _binding_groups(db: Session, provider: AuthProvider) -> tuple[str, ...]:
    rows = db.scalars(select(GroupBinding.group).where(
        (GroupBinding.provider_id == provider.id) | GroupBinding.provider_id.is_(None))).all()
    return tuple(sorted(set(rows)))


def _ldap_login(db: Session, user: User | None, username: str, password: str, slug: str | None) -> User | None:
    candidates = providers.enabled(db, "ldap")
    if user is not None and user.provider_id:  # existing directory user: only the directory it came from
        candidates = [p for p in candidates if p.id == user.provider_id]
    elif slug:
        candidates = [p for p in candidates if p.slug == slug]
    unavailable = 0
    for p in candidates:
        cfg = providers.ldap_config(p)
        try:
            lu = ldap_auth.authenticate(cfg, username, password, check_groups=_binding_groups(db, p))
        except ldap_auth.LdapUnavailable:
            unavailable += 1
            continue
        if not lu:
            continue
        if user is None:
            user = User(username=lu.username, source="ldap", provider_id=p.id, display_name=lu.display_name,
                        is_active=True, is_admin=False)
            db.add(user)
            db.flush()
        user.display_name, user.email = lu.display_name, lu.email
        if cfg.admin_group:
            user.is_admin = lu.is_admin  # directory is the source of truth for admin rights
        groups = list(lu.groups)
        if cfg.allowed_group:
            groups.append(cfg.allowed_group)  # authenticate() already checked membership
        if lu.is_admin:
            groups.append(cfg.admin_group)
        sync_groups(db, user, p, groups)
        return user
    if candidates and unavailable == len(candidates):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Directory service is unavailable")
    return None


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    username = body.username.strip().lower()
    ip = request.client.host if request.client else "-"
    if _locked(db, username):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many failed attempts. Try again in {s.login_lock_minutes} min")

    user = db.scalar(select(User).where(User.username == username))
    ok = False
    local = providers.local_provider(db)
    if user and user.source == "local":
        if local and local.enabled and (not local.config.get("admins_only") or user.is_admin):
            ok = verify_password(body.password, user.password_hash)
    elif user is None or user.source == "ldap":
        found = _ldap_login(db, user, username, body.password, body.provider)
        ok, user = found is not None, found or user
    if not ok and (user is None or user.source == "local"):
        verify_password(body.password, _DUMMY_HASH)  # equalize timing: don't reveal which usernames exist
    if not ok or not user or not user.is_active:
        db.rollback()
        _record(db, username, ip, False)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD)

    user.last_login_at = utcnow()
    db.commit()
    _record(db, username, ip, True)
    set_session(response, user)
    return me_out(db, user)


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_out(db, user)


# ---------- OpenID Connect SSO
def _oidc_provider(db: Session, slug: str) -> AuthProvider:
    p = db.scalar(select(AuthProvider).where(AuthProvider.slug == slug, AuthProvider.type == "oidc",
                                             AuthProvider.enabled.is_(True)))
    if not p:
        raise HTTPException(404, "Unknown sign-in provider")
    return p


def redirect_uri(slug: str) -> str:
    return f"{get_settings().base_url.rstrip('/')}/api/auth/oidc/{slug}/callback"


def _safe_next(nxt: str) -> str:
    # only same-site relative paths: no open redirect via //evil.com or /\\evil.com
    return nxt if nxt.startswith("/") and not nxt.startswith(("//", "/\\")) else "/"


def _fail(code: str) -> RedirectResponse:
    r = RedirectResponse(f"/?login_error={quote(code)}", status_code=303)
    r.delete_cookie(FLOW_COOKIE, path="/api/auth/oidc")
    return r


@router.get("/oidc/{slug}/login", include_in_schema=False)
def oidc_login(slug: str, next: str = "/", db: Session = Depends(get_db)):
    s = get_settings()
    p = _oidc_provider(db, slug)
    flow = oidc.new_flow()
    try:
        url = oidc.authorize_url(providers.oidc_config(p), redirect_uri(slug), flow)
    except oidc.OidcError as e:
        log.error("oidc %s: %s", slug, e)
        return _fail("sso_unavailable")
    cookie = jwt.encode({**flow, "slug": slug, "next": _safe_next(next),
                         "exp": datetime.now(timezone.utc) + timedelta(minutes=10)}, s.secret_key, algorithm="HS256")
    r = RedirectResponse(url, status_code=303)
    r.set_cookie(FLOW_COOKIE, cookie, httponly=True, secure=s.cookie_secure, samesite="lax", max_age=600,
                 path="/api/auth/oidc")
    return r


def _oidc_user(db: Session, p: AuthProvider, ou: oidc.OidcUser, cfg: oidc.OidcConfig) -> User | None:
    user = db.scalar(select(User).where(User.provider_id == p.id, User.external_id == ou.sub))
    if user is None and cfg.link_by_email and ou.email and ou.email_verified:
        user = db.scalar(select(User).where(func.lower(User.email) == ou.email.lower(), User.source != "local"))
        if user:
            user.provider_id, user.external_id, user.source = p.id, ou.sub, "oidc"
    if user is None:
        if not cfg.auto_create:
            return None
        name, n = ou.username, 1
        while db.scalar(select(User.id).where(User.username == name)):
            n += 1
            name = f"{ou.username[:140]}-{n}"
        user = User(id=uuid.uuid4(), username=name, source="oidc", provider_id=p.id, external_id=ou.sub,
                    display_name=ou.display_name, is_active=True, is_admin=False)
        db.add(user)
        db.flush()
    user.display_name, user.email = ou.display_name, ou.email or user.email
    if ou.is_admin is not None:
        user.is_admin = ou.is_admin
    sync_groups(db, user, p, ou.groups)
    return user


@router.get("/oidc/{slug}/callback", include_in_schema=False)
def oidc_callback(slug: str, request: Request, code: str = "", state: str = "", error: str = "",
                  db: Session = Depends(get_db)):
    s = get_settings()
    if error:
        return _fail("sso_denied")
    try:
        flow = jwt.decode(request.cookies.get(FLOW_COOKIE, ""), s.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return _fail("sso_expired")
    if flow.get("slug") != slug or not state or state != flow.get("state") or not code:
        return _fail("sso_state")
    p = _oidc_provider(db, slug)
    cfg = providers.oidc_config(p)
    try:
        ou = oidc.complete(cfg, code, redirect_uri(slug), flow)
    except oidc.OidcError as e:
        log.warning("oidc %s callback: %s", slug, e)
        return _fail("sso_not_allowed" if str(e) == "not_allowed" else "sso_failed")
    user = _oidc_user(db, p, ou, cfg)
    if not user or not user.is_active:
        db.rollback()
        return _fail("sso_no_account")
    user.last_login_at = utcnow()
    db.commit()
    r = RedirectResponse(_safe_next(flow.get("next", "/")), status_code=303)
    r.delete_cookie(FLOW_COOKIE, path="/api/auth/oidc")
    set_session(r, user)
    return r
