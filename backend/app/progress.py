"""Progress of a set of issues: totals by status category, burndown series, cumulative flow, lead and cycle time.

Computed on request from issues and their state-change history (activities), so there is nothing to keep in sync.
"""
import statistics
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity, Issue, Priority, State, StateCategory, User, issue_assignees

CATEGORIES = [c.value for c in StateCategory]
MAX_DAYS = 366


def _day(dt: datetime | None) -> date | None:
    return dt.astimezone(timezone.utc).date() if dt else None


def issue_rows(db: Session, where) -> list:
    return db.execute(select(Issue.id, Issue.created_at, Issue.started_at, Issue.completed_at, Issue.estimate,
                             Issue.due_date, State.category)
                      .join(State, State.id == Issue.state_id).where(*where)).all()


def totals(rows) -> dict:
    """Counts and estimate sums by status category, plus percent done (cancelled issues leave the scope)."""
    by_cat = {c: 0 for c in CATEGORIES}
    points = {c: 0.0 for c in CATEGORIES}
    for r in rows:
        by_cat[r.category.value] += 1
        points[r.category.value] += r.estimate or 0
    scope = len(rows) - by_cat["cancelled"]
    scope_points = sum(points.values()) - points["cancelled"]
    return {
        "total": len(rows), "by_category": by_cat, "points_by_category": points,
        "scope": scope, "done": by_cat["done"],
        "percent": round(100 * by_cat["done"] / scope) if scope else 0,
        "points_scope": scope_points, "points_done": points["done"],
        "points_percent": round(100 * points["done"] / scope_points) if scope_points else 0,
    }


def burndown(rows, start: date, end: date, today: date | None = None) -> list[dict]:
    """Per day: scope (created and not cancelled by then) and done, by count and by estimate.
    Days after today carry None so a chart stops at today. Membership is the current one."""
    today = today or datetime.now(timezone.utc).date()
    end = min(end, start + timedelta(days=MAX_DAYS))
    out = []
    d = start
    while d <= end:
        if d > today:
            out.append({"date": d.isoformat(), "scope": None, "done": None, "points_scope": None, "points_done": None})
        else:
            scope = done = 0
            p_scope = p_done = 0.0
            for r in rows:
                created = _day(r.created_at)
                closed = _day(r.completed_at)
                if created and created > d:
                    continue  # did not exist yet
                if r.category == StateCategory.cancelled and closed and closed <= d:
                    continue
                scope += 1
                p_scope += r.estimate or 0
                if r.category == StateCategory.done and closed and closed <= d:
                    done += 1
                    p_done += r.estimate or 0
            out.append({"date": d.isoformat(), "scope": scope, "done": done,
                        "points_scope": p_scope, "points_done": p_done})
        d += timedelta(days=1)
    return out


def default_range(start: date | None, end: date | None, rows) -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    first = min((_day(r.created_at) for r in rows), default=today)
    s = start or first
    e = end or max(today, s)
    if e < s:
        e = s
    return s, e


def cumulative_flow(db: Session, where, start: date, end: date) -> list[dict]:
    """Per day, how many issues sat in each status category at the end of that day."""
    issues = db.execute(select(Issue.id, Issue.created_at, State.category)
                        .join(State, State.id == Issue.state_id).where(*where)).all()
    if not issues:
        return []
    ids = [i.id for i in issues]
    cat_of = {str(sid): cat.value for sid, cat in db.execute(select(State.id, State.category)).all()}
    changes: dict[uuid.UUID, list[tuple[datetime, str]]] = defaultdict(list)
    first_old: dict[uuid.UUID, str] = {}
    for issue_id, at, old_ref, new_ref in db.execute(
            select(Activity.issue_id, Activity.created_at, Activity.old_ref, Activity.new_ref)
            .where(Activity.field == "state", Activity.issue_id.in_(ids)).order_by(Activity.created_at, Activity.id)):
        if issue_id not in first_old and old_ref in cat_of:
            first_old[issue_id] = cat_of[old_ref]
        if new_ref in cat_of:
            changes[issue_id].append((at, cat_of[new_ref]))
    out = []
    d = start
    end = min(end, start + timedelta(days=MAX_DAYS))
    while d <= end:
        cutoff = datetime.combine(d + timedelta(days=1), time.min, tzinfo=timezone.utc)
        counts = {c: 0 for c in CATEGORIES}
        for i in issues:
            if i.created_at >= cutoff:
                continue
            cat = first_old.get(i.id, i.category.value) if changes.get(i.id) else i.category.value
            for at, c in changes.get(i.id, []):
                if at >= cutoff:
                    break
                cat = c
            counts[cat] += 1
        out.append({"date": d.isoformat(), **counts})
        d += timedelta(days=1)
    return out


