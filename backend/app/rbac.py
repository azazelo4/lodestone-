"""Role-based access control.

A permission is a string like "issues.edit". Roles are named sets of permissions and live in the database,
so admins can add their own. Two scopes:
  * global roles: given to users directly or via directory groups; a project permission inside a global role
    applies to every project (e.g. an "Auditor" role with project.read sees all projects);
  * project roles: given per project to a user (project_members) or to a directory group (group_bindings).

users.is_admin stays as the superuser flag (break-glass admin, LDAP/OIDC admin group): it has every permission.
"""
import uuid

from sqlalchemy import and_, exists, func, or_, select, true
from sqlalchemy.orm import Session

from .models import GroupBinding, Project, ProjectMember, Role, User, UserGroup, UserRole

# ---------- catalog
USERS_MANAGE = "users.manage"
ROLES_MANAGE = "roles.manage"
AUTH_MANAGE = "auth.manage"
PROJECTS_CREATE = "projects.create"
NOTIFICATIONS_MANAGE = "notifications.manage"

PROJECT_READ = "project.read"
PROJECT_MANAGE = "project.manage"
MEMBERS_MANAGE = "members.manage"
ISSUES_CREATE = "issues.create"
ISSUES_EDIT = "issues.edit"
ISSUES_DELETE = "issues.delete"
COMMENTS_CREATE = "comments.create"
COMMENTS_MODERATE = "comments.moderate"
LABELS_MANAGE = "labels.manage"
SPRINTS_MANAGE = "sprints.manage"

GLOBAL_PERMISSIONS = [USERS_MANAGE, ROLES_MANAGE, AUTH_MANAGE, NOTIFICATIONS_MANAGE, PROJECTS_CREATE]
PROJECT_PERMISSIONS = [PROJECT_READ, PROJECT_MANAGE, MEMBERS_MANAGE, ISSUES_CREATE, ISSUES_EDIT, ISSUES_DELETE,
                       COMMENTS_CREATE, COMMENTS_MODERATE, LABELS_MANAGE, SPRINTS_MANAGE]
ALL_PERMISSIONS = GLOBAL_PERMISSIONS + PROJECT_PERMISSIONS

# builtin roles: key -> (scope, name, permissions). Project "admin" always keeps every project permission.
MEMBER_PERMS = [PROJECT_READ, ISSUES_CREATE, ISSUES_EDIT, COMMENTS_CREATE, LABELS_MANAGE, SPRINTS_MANAGE]
BUILTIN_ROLES = {
    "admin": ("project", "Project admin", PROJECT_PERMISSIONS),
    "member": ("project", "Member", MEMBER_PERMS),
    "viewer": ("project", "Viewer", [PROJECT_READ]),
    "user": ("global", "User", [PROJECTS_CREATE]),  # default: every signed-in user has it
}
DEFAULT_PROJECT_ROLE = "member"
LOCKED_ROLES = {"admin"}  # permissions cannot be edited: a project must always have a way to be managed


def valid_permissions(scope: str, perms: list[str]) -> list[str]:
    allowed = ALL_PERMISSIONS if scope == "global" else PROJECT_PERMISSIONS
    bad = [p for p in perms if p not in allowed]
    if bad:
        raise ValueError(f"Unknown permissions for {scope} role: {', '.join(bad)}")
    return sorted(set(perms), key=ALL_PERMISSIONS.index)


# ---------- group matching
def _group_match(user: User):
    """SQL condition: a group binding applies to this user (case-insensitive group name, optional provider)."""
    return exists().where(
        UserGroup.user_id == user.id,
        UserGroup.name == func.lower(GroupBinding.group),
        or_(GroupBinding.provider_id.is_(None), GroupBinding.provider_id == UserGroup.provider_id),
    )


def _perms_of(roles) -> set[str]:
    out: set[str] = set()
    for r in roles:
        out.update(r.permissions or [])
    return out


# ---------- effective permissions
def global_permissions(db: Session, user: User) -> set[str]:
    if user.is_admin:
        return set(ALL_PERMISSIONS)
    direct = select(UserRole.role_id).where(UserRole.user_id == user.id)
    via_group = select(GroupBinding.role_id).where(GroupBinding.project_id.is_(None), _group_match(user))
    roles = db.scalars(select(Role).where(Role.scope == "global", or_(
        Role.is_default.is_(True), Role.id.in_(direct), Role.id.in_(via_group)))).all()
    return _perms_of(roles)


def project_permissions(db: Session, project: Project, user: User, global_perms: set[str] | None = None) -> set[str]:
    if user.is_admin:
        return set(PROJECT_PERMISSIONS)
    gp = global_permissions(db, user) if global_perms is None else global_perms
    perms = {p for p in gp if p in PROJECT_PERMISSIONS}
    direct = select(ProjectMember.role_id).where(ProjectMember.project_id == project.id,
                                                 ProjectMember.user_id == user.id)
    via_group = select(GroupBinding.role_id).where(GroupBinding.project_id == project.id, _group_match(user))
    perms |= _perms_of(db.scalars(select(Role).where(or_(Role.id.in_(direct), Role.id.in_(via_group)))).all())
    if not project.is_private:
        perms.add(PROJECT_READ)  # public project: every signed-in user can read
    if perms and PROJECT_READ not in perms:
        perms.add(PROJECT_READ)  # any role in a project implies seeing it
    return perms


def direct_role(db: Session, project: Project, user: User) -> Role | None:
    m = db.get(ProjectMember, (project.id, user.id))
    return db.get(Role, m.role_id) if m else None


def visible_projects(db: Session, user: User):
    """SQL condition on Project: projects the user can read. Used for lists (projects, my issues)."""
    if user.is_admin or PROJECT_READ in global_permissions(db, user):
        return true()
    member = exists().where(ProjectMember.project_id == Project.id, ProjectMember.user_id == user.id)
    via_group = exists().where(and_(GroupBinding.project_id == Project.id, _group_match(user)))
    return or_(Project.is_private.is_(False), member, via_group)


def project_user_ids(project_id: uuid.UUID):
    """Select of user ids that belong to the project directly or through a bound directory group."""
    direct = select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
    via_group = (select(UserGroup.user_id).join(GroupBinding, and_(
        UserGroup.name == func.lower(GroupBinding.group),
        or_(GroupBinding.provider_id.is_(None), GroupBinding.provider_id == UserGroup.provider_id)))
        .where(GroupBinding.project_id == project_id))
    return direct.union(via_group)


def can_grant(granter_perms: set[str], role: Role) -> bool:
    """No privilege escalation: you can only hand out permissions you hold yourself."""
    return set(role.permissions or []) <= granter_perms
