"""Cycles (time boxes, table "sprints"), modules (groups of issues across cycles) and progress analytics."""
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from .. import progress, rbac
from ..db import get_db
from ..deps import current_user, project_for
from ..models import CLOSED, Activity, Issue, Module, Project, Sprint, State, User, issue_modules, utcnow
from ..schemas import (
    ModuleIn,
    ModuleOut,
    ModulePatch,
    ProgressDetail,
    SprintComplete,
    SprintIn,
    SprintOut,
    SprintPatch,
)

router = APIRouter(prefix="/api/projects", tags=["planning"])


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _check_dates(start: date | None, end: date | None, what: str):
    if start and end and end < start:
        raise HTTPException(422, f"{what} ends before it starts")


# ---------- cycles
def cycle_status(sp: Sprint, today: date | None = None) -> str:
    today = today or _today()
    if sp.closed:
        return "completed"
    if not sp.start_date and not sp.end_date:
        return "draft"
    if sp.start_date and today < sp.start_date:
        return "upcoming"
    if sp.end_date and today > sp.end_date:
        return "ended"  # past its end date, waiting to be completed
    return "active"


def _cycle(db: Session, project: Project, cycle_id: uuid.UUID) -> Sprint:
    sp = db.get(Sprint, cycle_id)
    if not sp or sp.project_id != project.id:
        raise HTTPException(404, "Cycle not found")
    return sp


def _cycle_out(sp: Sprint, stats: dict | None) -> SprintOut:
    o = SprintOut.model_validate(sp, from_attributes=True)
    o.status = cycle_status(sp)
    if stats:
        o.progress = stats
    return o


def _no_overlap(db: Session, project: Project, sp_id: uuid.UUID | None, start: date | None, end: date | None):
    """Two open cycles of a project cannot overlap in time, so "the current cycle" is always one."""
    if not (start and end):
        return
    for other in db.scalars(select(Sprint).where(Sprint.project_id == project.id, Sprint.closed.is_(False),
                                                 Sprint.start_date.is_not(None), Sprint.end_date.is_not(None))):
        if other.id != sp_id and other.start_date <= end and start <= other.end_date:
            raise HTTPException(409, f"Dates overlap with cycle “{other.name}”")