def _stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "median": None, "p85": None}
    values = sorted(values)
    p85 = values[min(len(values) - 1, int(round(0.85 * (len(values) - 1))))]
    return {"count": len(values), "median": round(statistics.median(values), 1), "p85": round(p85, 1)}


def project_report(db: Session, project_id: uuid.UUID, weeks: int) -> dict:
    today = datetime.now(timezone.utc).date()
    week0 = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)  # Monday, `weeks` weeks ago
    where = [Issue.project_id == project_id]
    rows = issue_rows(db, where)
    t = totals(rows)
    open_ids = {r.id for r in rows if r.category.value not in ("done", "cancelled")}
    t["overdue"] = sum(1 for r in rows if r.id in open_ids and r.due_date and r.due_date < today)

    weekly = []
    for w in range(weeks):
        ws = week0 + timedelta(weeks=w)
        we = ws + timedelta(days=7)
        weekly.append({
            "week": ws.isoformat(),
            "created": sum(1 for r in rows if ws <= _day(r.created_at) < we),
            "completed": sum(1 for r in rows if r.category == StateCategory.done and r.completed_at
                             and ws <= _day(r.completed_at) < we),
        })

    finished = [r for r in rows if r.category == StateCategory.done and r.completed_at
                and _day(r.completed_at) >= week0]
    lead = [(r.completed_at - r.created_at).total_seconds() / 86400 for r in finished]
    cycle = [(r.completed_at - r.started_at).total_seconds() / 86400 for r in finished if r.started_at]

    # people: open work by category and what they finished in the period
    people: dict[uuid.UUID, dict] = {}
    cat_by_id = {r.id: r for r in rows}
    for issue_id, uid, name in db.execute(
            select(issue_assignees.c.issue_id, User.id, User.display_name)
            .join(User, User.id == issue_assignees.c.user_id)
            .join(Issue, Issue.id == issue_assignees.c.issue_id).where(*where)):
        r = cat_by_id.get(issue_id)
        if not r:
            continue
        p = people.setdefault(uid, {"user_id": str(uid), "name": name, "todo": 0, "in_progress": 0, "done": 0})
        if r.category in (StateCategory.backlog, StateCategory.todo):
            p["todo"] += 1
        elif r.category == StateCategory.in_progress:
            p["in_progress"] += 1
        elif r.category == StateCategory.done and r.completed_at and _day(r.completed_at) >= week0:
            p["done"] += 1
    assigned_open = {i for i, in db.execute(select(issue_assignees.c.issue_id)
                                           .where(issue_assignees.c.issue_id.in_(open_ids)))} if open_ids else set()
    t["unassigned"] = len(open_ids - assigned_open)

    prio = {p.value: 0 for p in Priority}
    for issue_id, pr in db.execute(select(Issue.id, Issue.priority).where(*where)):
        if issue_id in open_ids:
            prio[pr.value] += 1

    return {
        "since": week0.isoformat(), "totals": t, "weekly": weekly,
        "lead_time": _stats(lead), "cycle_time": _stats(cycle),
        "people": sorted(people.values(), key=lambda p: -(p["todo"] + p["in_progress"] + p["done"]))[:20],
        "priority": prio,
        "flow": cumulative_flow(db, where, week0, today),
    }



def grouped(db: Session, key_col, where, join=None) -> dict:
    """{group id: totals()} for many cycles or modules in one query."""
    stmt = select(key_col.label("gid"), Issue.id, Issue.created_at, Issue.started_at, Issue.completed_at,
                  Issue.estimate, Issue.due_date, State.category).join(State, State.id == Issue.state_id)
    if join is not None:
        stmt = stmt.join(*join)
    by: dict = defaultdict(list)
    for r in db.execute(stmt.where(*where)).all():
        by[r.gid].append(r)
    return {gid: totals(rs) for gid, rs in by.items()}


def people(db: Session, rows) -> list[dict]:
    """Assignees of these issues: how many each has and how many are done."""
    if not rows:
        return []
    cat = {r.id: r.category for r in rows}
    out: dict[uuid.UUID, dict] = {}
    for issue_id, uid, name in db.execute(
            select(issue_assignees.c.issue_id, User.id, User.display_name)
            .join(User, User.id == issue_assignees.c.user_id).where(issue_assignees.c.issue_id.in_(list(cat)))):
        p = out.setdefault(uid, {"user_id": str(uid), "name": name, "total": 0, "done": 0})
        if cat[issue_id] != StateCategory.cancelled:
            p["total"] += 1
            p["done"] += cat[issue_id] == StateCategory.done
    return sorted(out.values(), key=lambda p: (-p["total"], p["name"]))
