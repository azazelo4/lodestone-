import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..db import get_db
from ..deps import current_user, project_for, role_in
from ..models import (
    CLOSED,
    DEFAULT_STATES,
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


def _detail(db: Session, p: Project, user: User) -> ProjectDetail:
    open_count = db.scalar(select(func.count()).select_from(Issue).join(State).where(
        Issue.project_id == p.id, State.category.notin_(CLOSED)))
    d = ProjectDetail.model_validate(p, from_attributes=True)
    d.my_role = role_in(db, p, user)
    d.open_issues = open_count or 0
    return d


@router.get("", response_model=list[ProjectDetail])
def list_projects(include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Project).options(selectinload(Project.states), selectinload(Project.lead))
    if not user.is_admin:
        is_member = exists().where(ProjectMember.project_id == Project.id, ProjectMember.user_id == user.id)
        stmt = stmt.where(or_(Project.is_private.is_(False), is_member))
    if not include_archived:
        stmt = stmt.where(Project.archived.is_(False))
    return [_detail(db, p, user) for p in db.scalars(stmt.order_by(Project.name)).all()]


@router.post("", response_model=ProjectDetail, status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if get_settings().project_create == "admins" and not user.is_admin:
        raise HTTPException(403, "Only admins can create projects")
    if db.scalar(select(Project).where(Project.key == body.key)):
        raise HTTPException(409, f"Project key {body.key} is taken")
    p = Project(key=body.key, name=body.name, description=body.description, is_private=body.is_private,
                lead_id=user.id)
    p.states = [State(name=n, category=c, position=i) for i, (n, c) in enumerate(DEFAULT_STATES)]
    p.members = [ProjectMember(user_id=user.id, role=Role.admin)]
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
    p, _ = project_for(db, key, user, Role.admin)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    return _detail(db, p, user)


# ---------- members
@router.get("/{key}/members", response_model=list[MemberOut])
def members(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    return db.scalars(select(ProjectMember).join(User).where(ProjectMember.project_id == p.id)
                      .order_by(User.display_name)).all()


@router.post("/{key}/members", response_model=MemberOut, status_code=201)
def add_member(key: str, body: MemberIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, Role.admin)
    target = db.get(User, body.user_id)
    if not target or not target.is_active:
        raise HTTPException(404, "User not found")
    m = db.get(ProjectMember, (p.id, target.id))
    if m:
        m.role = body.role
    else:
        m = ProjectMember(project_id=p.id, user_id=target.id, role=body.role)
        db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _admins_left(db: Session, p: Project, excluding: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(ProjectMember).where(
        ProjectMember.project_id == p.id, ProjectMember.role == Role.admin, ProjectMember.user_id != excluding)) or 0


@router.patch("/{key}/members/{user_id}", response_model=MemberOut)
def patch_member(key: str, user_id: uuid.UUID, body: MemberPatch, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, Role.admin)
    m = db.get(ProjectMember, (p.id, user_id))
    if not m:
        raise HTTPException(404, "Member not found")
    if m.role == Role.admin and body.role != Role.admin and not _admins_left(db, p, user_id):
        raise HTTPException(400, "A project must keep at least one admin")
    m.role = body.role
    db.commit()
    return m


@router.delete("/{key}/members/{user_id}", status_code=204)
def remove_member(key: str, user_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, Role.admin)
    m = db.get(ProjectMember, (p.id, user_id))
    if not m:
        raise HTTPException(404, "Member not found")
    if m.role == Role.admin and not _admins_left(db, p, user_id):
        raise HTTPException(400, "A project must keep at least one admin")
    db.delete(m)
    db.commit()


# ---------- states
@router.get("/{key}/states", response_model=list[StateOut])
def states(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    return p.states


@router.post("/{key}/states", response_model=StateOut, status_code=201)
def add_state(key: str, body: StateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, Role.admin)
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
    p, _ = project_for(db, key, user, Role.admin)
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
    p, _ = project_for(db, key, user, Role.admin)
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
    p, _ = project_for(db, key, user, Role.member)
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
    p, _ = project_for(db, key, user, Role.member)
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(422, "Sprint ends before it starts")
    sp = Sprint(project_id=p.id, **body.model_dump())
    db.add(sp)
    db.commit()
    return sp


@router.patch("/{key}/sprints/{sprint_id}", response_model=SprintOut)
def patch_sprint(key: str, sprint_id: uuid.UUID, body: SprintPatch, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, Role.member)
    sp = db.get(Sprint, sprint_id)
    if not sp or sp.project_id != p.id:
        raise HTTPException(404, "Sprint not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(sp, k, v)
    db.commit()
    return sp
