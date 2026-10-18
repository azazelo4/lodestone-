from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Project, ProjectMember, Role, User
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


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return user


def role_in(db: Session, project: Project, user: User) -> Role | None:
    if user.is_admin:
        return Role.admin
    m = db.get(ProjectMember, (project.id, user.id))
    return m.role if m else None


RANK = {Role.viewer: 1, Role.member: 2, Role.admin: 3}


def project_for(db: Session, key: str, user: User, need: Role = Role.viewer) -> tuple[Project, Role | None]:
    """Loads project by key and checks access. Private projects look like 404 to non-members."""
    project = db.scalar(select(Project).where(Project.key == key.upper()))
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    role = role_in(db, project, user)
    if role is None and project.is_private:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    effective = role or (Role.viewer if not project.is_private else None)
    if effective is None or RANK[effective] < RANK[need]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires project role: {need.value}")
    return project, role
