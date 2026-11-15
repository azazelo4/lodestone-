"""Project money: what people's time cost and how spending compares to the budget.

Cost of a worklog = hours x rate. The rate is the person's latest project rate that starts on or before the work
date; work logged before their first rate uses that first rate (so setting a rate later still prices old time);
people with no rate get the project's default rate. The analytics.worklogs view applies the same rule for BI tools.
Everything is computed on request: a project has thousands of worklogs, not millions.
"""
import bisect
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Expense, Issue, MemberRate, Module, Project, ProjectFinance, Sprint, User, Worklog, issue_modules

CENT = Decimal("0.01")
MAX_MONTHS = 60


def today() -> date:
    return datetime.now(timezone.utc).date()


def money(v: Decimal | None) -> float | None:
    return None if v is None else float(Decimal(v).quantize(CENT))


def settings(db: Session, project: Project) -> ProjectFinance:
    """The project's finance row, or an unsaved one with defaults."""
    return db.get(ProjectFinance, project.id) or ProjectFinance(project_id=project.id, currency="USD")


class Rates:
    """Hourly rate lookup for one project."""

    def __init__(self, db: Session, project_id: uuid.UUID, default: Decimal | None):
        self.default = default
        self.by_user: dict[uuid.UUID, tuple[list[date], list[Decimal]]] = {}
        rows = db.execute(select(MemberRate.user_id, MemberRate.valid_from, MemberRate.rate)
                          .where(MemberRate.project_id == project_id).order_by(MemberRate.valid_from))
        for uid, since, rate in rows:
            days, rates = self.by_user.setdefault(uid, ([], []))
            days.append(since)
            rates.append(rate)

    def rate(self, user_id: uuid.UUID | None, day: date) -> Decimal | None:
        found = self.by_user.get(user_id) if user_id else None
        if not found:
            return self.default
        days, rates = found
        i = bisect.bisect_right(days, day) - 1
        return rates[max(i, 0)]

    def current(self, user_id: uuid.UUID) -> Decimal | None:
        return self.rate(user_id, today())


@dataclass
class Priced:
    id: uuid.UUID
    issue_id: uuid.UUID
    user_id: uuid.UUID | None
    work_date: date
    minutes: int
    rate: Decimal | None

    @property
    def hours(self) -> Decimal:
        return Decimal(self.minutes) / 60

    @property
    def cost(self) -> Decimal:
        return self.hours * self.rate if self.rate is not None else Decimal(0)


def priced_worklogs(db: Session, project_id: uuid.UUID, rates: Rates) -> list[Priced]:
    rows = db.execute(select(Worklog.id, Worklog.issue_id, Worklog.user_id, Worklog.work_date, Worklog.minutes)
                      .where(Worklog.project_id == project_id))
    return [Priced(*r, rates.rate(r.user_id, r.work_date)) for r in rows]


def worklog_cost(rates: Rates, w: Worklog) -> float:
    rate = rates.rate(w.user_id, w.work_date)
    return money(Decimal(w.minutes) / 60 * rate) if rate is not None else 0.0


def _month(d: date) -> date:
    return d.replace(day=1)


def _next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def _plan_by(fin: ProjectFinance, day: date) -> Decimal | None:
    """Budget spread evenly over the project's dates, cumulative up to and including `day`."""
    if fin.budget is None or not fin.start_date or not fin.end_date:
        return None
    total = (fin.end_date - fin.start_date).days + 1
    done = min(max((day - fin.start_date).days + 1, 0), total)
    return fin.budget * done / total


def _bucket(name: str, hours: Decimal, cost: Decimal, **extra) -> dict:
    return {"name": name, "hours": round(float(hours), 2), "cost": money(cost), **extra}


