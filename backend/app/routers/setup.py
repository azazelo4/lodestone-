"""First-start wizard: create the first admin and choose how people sign in (one or several ways)."""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import providers
from ..config import get_settings
from ..db import get_db
from ..models import AuthProvider, User
from ..schemas import MeOut, ProviderTest, SetupIn, SetupStatus, SetupToken, TestResult
from ..security import hash_password
from .admin import new_provider, run_test
from .auth import me_out, set_session

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _check_token(db: Session, token: str):
    state = providers.setup_state(db)
    if state.get("completed"):
        raise HTTPException(409, "Setup is already completed")
    expected = state.get("token") or ""
    if not expected or not hmac.compare_digest(expected.encode(), token.encode()):
        raise HTTPException(403, "Wrong setup token (see the server log)")


@router.get("", response_model=SetupStatus)
def status(db: Session = Depends(get_db)):
    return SetupStatus(required=providers.setup_required(db), base_url=get_settings().base_url)


@router.post("/verify", status_code=204)
def verify(body: SetupToken, db: Session = Depends(get_db)):
    _check_token(db, body.token)


@router.post("/test", response_model=TestResult)
def test(body: ProviderTest, x_setup_token: str = Header(default=""), db: Session = Depends(get_db)):
    _check_token(db, x_setup_token)
    if not body.provider:
        raise HTTPException(422, "provider is required")
    return run_test(body.provider.type, body.provider.config, body.username)


@router.post("", response_model=MeOut)
def complete(body: SetupIn, response: Response, db: Session = Depends(get_db)):
    _check_token(db, body.token)
    slugs = {"local"}
    for p in body.providers:
        if p.type == "local":
            raise HTTPException(422, "Local accounts are configured with local_mode")
        if p.slug in slugs:
            raise HTTPException(422, f"Duplicate provider id {p.slug}")
        slugs.add(p.slug)
    if not providers.mark_setup_completed(db):  # atomic: a parallel request lost the race
        db.rollback()
        raise HTTPException(409, "Setup is already completed")

    local = db.scalar(select(AuthProvider).where(AuthProvider.type == "local"))
    if local is None:
        local = AuthProvider(slug="local", type="local", name="Local accounts", position=0)
        db.add(local)
    local.enabled, local.config = True, {"admins_only": body.local_mode == "admins"}
    for i, p in enumerate(body.providers, start=1):
        if db.scalar(select(AuthProvider).where(AuthProvider.slug == p.slug)):
            raise HTTPException(409, f"Provider {p.slug} exists")
        db.add(new_provider(p, position=p.position or i))

    username = body.admin.username.lower()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, "Username already exists")
    admin = User(username=username, display_name=body.admin.display_name, email=body.admin.email, source="local",
                 password_hash=hash_password(body.admin.password), is_admin=True, is_active=True)
    db.add(admin)
    db.commit()
    set_session(response, admin)
    return me_out(db, admin)
