from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ldap_auth
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import LoginAttempt, User, utcnow
from ..schemas import AuthConfig, LoginIn, UserOut
from ..security import COOKIE, create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

BAD = "Wrong username or password"
_DUMMY_HASH = hash_password("timing-equalizer")


@router.get("/config", response_model=AuthConfig)
def auth_config():
    s = get_settings()
    return AuthConfig(ldap=s.ldap_enabled, local=s.local_auth_enabled)


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


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    username = body.username.strip().lower()
    ip = request.client.host if request.client else "-"
    if _locked(db, username):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many failed attempts. Try again in {s.login_lock_minutes} min")

    user = db.scalar(select(User).where(User.username == username))
    ok = False
    if user and user.source == "local" and s.local_auth_enabled:
        ok = verify_password(body.password, user.password_hash)
    elif s.ldap_enabled and (user is None or user.source == "ldap"):
        try:
            lu = ldap_auth.authenticate(s, username, body.password)
        except ldap_auth.LdapUnavailable:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Directory service is unavailable") from None
        if lu:
            ok = True
            if user is None:
                user = User(username=lu.username, source="ldap", display_name=lu.display_name,
                            is_active=True, is_admin=False)
                db.add(user)
            user.display_name, user.email = lu.display_name, lu.email
            if get_settings().ldap_admin_group:
                user.is_admin = lu.is_admin  # directory is the source of truth for admin rights
    if not ok and (user is None or user.source == "local"):
        verify_password(body.password, _DUMMY_HASH)  # equalize timing: don't reveal which usernames exist
    if not ok or not user or not user.is_active:
        _record(db, username, ip, False)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD)

    user.last_login_at = utcnow()
    db.commit()
    _record(db, username, ip, True)
    response.set_cookie(COOKIE, create_token(user.id), httponly=True, secure=s.cookie_secure, samesite="lax",
                        max_age=s.session_hours * 3600, path="/")
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
