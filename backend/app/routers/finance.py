"""Project finance: budget, hourly rates, time logged on issues, other expenses and the plan-vs-actual summary.

Hours are visible to everyone who sees the project; money (rates, costs, budget, expenses) needs finance.view.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import finance, rbac
from ..db import get_db
from ..deps import current_user, project_for
from ..models import Expense, Issue, MemberRate, Module, Project, ProjectFinance, User, Worklog
from ..schemas import (
    ExpenseIn,
    ExpenseOut,
    ExpensePatch,
    FinanceSettingsIn,
    FinanceSettingsOut,
    FinanceSummary,
    IssueWorklogs,
    NamedRef,
    RateIn,
    RateOut,
    UserBrief,
    WorklogIn,
    WorklogOut,
    WorklogPatch,
)
from .issues import KEY, _load

router = APIRouter(prefix="/api", tags=["finance"])


def sees_money(perms: set[str]) -> bool:
    return rbac.FINANCE_VIEW in perms or rbac.FINANCE_MANAGE in perms


def _viewer(db: Session, key: str, user: User) -> Project:
    p, perms = project_for(db, key, user)
    if not sees_money(perms):
        raise HTTPException(403, f"Requires permission: {rbac.FINANCE_VIEW}")
    return p


def _settings_out(fin: ProjectFinance) -> FinanceSettingsOut:
    return FinanceSettingsOut(
        currency=fin.currency, budget=finance.money(fin.budget), budget_hours=finance.money(fin.budget_hours),
        default_rate=finance.money(fin.default_rate), start_date=fin.start_date, end_date=fin.end_date)


# ---------- summary and settings
@router.get("/projects/{key}/finance", response_model=FinanceSummary)
def summary(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return finance.summary(db, _viewer(db, key, user))


@router.put("/projects/{key}/finance/settings", response_model=FinanceSettingsOut)
def save_settings(key: str, body: FinanceSettingsIn, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.FINANCE_MANAGE)
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(422, "The project ends before it starts")
    fin = db.get(ProjectFinance, p.id) or ProjectFinance(project_id=p.id)
    for k, v in body.model_dump().items():
        setattr(fin, k, v)
    db.add(fin)
    db.commit()
    return _settings_out(fin)


# ---------- rates
def _rate_out(r: MemberRate) -> RateOut:
    return RateOut(id=r.id, user=UserBrief.model_validate(r.user, from_attributes=True), rate=float(r.rate),
                   valid_from=r.valid_from)


@router.get("/projects/{key}/finance/rates", response_model=list[RateOut])
def rates(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _viewer(db, key, user)
    rows = db.scalars(select(MemberRate).options(selectinload(MemberRate.user)).where(MemberRate.project_id == p.id)
                      .join(User, User.id == MemberRate.user_id).order_by(User.display_name, MemberRate.valid_from))
    return [_rate_out(r) for r in rows]


@router.post("/projects/{key}/finance/rates", response_model=RateOut, status_code=201)
def set_rate(key: str, body: RateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Sets a person's rate from a date; a second rate on the same date replaces the first."""
    p, _ = project_for(db, key, user, rbac.FINANCE_MANAGE)
    if not db.get(User, body.user_id):
        raise HTTPException(422, "Unknown user")
    r = db.scalar(select(MemberRate).where(MemberRate.project_id == p.id, MemberRate.user_id == body.user_id,
                                           MemberRate.valid_from == body.valid_from))
    if r:
        r.rate = body.rate
    else:
        r = MemberRate(project_id=p.id, **body.model_dump())
        db.add(r)
    db.commit()
    db.refresh(r)
    return _rate_out(r)


@router.delete("/projects/{key}/finance/rates/{rate_id}", status_code=204)
def delete_rate(key: str, rate_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.FINANCE_MANAGE)
    r = db.get(MemberRate, rate_id)
    if not r or r.project_id != p.id:
        raise HTTPException(404, "Rate not found")
    db.delete(r)
    db.commit()


# ---------- expenses
def _expense_out(e: Expense, project: Project) -> ExpenseOut:
    return ExpenseOut(
        id=e.id, spent_on=e.spent_on, amount=float(e.amount), category=e.category, description=e.description,
        issue_key=f"{project.key}-{e.issue.number}" if e.issue else None,
        module=NamedRef(id=e.module.id, name=e.module.name) if e.module else None,
        created_by=UserBrief.model_validate(e.created_by, from_attributes=True) if e.created_by else None,
        created_at=e.created_at)