@router.get("/{key}/sprints", response_model=list[SprintOut])
def cycles(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    rows = db.scalars(select(Sprint).where(Sprint.project_id == p.id)
                      .order_by(Sprint.closed, Sprint.start_date.nulls_last(), Sprint.name)).all()
    stats = progress.grouped(db, Issue.sprint_id, [Issue.project_id == p.id, Issue.sprint_id.is_not(None)])
    return [_cycle_out(sp, stats.get(sp.id)) for sp in rows]


@router.post("/{key}/sprints", response_model=SprintOut, status_code=201)
def add_cycle(key: str, body: SprintIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.SPRINTS_MANAGE)
    _check_dates(body.start_date, body.end_date, "Cycle")
    _no_overlap(db, p, None, body.start_date, body.end_date)
    sp = Sprint(project_id=p.id, **body.model_dump())
    db.add(sp)
    db.commit()
    return _cycle_out(sp, None)


@router.patch("/{key}/sprints/{cycle_id}", response_model=SprintOut)
def patch_cycle(key: str, cycle_id: uuid.UUID, body: SprintPatch, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.SPRINTS_MANAGE)
    sp = _cycle(db, p, cycle_id)
    data = body.model_dump(exclude_unset=True)
    start, end = data.get("start_date", sp.start_date), data.get("end_date", sp.end_date)
    _check_dates(start, end, "Cycle")
    if not data.get("closed", sp.closed):
        _no_overlap(db, p, sp.id, start, end)
    if "closed" in data and data["closed"] != sp.closed:
        sp.closed_at = utcnow() if data["closed"] else None
    for k, v in data.items():
        setattr(sp, k, v)
    db.commit()
    return _cycle_out(sp, progress.grouped(db, Issue.sprint_id, [Issue.sprint_id == sp.id]).get(sp.id))


@router.delete("/{key}/sprints/{cycle_id}", status_code=204)
def delete_cycle(key: str, cycle_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.SPRINTS_MANAGE)
    db.delete(_cycle(db, p, cycle_id))  # issues stay, without a cycle (FK SET NULL)
    db.commit()


@router.post("/{key}/sprints/{cycle_id}/complete", response_model=SprintOut)
def complete_cycle(key: str, cycle_id: uuid.UUID, body: SprintComplete, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """Closes the cycle and moves its unfinished issues to another open cycle or out of any cycle."""
    p, _ = project_for(db, key, user, rbac.SPRINTS_MANAGE)
    sp = _cycle(db, p, cycle_id)
    target = None
    if body.move_to:
        target = _cycle(db, p, body.move_to)
        if target.closed or target.id == sp.id:
            raise HTTPException(422, "Unfinished issues can only move to another open cycle")
    unfinished = db.scalars(select(Issue).join(State, State.id == Issue.state_id)
                            .where(Issue.sprint_id == sp.id, State.category.notin_(CLOSED))).all()
    for i in unfinished:
        db.add(Activity(issue_id=i.id, actor_id=user.id, field="sprint", old_value=sp.name,
                        new_value=target.name if target else None, old_ref=str(sp.id),
                        new_ref=str(target.id) if target else None))
    if unfinished:
        db.execute(update(Issue).where(Issue.id.in_([i.id for i in unfinished]))
                   .values(sprint_id=target.id if target else None, updated_at=utcnow()))
    sp.closed, sp.closed_at = True, utcnow()
    db.commit()
    return _cycle_out(sp, progress.grouped(db, Issue.sprint_id, [Issue.sprint_id == sp.id]).get(sp.id))


@router.get("/{key}/sprints/{cycle_id}/progress", response_model=ProgressDetail)
def cycle_progress(key: str, cycle_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    sp = _cycle(db, p, cycle_id)
    rows = progress.issue_rows(db, [Issue.sprint_id == sp.id])
    start, end = progress.default_range(sp.start_date, sp.end_date, rows)
    return {"progress": progress.totals(rows), "start": start, "end": end,
            "burndown": progress.burndown(rows, start, end), "people": progress.people(db, rows)}


# ---------- modules
def _module(db: Session, project: Project, module_id: uuid.UUID) -> Module:
    m = db.scalar(select(Module).options(selectinload(Module.lead)).where(Module.id == module_id))
    if not m or m.project_id != project.id:
        raise HTTPException(404, "Module not found")
    return m


def _lead(db: Session, project: Project, lead_id: uuid.UUID | None) -> uuid.UUID | None:
    if lead_id is None:
        return None
    ok = db.scalar(select(User.id).where(User.id == lead_id, User.is_active.is_(True),
                                         User.id.in_(rbac.project_user_ids(project.id))))
    if not ok:
        raise HTTPException(422, "The lead must be an active project member")
    return lead_id


def _unique_name(db: Session, project: Project, name: str, module_id: uuid.UUID | None = None):
    other = db.scalar(select(Module.id).where(Module.project_id == project.id, Module.name.ilike(name.strip())))
    if other and other != module_id:
        raise HTTPException(409, "A module with this name exists")


def _module_stats(db: Session, where) -> dict:
    return progress.grouped(db, issue_modules.c.module_id, where,
                            join=(issue_modules, issue_modules.c.issue_id == Issue.id))


def _module_out(db: Session, m: Module) -> ModuleOut:
    o = ModuleOut.model_validate(m, from_attributes=True)
    stats = _module_stats(db, [issue_modules.c.module_id == m.id]).get(m.id)
    if stats:
        o.progress = stats
    return o


@router.get("/{key}/modules", response_model=list[ModuleOut])
def modules(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    rows = db.scalars(select(Module).options(selectinload(Module.lead)).where(Module.project_id == p.id)
                      .order_by(Module.name)).all()
    stats = _module_stats(db, [Issue.project_id == p.id])
    out = []
    for m in rows:
        o = ModuleOut.model_validate(m, from_attributes=True)
        if m.id in stats:
            o.progress = stats[m.id]
        out.append(o)
    return out


@router.post("/{key}/modules", response_model=ModuleOut, status_code=201)
def add_module(key: str, body: ModuleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.MODULES_MANAGE)
    _check_dates(body.start_date, body.target_date, "Module")
    _unique_name(db, p, body.name)
    m = Module(project_id=p.id, **{**body.model_dump(), "name": body.name.strip(),
                                    "lead_id": _lead(db, p, body.lead_id)})
    db.add(m)
    db.commit()
    return _module_out(db, _module(db, p, m.id))


@router.patch("/{key}/modules/{module_id}", response_model=ModuleOut)
def patch_module(key: str, module_id: uuid.UUID, body: ModulePatch, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.MODULES_MANAGE)
    m = _module(db, p, module_id)
    data = body.model_dump(exclude_unset=True)
    _check_dates(data.get("start_date", m.start_date), data.get("target_date", m.target_date), "Module")
    if "name" in data:
        _unique_name(db, p, data["name"], m.id)
        data["name"] = data["name"].strip()
    if "lead_id" in data:
        data["lead_id"] = _lead(db, p, data["lead_id"])
    for k, v in data.items():
        setattr(m, k, v)
    db.commit()
    db.expire_all()
    return _module_out(db, _module(db, p, m.id))


@router.delete("/{key}/modules/{module_id}", status_code=204)
def delete_module(key: str, module_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.MODULES_MANAGE)
    db.delete(_module(db, p, module_id))  # issues stay; only the link goes
    db.commit()


@router.get("/{key}/modules/{module_id}/progress", response_model=ProgressDetail)
def module_progress(key: str, module_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    m = _module(db, p, module_id)
    rows = progress.issue_rows(db, [Issue.id.in_(select(issue_modules.c.issue_id)
                                                 .where(issue_modules.c.module_id == m.id))])
    start, end = progress.default_range(m.start_date or m.created_at.date(), m.target_date, rows)
    return {"progress": progress.totals(rows), "start": start, "end": end,
            "burndown": progress.burndown(rows, start, end), "people": progress.people(db, rows)}


# ---------- project analytics
@router.get("/{key}/analytics")
def analytics(key: str, weeks: int = Query(default=12, ge=2, le=52), db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    return progress.project_report(db, p.id, weeks)
