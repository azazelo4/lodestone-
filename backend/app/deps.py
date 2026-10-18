from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import rbac
from .db import get_db
from .models import Project, User
from .security import COOKIE, decode_token


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:]
    uid = decode_token(token) if token else None
    user = db.get(User, uid) if uid else None
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


def require(permission: str):
    """Dependency: the user must hold a global permission (e.g. rbac.USERS_MANAGE)."""

    def dep(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        if permission not in rbac.global_permissions(db, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires permission: {permission}")
        return user

    return dep


def project_for(db: Session, key: str, user: User, need: str = rbac.PROJECT_READ) -> tuple[Project, set[str]]:
    """Loads project by key and checks a project permission. Private projects look like 404 to outsiders."""
    project = db.scalar(select(Project).where(Project.key == key.upper()))
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    perms = rbac.project_permissions(db, project, user)
    if rbac.PROJECT_READ not in perms:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if need not in perms:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires permission: {need}")
    return project, perms
