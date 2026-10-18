import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import rbac
from ..db import get_db
from ..deps import current_user, project_for
from ..models import (
    CLOSED,
    DEFAULT_STATES,
    GroupBinding,
    Issue,
    Label,
    Project,
    ProjectMember,
    Role,
    Sprint,
    State,
    User,
)
from ..schemas import (
    BindingIn,
    BindingOut,
    LabelIn,
    LabelOut,
    MemberIn,
    MemberOut,
    MemberPatch,
    ProjectDetail,
    ProjectIn,
    ProjectPatch,
    SprintIn,
    SprintOut,
    SprintPatch,
    StateIn,
    StateOut,
    StatePatch,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _detail(db: Session, p: Project, user: User, gp: set[str] | None = None) -> ProjectDetail:
    open_count = db.scalar(select(func.count()).select_from(Issue).join(State).where(
        Issue.project_id == p.id, State.category.notin_(CLOSED)))
    d = ProjectDetail.model_validate(p, from_attributes=True)
    role = rbac.direct_role(db, p, user)
    d.my_role = role.key if role else None
    d.my_permissions = sorted(rbac.project_permissions(db, p, user, gp), key=rbac.ALL_PERMISSIONS.index)
    d.open_issues = open_count or 0
    return d


def _role(db: Session, key: str) -> Role:
    r = db.scalar(select(Role).where(Role.key == key, Role.scope == "project"))
    if not r:
        raise HTTPException(422, f"Unknown project role {key}")
    return r


@router.get("", response_model=list[ProjectDetail])
def list_projects(include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = (select(Project).options(selectinload(Project.states), selectinload(Project.lead))
            .where(rbac.visible_projects(db, user)))
    if not include_archived:
        stmt = stmt.where(Project.archived.is_(False))
    gp = rbac.global_permissions(db, user)
    return [_detail(db, p, user, gp) for p in db.scalars(stmt.order_by(Project.name)).all()]


@router.post("", response_model=ProjectDetail, status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if rbac.PROJECTS_CREATE not in rbac.global_permissions(db, user):
        raise HTTPException(403, f"Requires permission: {rbac.PROJECTS_CREATE}")
    if db.scalar(select(Project).where(Project.key == body.key)):
        raise HTTPException(409, f"Project key {body.key} is taken")
    p = Project(key=body.key, name=body.name, description=body.description, is_private=body.is_private,
                lead_id=user.id)
    p.states = [State(name=n, category=c, position=i) for i, (n, c) in enumerate(DEFAULT_STATES)]
    p.members = [ProjectMember(user_id=user.id, role_id=_role(db, "admin").id)]
    db.add(p)
    db.commit()
    db.refresh(p)
    return _detail(db, p, user)


@router.get("/{key}", response_model=ProjectDetail)
def get_project(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    return _detail(db, p, user)


@router.patch("/{key}", response_model=ProjectDetail)
def patch_project(key: str, body: ProjectPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.PROJECT_MANAGE)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    return _detail(db, p, user)


# ---------- members
@router.get("/{key}/members", response_model=list[MemberOut])
def members(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    return db.scalars(select(ProjectMember).options(selectinload(ProjectMember.role)).join(User)
                      .where(ProjectMember.project_id == p.id).order_by(User.display_name)).all()


def _grantable(perms: set[str], role: Role, user: User):
    if not user.is_admin and not rbac.can_grant(perms, role):
        raise HTTPException(403, "You cannot give a role with more rights than your own")


def _managers_left(db: Session, p: Project, excluding: uuid.UUID) -> int:
    managing = select(Role.id).where(Role.permissions.any(rbac.MEMBERS_MANAGE))
    direct = db.scalar(select(func.count()).select_from(ProjectMember).where(
        ProjectMember.project_id == p.id, ProjectMember.role_id.in_(managing), ProjectMember.user_id != excluding))
    groups = db.scalar(select(func.count()).select_from(GroupBinding).where(
        GroupBinding.project_id == p.id, GroupBinding.role_id.in_(managing)))
    return (direct or 0) + (groups or 0)


@router.post("/{key}/members", response_model=MemberOut, status_code=201)
def add_member(key: str, body: MemberIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, perms = project_for(db, key, user, rbac.MEMBERS_MANAGE)
    role = _role(db, body.role)
    _grantable(perms, role, user)
    target = db.get(User, body.user_id)
    if not target or not target.is_active:
        raise HTTPException(404, "User not found")
    m = db.get(ProjectMember, (p.id, target.id))
    if m:
        m.role_id = role.id
    else:
        m = ProjectMember(project_id=p.id, user_id=target.id, role_id=role.id)
        db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.patch("/{key}/members/{user_id}", response_model=MemberOut)
def patch_member(key: str, user_id: uuid.UUID, body: MemberPatch, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    p, perms = project_for(db, key, user, rbac.MEMBERS_MANAGE)
    m = db.get(ProjectMember, (p.id, user_id))
    if not m:
        raise HTTPException(404, "Member not found")
    role = _role(db, body.role)
    _grantable(perms, role, user)
    _grantable(perms, m.role, user)  # cannot demote someone above you either
    if (rbac.MEMBERS_MANAGE in m.role.permissions and rbac.MEMBERS_MANAGE not in role.permissions
            and not _managers_left(db, p, user_id)):
        raise HTTPException(400, "A project must keep at least one admin")
    m.role_id = role.id
    db.commit()
    db.refresh(m)
    return m


@router.delete("/{key}/members/{user_id}", status_code=204)
def remove_member(key: str, user_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, perms = project_for(db, key, user, rbac.MEMBERS_MANAGE)
    m = db.get(ProjectMember, (p.id, user_id))
    if not m:
        raise HTTPException(404, "Member not found")
    _grantable(perms, m.role, user)
    if rbac.MEMBERS_MANAGE in m.role.permissions and not _managers_left(db, p, user_id):
        raise HTTPException(400, "A project must keep at least one admin")
    db.delete(m)
    db.commit()


# ---------- directory groups with a role in this project
@router.get("/{key}/group-bindings", response_model=list[BindingOut])
def group_bindings(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .admin import binding_out

    p, _ = project_for(db, key, user)
    rows = db.scalars(select(GroupBinding).options(selectinload(GroupBinding.role), selectinload(GroupBinding.provider))
                      .where(GroupBinding.project_id == p.id).order_by(GroupBinding.group)).all()
    return [binding_out(b, p.key) for b in rows]


@router.post("/{key}/group-bindings", response_model=BindingOut, status_code=201)
def add_group_binding(key: str, body: BindingIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .admin import binding_out, resolve_binding

    p, perms = project_for(db, key, user, rbac.MEMBERS_MANAGE)
    role, provider = resolve_binding(db, body, "project")
    _grantable(perms, role, user)
    b = GroupBinding(group=body.group.strip(), role_id=role.id, provider_id=provider.id if provider else None,
                     project_id=p.id)
    db.add(b)
    db.commit()
    db.refresh(b)
    return binding_out(b, p.key)


@router.delete("/{key}/group-bindings/{binding_id}", status_code=204)
def delete_group_binding(key: str, binding_id: uuid.UUID, db: Session = Depends(get_db),
                         user: User = Depends(current_user)):
    p, perms = project_for(db, key, user, rbac.MEMBERS_MANAGE)
    b = db.get(GroupBinding, binding_id)
    if not b or b.project_id != p.id:
        raise HTTPException(404, "Binding not found")
    _grantable(perms, b.role, user)
    db.delete(b)
    db.commit()


# ---------- states
@router.get("/{key}/states", response_model=list[StateOut])
def states(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    return p.states


@router.post("/{key}/states", response_model=StateOut, status_code=201)
def add_state(key: str, body: StateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.PROJECT_MANAGE)
    if any(s.name.lower() == body.name.lower() for s in p.states):
        raise HTTPException(409, "State with this name exists")
    pos = body.position if body.position is not None else (max((s.position for s in p.states), default=-1) + 1)
    st = State(project_id=p.id, name=body.name, category=body.category, position=pos)
    db.add(st)
    db.commit()
    return st


@router.patch("/{key}/states/{state_id}", response_model=StateOut)
def patch_state(key: str, state_id: uuid.UUID, body: StatePatch, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.PROJECT_MANAGE)
    st = db.get(State, state_id)
    if not st or st.project_id != p.id:
        raise HTTPException(404, "State not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(st, k, v)
    db.commit()
    return st


@router.delete("/{key}/states/{state_id}", status_code=204)
def delete_state(key: str, state_id: uuid.UUID, move_to: uuid.UUID | None = None, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.PROJECT_MANAGE)
    st = db.get(State, state_id)
    if not st or st.project_id != p.id:
        raise HTTPException(404, "State not found")
    used = db.scalar(select(func.count()).select_from(Issue).where(Issue.state_id == st.id))
    if used:
        target = db.get(State, move_to) if move_to else None
        if not target or target.project_id != p.id or target.id == st.id:
            raise HTTPException(409, f"{used} issues use this state; pass ?move_to=<state id>")
        db.query(Issue).filter(Issue.state_id == st.id).update({Issue.state_id: target.id})
    db.delete(st)
    db.commit()


# ---------- labels
@router.get("/{key}/labels", response_model=list[LabelOut])
def labels(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    return db.scalars(select(Label).where(Label.project_id == p.id).order_by(Label.name)).all()


@router.post("/{key}/labels", response_model=LabelOut, status_code=201)
def add_label(key: str, body: LabelIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.LABELS_MANAGE)
    if db.scalar(select(Label).where(Label.project_id == p.id, func.lower(Label.name) == body.name.lower())):
        raise HTTPException(409, "Label exists")
    lb = Label(project_id=p.id, name=body.name, color=body.color)
    db.add(lb)
    db.commit()
    return lb


# ---------- sprints
@router.get("/{key}/sprints", response_model=list[SprintOut])
def sprints(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    return db.scalars(select(Sprint).where(Sprint.project_id == p.id)
                      .order_by(Sprint.closed, Sprint.start_date.nulls_last(), Sprint.name)).all()


@router.post("/{key}/sprints", response_model=SprintOut, status_code=201)
def add_sprint(key: str, body: SprintIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.SPRINTS_MANAGE)
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(422, "Sprint ends before it starts")
    sp = Sprint(project_id=p.id, **body.model_dump())
    db.add(sp)
    db.commit()
    return sp


@router.patch("/{key}/sprints/{sprint_id}", response_model=SprintOut)
def patch_sprint(key: str, sprint_id: uuid.UUID, body: SprintPatch, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.SPRINTS_MANAGE)
    sp = db.get(Sprint, sprint_id)
    if not sp or sp.project_id != p.id:
        raise HTTPException(404, "Sprint not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(sp, k, v)
    db.commit()
    return sp
