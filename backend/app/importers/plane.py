"""Plane (cloud or self-hosted) through its public REST API v1 with an API key (Profile settings -> API tokens).

Imported: states, labels, members, work items (issues) with priority, assignees, dates and parent, cycles,
modules and comments. Plane pages are not in the public API, so they are not imported.
"""
from datetime import date

from ..models import IssueType, Priority, StateCategory
from .base import PAGE_SIZE, Context, Remote, SourceError, footer, parse_date, parse_dt
from .convert import html_to_md

GROUPS = {"backlog": StateCategory.backlog, "unstarted": StateCategory.todo, "started": StateCategory.in_progress,
          "completed": StateCategory.done, "cancelled": StateCategory.cancelled}
MODULE_STATUS = {"backlog": "backlog", "planned": "planned", "in-progress": "in_progress", "in_progress": "in_progress",
                 "paused": "paused", "completed": "completed", "cancelled": "cancelled"}


def remote(src: dict) -> Remote:
    if not src.get("workspace"):
        raise SourceError("Plane workspace slug is required")
    return Remote(src["url"], token=src.get("token", ""), header="X-API-Key")


def _api(src: dict) -> str:
    return f"/api/v1/workspaces/{src['workspace']}"


def _all(r: Remote, path: str):
    """Plane pages with ?cursor=; old versions return a plain list."""
    cursor = None
    while True:
        data = r.get(path, {"per_page": PAGE_SIZE, **({"cursor": cursor} if cursor else {})})
        if isinstance(data, list):
            yield from data
            return
        yield from data.get("results", [])
        cursor = data.get("next_cursor")
        if not data.get("next_page_results") or not cursor:
            return


def list_projects(src: dict) -> list[dict]:
    r = remote(src)
    try:
        return [{"id": p["id"], "key": p.get("identifier") or "", "name": p.get("name", "")}
                for p in _all(r, f"{_api(src)}/projects/")]
    finally:
        r.close()


def _ids(rows) -> list[str]:
    out = []
    for x in rows or []:
        if isinstance(x, dict):
            x = x.get("issue") or x.get("id")
            x = x.get("id") if isinstance(x, dict) else x
        if x:
            out.append(str(x))
    return out


class PlaneImport:
    name = "Plane"

    def __init__(self, ctx: Context, src: dict, params: dict):
        self.ctx, self.src, self.params = ctx, src, params
        self.r = remote(src)
        self.base = f"{_api(src)}/projects/{params['remote']}"

    def run(self):
        ctx, r, base = self.ctx, self.r, self.base
        proj = r.get(base + "/")
        ident = proj.get("identifier") or "PLANE"
        ctx.say(f"Plane project {proj.get('name', '')} ({ident})")

        people: dict[str, tuple] = {}
        for m in _all(r, base + "/members/"):
            m = m.get("member") if isinstance(m.get("member"), dict) else m
            name = " ".join(x for x in (m.get("first_name"), m.get("last_name")) if x) or m.get("display_name")
            u = ctx.user(m.get("email"), m.get("display_name"), name or m.get("email"))
            people[str(m.get("id"))] = (u, None if u else name)

        def who(uid) -> tuple:
            return people.get(str(uid), (None, None)) if uid else (None, None)

        states = {}
        for s in sorted(_all(r, base + "/states/"), key=lambda s: s.get("sequence") or 0):
            states[s["id"]] = ctx.state(s["name"], GROUPS.get(s.get("group"), StateCategory.todo))
        labels = {lb["id"]: ctx.label(lb["name"], lb.get("color")) for lb in _all(r, base + "/labels/")}
        ctx.checkpoint()

        cycle_of: dict[str, object] = {}
        today = date.today()
        for c in _all(r, base + "/cycles/"):
            end = parse_date(c.get("end_date"))
            cyc = ctx.cycle(c["id"], c["name"], c.get("start_date"), c.get("end_date"),
                            closed=bool(end and end < today), goal=html_to_md(c.get("description") or ""))
            for iid in _ids(_all(r, f"{base}/cycles/{c['id']}/cycle-issues/")):
                cycle_of[iid] = cyc
        modules_of: dict[str, list] = {}
        for m in _all(r, base + "/modules/"):
            lead, _ = who(m.get("lead"))
            md = ctx.module(m["id"], m["name"], description=html_to_md(m.get("description_html") or "")
                            or (m.get("description") or ""),
                            status=MODULE_STATUS.get((m.get("status") or "").lower()),
                            start_date=parse_date(m.get("start_date")), target_date=parse_date(m.get("target_date")),
                            lead_id=lead.id if lead else None)
            for iid in _ids(_all(r, f"{base}/modules/{m['id']}/module-issues/")):
                modules_of.setdefault(iid, []).append(md)
        ctx.checkpoint()

        fallback = ctx.state("Todo", StateCategory.todo) if not states else next(iter(states.values()))
        parents, done = [], 0
        rows = sorted(_all(r, base + "/issues/"), key=lambda i: i.get("sequence_id") or 0)
        for it in rows:
            reporter, reporter_name = who(it.get("created_by"))
            ref = f"{ident}-{it.get('sequence_id')}"
            url = f"{r.base}/{self.src['workspace']}/projects/{self.params['remote']}/issues/{it['id']}"
            try:
                prio = Priority(it.get("priority") or "none")
            except ValueError:
                prio = Priority.none
            issue = ctx.issue(
                it["id"], title=it.get("name") or ref,
                description=html_to_md(it.get("description_html")) + footer("Plane", ref, url, reporter_name),
                state=states.get(it.get("state"), fallback), created_at=parse_dt(it.get("created_at")),
                type_=IssueType.task, priority=prio, reporter=reporter,
                assignees=[u for u, _ in (who(a) for a in it.get("assignees") or []) if u],
                labels=[labels[x] for x in it.get("labels") or [] if x in labels],
                sprint=cycle_of.get(str(it["id"])), modules=modules_of.get(str(it["id"]), []),
                start_date=it.get("start_date"), due_date=it.get("target_date"),
                completed_at=parse_dt(it.get("completed_at")))
            parents.append((issue, it.get("parent")))
            if self.params.get("include_comments", True):
                for c in _all(r, f"{base}/issues/{it['id']}/comments/"):
                    author, author_name = who(c.get("actor") or c.get("created_by"))
                    ctx.comment(issue, c["id"], html_to_md(c.get("comment_html") or ""), author, author_name,
                                parse_dt(c.get("created_at")))
            done += 1
            if done % 50 == 0:
                ctx.say(f"{done} issues")
                ctx.checkpoint()
        for issue, parent_id in parents:
            parent = ctx.linked(type(issue), "issue", parent_id) if parent_id else None
            issue.parent_id = parent.id if parent and parent.id != issue.id else None
        ctx.say(f"{done} issues imported")

    def close(self):
        self.r.close()
