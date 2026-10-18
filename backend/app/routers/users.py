import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import admin_user, current_user
from ..models import User
from ..schemas import LocalUserIn, UserAdminPatch, UserBrief, UserOut
from ..security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserBrief])
def search_users(q: str = "", limit: int = 20, db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(User).where(User.is_active.is_(True))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.display_name.ilike(like), User.email.ilike(like)))
    return db.scalars(stmt.order_by(User.display_name).limit(min(limit, 100))).all()


@router.get("/all", response_model=list[UserOut])
def all_users(db: Session = Depends(get_db), _: User = Depends(admin_user)):
    return db.scalars(select(User).order_by(User.display_name)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_local_user(body: LocalUserIn, db: Session = Depends(get_db), _: User = Depends(admin_user)):
    if db.scalar(select(User).where(User.username == body.username.lower())):
        raise HTTPException(409, "Username already exists")
    u = User(username=body.username.lower(), display_name=body.display_name, email=body.email, source="local",
             password_hash=hash_password(body.password), is_admin=body.is_admin)
    db.add(u)
    db.commit()
    return u


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(user_id: uuid.UUID, body: UserAdminPatch, db: Session = Depends(get_db),
               me: User = Depends(admin_user)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == me.id and (body.is_admin is False or body.is_active is False):
        raise HTTPException(400, "You cannot remove your own admin rights or deactivate yourself")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(u, k, v)
    db.commit()
    return u
