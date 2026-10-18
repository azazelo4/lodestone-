import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .. import rbac
from ..db import get_db
from ..deps import current_user, require
from ..models import Role, User, UserGroup, UserRole
from ..schemas import LocalUserIn, RoleBrief, UserAdminPatch, UserBrief, UserOut, UserRolesIn
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
def all_users(db: Session = Depends(get_db), _: User = Depends(require(rbac.USERS_MANAGE))):
    return db.scalars(select(User).order_by(User.display_name)).all()


def _superuser_only(me: User, wants_admin: bool | None):
    if wants_admin is not None and not me.is_admin:
        raise HTTPException(403, "Only administrators can grant or remove administrator rights")


@router.post("", response_model=UserOut, status_code=201)
def create_local_user(body: LocalUserIn, db: Session = Depends(get_db),
                      me: User = Depends(require(rbac.USERS_MANAGE))):
    _superuser_only(me, body.is_admin or None)
    if db.scalar(select(User).where(User.username == body.username.lower())):
        raise HTTPException(409, "Username already exists")
    u = User(username=body.username.lower(), display_name=body.display_name, email=body.email, source="local",
             password_hash=hash_password(body.password), is_admin=body.is_admin)
    db.add(u)
    db.commit()
    return u


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(user_id: uuid.UUID, body: UserAdminPatch, db: Session = Depends(get_db),
               me: User = Depends(require(rbac.USERS_MANAGE))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    _superuser_only(me, body.is_admin)
    if u.is_admin and not me.is_admin:
        raise HTTPException(403, "Only administrators can change administrators")
    if u.id == me.id and (body.is_admin is False or body.is_active is False):
        raise HTTPException(400, "You cannot remove your own admin rights or deactivate yourself")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(u, k, v)
    db.commit()
    return u


@router.get("/{user_id}/roles", response_model=list[RoleBrief])
def user_roles(user_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require(rbac.USERS_MANAGE))):
    return db.scalars(select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
                      .order_by(Role.name)).all()


@router.put("/{user_id}/roles", response_model=list[RoleBrief])
def set_user_roles(user_id: uuid.UUID, body: UserRolesIn, db: Session = Depends(get_db),
                   me: User = Depends(require(rbac.USERS_MANAGE))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    roles = db.scalars(select(Role).where(Role.key.in_(body.roles), Role.scope == "global")).all()
    if len(roles) != len(set(body.roles)):
        raise HTTPException(422, "Unknown global role")
    current = set(db.scalars(select(UserRole.role_id).where(UserRole.user_id == u.id)).all())
    changed = {r.id for r in roles} ^ current
    mine = rbac.global_permissions(db, me)
    for r in db.scalars(select(Role).where(Role.id.in_(changed))).all():
        if not rbac.can_grant(mine, r):
            raise HTTPException(403, f"You cannot give or take role {r.key}: it has rights you do not have")
    db.execute(delete(UserRole).where(UserRole.user_id == u.id))
    for r in roles:
        db.add(UserRole(user_id=u.id, role_id=r.id))
    db.commit()
    return sorted(roles, key=lambda r: r.name)


@router.get("/{user_id}/groups", response_model=list[str])
def user_groups(user_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require(rbac.USERS_MANAGE))):
    """Directory groups seen at the last sign-in: helps to write group bindings."""
    return db.scalars(select(UserGroup.name).where(UserGroup.user_id == user_id).order_by(UserGroup.name)).all()