def summary(db: Session, project: Project) -> dict:
    fin = settings(db, project)
    rates = Rates(db, project.id, fin.default_rate)
    logs = priced_worklogs(db, project.id, rates)
    expenses = db.execute(select(Expense.spent_on, Expense.amount, Expense.category)
                          .where(Expense.project_id == project.id)).all()
    now = today()

    hours = sum((w.hours for w in logs), Decimal(0))
    labor = sum((w.cost for w in logs), Decimal(0))
    spent_other = sum((e.amount for e in expenses), Decimal(0))
    spent = labor + spent_other
    unrated = sum((w.hours for w in logs if w.rate is None), Decimal(0))

    forecast = None
    if fin.start_date and fin.end_date and spent:
        if now >= fin.end_date:
            forecast = spent
        elif now >= fin.start_date:
            elapsed = (now - fin.start_date).days + 1
            forecast = spent / elapsed * ((fin.end_date - fin.start_date).days + 1)

    totals = {
        "budget": money(fin.budget), "budget_hours": money(fin.budget_hours),
        "hours": round(float(hours), 2), "labor": money(labor), "expenses": money(spent_other), "spent": money(spent),
        "remaining": money(fin.budget - spent) if fin.budget is not None else None,
        "percent": round(float(spent / fin.budget * 100), 1) if fin.budget else None,
        "hours_percent": round(float(hours / fin.budget_hours * 100), 1) if fin.budget_hours else None,
        "unrated_hours": round(float(unrated), 2), "forecast": money(forecast),
    }

    # months: from the first of (start date, first record) to the last of (end date, today)
    days = [w.work_date for w in logs] + [e.spent_on for e in expenses] + [d for d in (fin.start_date,) if d]
    months = []
    if days:
        first = _month(min(days))
        last = _month(max([now] + [d for d in (fin.end_date,) if d] + days))
        per = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0)])  # hours, labor, expenses
        for w in logs:
            m = per[_month(w.work_date)]
            m[0] += w.hours
            m[1] += w.cost
        for e in expenses:
            per[_month(e.spent_on)][2] += e.amount
        m = max(first, last.replace(year=last.year - MAX_MONTHS // 12))  # older months only count in the total
        running = sum((v[1] + v[2] for k, v in per.items() if k < m), Decimal(0))
        while m <= last:
            h, lab, exp = per.get(m, (Decimal(0), Decimal(0), Decimal(0)))
            running += lab + exp
            end_of_month = _next_month(m).toordinal() - 1
            plan = _plan_by(fin, date.fromordinal(end_of_month))
            months.append({"month": m, "hours": round(float(h), 2), "labor": money(lab), "expenses": money(exp),
                           "actual": money(running) if m <= now else None, "plan": money(plan)})
            m = _next_month(m)

    by_user: dict = defaultdict(lambda: [Decimal(0), Decimal(0)])
    by_issue: dict = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for w in logs:
        by_user[w.user_id][0] += w.hours
        by_user[w.user_id][1] += w.cost
        by_issue[w.issue_id][0] += w.hours
        by_issue[w.issue_id][1] += w.cost

    names = dict(db.execute(select(User.id, User.display_name).where(User.id.in_([u for u in by_user if u]))).all())
    people = sorted((_bucket(names.get(uid, "—"), h, c, id=uid, rate=money(rates.current(uid)) if uid else None)
                     for uid, (h, c) in by_user.items()), key=lambda b: (-b["cost"], -b["hours"]))

    issues = db.execute(select(Issue.id, Issue.number, Issue.title, Issue.estimate, Issue.sprint_id)
                        .where(Issue.id.in_(list(by_issue)))).all() if by_issue else []
    top = sorted(issues, key=lambda i: (-by_issue[i.id][1], -by_issue[i.id][0]))[:10]
    top_issues = [_bucket(i.title, *by_issue[i.id], id=i.id, key=f"{project.key}-{i.number}", estimate=i.estimate)
                  for i in top]

    by_cycle: dict = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for i in issues:
        if i.sprint_id:
            by_cycle[i.sprint_id][0] += by_issue[i.id][0]
            by_cycle[i.sprint_id][1] += by_issue[i.id][1]
    cycle_names = dict(db.execute(select(Sprint.id, Sprint.name).where(Sprint.project_id == project.id)).all())
    cycles = [_bucket(cycle_names[cid], h, c, id=cid) for cid, (h, c) in by_cycle.items() if cid in cycle_names]

    # an issue in two modules counts in both: modules overlap, so these do not add up to the total
    by_module: dict = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for iid, mid in db.execute(select(issue_modules.c.issue_id, issue_modules.c.module_id)
                               .where(issue_modules.c.issue_id.in_(list(by_issue)))).all() if by_issue else []:
        by_module[mid][0] += by_issue[iid][0]
        by_module[mid][1] += by_issue[iid][1]
    module_names = dict(db.execute(select(Module.id, Module.name).where(Module.project_id == project.id)).all())
    modules = [_bucket(module_names[mid], h, c, id=mid) for mid, (h, c) in by_module.items() if mid in module_names]

    by_cat: dict = defaultdict(Decimal)
    for e in expenses:
        by_cat[e.category] += e.amount
    categories = [_bucket(cat, Decimal(0), amt) for cat, amt in by_cat.items()]

    def biggest(rows):
        return sorted(rows, key=lambda b: (-b["cost"], -b["hours"], b["name"]))

    return {
        "settings": {"currency": fin.currency, "budget": money(fin.budget), "budget_hours": money(fin.budget_hours),
                     "default_rate": money(fin.default_rate), "start_date": fin.start_date, "end_date": fin.end_date},
        "totals": totals, "months": months, "people": people, "issues": top_issues,
        "cycles": biggest(cycles), "modules": biggest(modules), "categories": biggest(categories),
    }