def _expense_refs(db: Session, project: Project, data: dict) -> dict:
    """Turns issue_key into issue_id and checks that the issue and module belong to the project."""
    if "issue_key" in data:
        k = data.pop("issue_key")
        data["issue_id"] = None
        if k:
            m = KEY.match(k.strip())
            issue = m and m.group(1).upper() == project.key and db.scalar(
                select(Issue).where(Issue.project_id == project.id, Issue.number == int(m.group(2))))
            if not issue:
                raise HTTPException(422, "Issue must be in this project")
            data["issue_id"] = issue.id
    if data.get("module_id"):
        mod = db.get(Module, data["module_id"])
        if not mod or mod.project_id != project.id:
            raise HTTPException(422, "Module must be in this project")
    return data


EXPENSE_LOAD = (selectinload(Expense.issue), selectinload(Expense.module), selectinload(Expense.created_by))


@router.get("/projects/{key}/finance/expenses", response_model=list[ExpenseOut])
def expenses(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _viewer(db, key, user)
    rows = db.scalars(select(Expense).options(*EXPENSE_LOAD).where(Expense.project_id == p.id)
                      .order_by(Expense.spent_on.desc(), Expense.created_at.desc()))
    return [_expense_out(e, p) for e in rows]


@router.post("/projects/{key}/finance/expenses", response_model=ExpenseOut, status_code=201)
def add_expense(key: str, body: ExpenseIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.FINANCE_MANAGE)
    e = Expense(project_id=p.id, created_by_id=user.id, **_expense_refs(db, p, body.model_dump()))
    db.add(e)
    db.commit()
    db.refresh(e)
    return _expense_out(e, p)


def _expense(db: Session, project: Project, expense_id: uuid.UUID) -> Expense:
    e = db.get(Expense, expense_id)
    if not e or e.project_id != project.id:
        raise HTTPException(404, "Expense not found")
    return e


@router.patch("/projects/{key}/finance/expenses/{expense_id}", response_model=ExpenseOut)
def patch_expense(key: str, expense_id: uuid.UUID, body: ExpensePatch, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.FINANCE_MANAGE)
    e = _expense(db, p, expense_id)
    data = _expense_refs(db, p, body.model_dump(exclude_unset=True))
    for k in ("spent_on", "amount", "category"):
        if k in data and data[k] is None:
            raise HTTPException(422, f"{k} cannot be empty")
    for k, v in data.items():
        setattr(e, k, v)
    db.commit()
    db.refresh(e)
    return _expense_out(e, p)


@router.delete("/projects/{key}/finance/expenses/{expense_id}", status_code=204)
def delete_expense(key: str, expense_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.FINANCE_MANAGE)
    db.delete(_expense(db, p, expense_id))
    db.commit()


# ---------- worklogs
def _worklog_out(w: Worklog, project: Project, rates: finance.Rates | None) -> WorklogOut:
    return WorklogOut(
        id=w.id, issue_key=f"{project.key}-{w.issue.number}", issue_title=w.issue.title,
        user=UserBrief.model_validate(w.user, from_attributes=True) if w.user else None,
        work_date=w.work_date, minutes=w.minutes, note=w.note, created_at=w.created_at,
        cost=finance.worklog_cost(rates, w) if rates else None)


def _rates(db: Session, project: Project, perms: set[str]) -> finance.Rates | None:
    return finance.Rates(db, project.id, finance.settings(db, project).default_rate) if sees_money(perms) else None


def _check_day(day: date):
    if day > finance.today():
        raise HTTPException(422, "Time cannot be logged in the future")


WORKLOG_LOAD = (selectinload(Worklog.user), selectinload(Worklog.issue))


@router.get("/projects/{key}/worklogs", response_model=list[WorklogOut])
def project_worklogs(key: str, start: date | None = None, end: date | None = None,
                     user_id: uuid.UUID | None = None, limit: int = Query(500, ge=1, le=5000),
                     db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, perms = project_for(db, key, user)
    q = select(Worklog).options(*WORKLOG_LOAD).where(Worklog.project_id == p.id)
    if start:
        q = q.where(Worklog.work_date >= start)
    if end:
        q = q.where(Worklog.work_date <= end)
    if user_id:
        q = q.where(Worklog.user_id == user_id)
    rows = db.scalars(q.order_by(Worklog.work_date.desc(), Worklog.created_at.desc()).limit(limit))
    rates = _rates(db, p, perms)
    return [_worklog_out(w, p, rates) for w in rows]


@router.get("/issues/{key}/worklogs", response_model=IssueWorklogs)
def issue_worklogs(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    issue, perms = _load(db, key, user)
    rows = db.scalars(select(Worklog).options(*WORKLOG_LOAD).where(Worklog.issue_id == issue.id)
                      .order_by(Worklog.work_date.desc(), Worklog.created_at.desc())).all()
    rates = _rates(db, issue.project, perms)
    return IssueWorklogs(total_minutes=sum(w.minutes for w in rows), estimate=issue.estimate,
                         currency=finance.settings(db, issue.project).currency if rates else None,
                         items=[_worklog_out(w, issue.project, rates) for w in rows])


@router.post("/issues/{key}/worklogs", response_model=WorklogOut, status_code=201)
def log_time(key: str, body: WorklogIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    issue, perms = _load(db, key, user, rbac.TIME_LOG)
    who = body.user_id or user.id
    if who != user.id:
        if rbac.FINANCE_MANAGE not in perms:
            raise HTTPException(403, f"Logging time for others requires permission: {rbac.FINANCE_MANAGE}")
        if not db.get(User, who):
            raise HTTPException(422, "Unknown user")
    day = body.work_date or finance.today()
    _check_day(day)
    w = Worklog(project_id=issue.project_id, issue_id=issue.id, user_id=who, work_date=day, minutes=body.minutes,
                note=body.note)
    db.add(w)
    db.commit()
    db.refresh(w)
    return _worklog_out(w, issue.project, _rates(db, issue.project, perms))


def _own_worklog(db: Session, worklog_id: uuid.UUID, user: User) -> tuple[Worklog, Project, set[str]]:
    """Your own entries need time.log; anyone's need finance.manage."""
    w = db.get(Worklog, worklog_id)
    project = db.get(Project, w.project_id) if w else None
    perms = rbac.project_permissions(db, project, user) if project else set()
    if not w or rbac.PROJECT_READ not in perms:
        raise HTTPException(404, "Worklog not found")
    mine = w.user_id == user.id and rbac.TIME_LOG in perms
    if not mine and rbac.FINANCE_MANAGE not in perms:
        raise HTTPException(403, "You can change only your own time")
    return w, project, perms


@router.patch("/worklogs/{worklog_id}", response_model=WorklogOut)
def patch_worklog(worklog_id: uuid.UUID, body: WorklogPatch, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    w, project, perms = _own_worklog(db, worklog_id, user)
    data = body.model_dump(exclude_unset=True)
    for k in ("minutes", "work_date", "note"):
        if k in data and data[k] is None:
            raise HTTPException(422, f"{k} cannot be empty")
    if "work_date" in data:
        _check_day(data["work_date"])
    for k, v in data.items():
        setattr(w, k, v)
    db.commit()
    db.refresh(w)
    return _worklog_out(w, project, _rates(db, project, perms))


@router.delete("/worklogs/{worklog_id}", status_code=204)
def delete_worklog(worklog_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    w, _, _ = _own_worklog(db, worklog_id, user)
    db.delete(w)
    db.commit()


@router.get("/my/worklogs", response_model=list[WorklogOut])
def my_worklogs(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    """Your own time across projects, for a timesheet; costs are left out here."""
    q = select(Worklog).options(selectinload(Worklog.user), selectinload(Worklog.issue).selectinload(Issue.project)) \
        .where(Worklog.user_id == user.id)
    if start:
        q = q.where(Worklog.work_date >= start)
    if end:
        q = q.where(Worklog.work_date <= end)
    rows = db.scalars(q.order_by(Worklog.work_date.desc(), Worklog.created_at.desc()).limit(1000))
    return [_worklog_out(w, w.issue.project, None) for w in rows]

