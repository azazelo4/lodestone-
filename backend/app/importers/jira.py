"""Jira Cloud (REST API v3, ADF descriptions) and Jira Server / Data Center (REST API v2, wiki markup).

Imported: issues with type, status, priority, labels, assignee, reporter, dates, story points, parent (sub-tasks,
epics), sprints as cycles, components as modules, and comments. Not imported: attachments, worklogs, history.
"""
import re

from ..models import IssueType, Priority, StateCategory
from .base import PAGE_SIZE, Context, Remote, SourceError, footer, parse_dt
from .convert import adf_to_md, wiki_to_md

TYPES = {"epic": IssueType.epic, "bug": IssueType.bug, "story": IssueType.story, "user story": IssueType.story}
PRIORITIES = {"highest": Priority.urgent, "blocker": Priority.urgent, "critical": Priority.high,
              "high": Priority.high, "major": Priority.medium, "medium": Priority.medium, "low": Priority.low,
              "minor": Priority.low, "lowest": Priority.low, "trivial": Priority.low}
CANCELLED = {"cancelled", "canceled", "rejected", "declined", "won't do", "won't fix", "closed without fix"}


def remote(src: dict) -> Remote:
    """Cloud: e-mail + API token. Server/DC: login + password, or a personal access token alone."""
    return Remote(src["url"], src.get("username", ""), src.get("token", ""))


def list_projects(src: dict) -> list[dict]:
    r = remote(src)
    try:
        rows = r.get("/rest/api/2/project")
    finally:
        r.close()
    if not isinstance(rows, list):
        raise SourceError("Unexpected answer from /rest/api/2/project")
    return [{"id": str(p["id"]), "key": p["key"], "name": p.get("name", p["key"])} for p in rows]


def category(status: dict) -> StateCategory:
    name = (status.get("name") or "").strip().lower()
    cat = (status.get("statusCategory") or {}).get("key", "")
    if name in CANCELLED:
        return StateCategory.cancelled
    if cat == "done":
        return StateCategory.done
    if cat == "indeterminate":
        return StateCategory.in_progress
    return StateCategory.backlog if name == "backlog" else StateCategory.todo


SPRINT_STR = re.compile(r"\[(.*)\]$")


def parse_sprint(v) -> dict | None:
    """Cloud returns objects; Server returns strings like "...Sprint@1f[id=3,state=CLOSED,name=S 1,startDate=...]"."""
    if isinstance(v, dict):
        return v
    if not isinstance(v, str):
        return None
    m = SPRINT_STR.search(v)
    if not m:
        return None
    out = {}
    for part in re.split(r",(?=\w+=)", m.group(1)):
        k, _, val = part.partition("=")
        out[k] = None if val == "<null>" else val
    return out if out.get("id") else None


class JiraImport:
    name = "Jira"

    def __init__(self, ctx: Context, src: dict, params: dict):
        self.ctx, self.src, self.params = ctx, src, params
        self.r = remote(src)
        self.key = params["remote"]
        self.cloud = False
        self.f_sprint = self.f_points = self.f_epic = None

    def _fields(self):
        info = self.r.get("/rest/api/2/serverInfo")
        self.cloud = (info or {}).get("deploymentType") == "Cloud"
        for f in self.r.get("/rest/api/2/field") or []:
            custom = (f.get("schema") or {}).get("custom", "")
            name = (f.get("name") or "").lower()
            if custom.endswith(":gh-sprint"):
                self.f_sprint = f["id"]
            elif custom.endswith(":gh-epic-link"):
                self.f_epic = f["id"]
            elif custom.endswith("jsw-story-points") or name in ("story points", "story point estimate"):
                self.f_points = self.f_points or f["id"]

    def text(self, v) -> str:
        return adf_to_md(v) if self.cloud else wiki_to_md(v)

    def issues(self):
        fields = ["summary", "description", "issuetype", "status", "priority", "labels", "assignee", "reporter",
                  "created", "resolutiondate", "duedate", "parent", "components"]
        fields += [f for f in (self.f_sprint, self.f_points, self.f_epic) if f]
        jql = f'project = "{self.key}" ORDER BY created ASC'
        base = {"jql": jql, "fields": ",".join(fields), "maxResults": PAGE_SIZE}
        if self.cloud:
            token = None
            while True:
                data = self.r.get("/rest/api/3/search/jql", {**base, **({"nextPageToken": token} if token else {})})
                yield from data.get("issues", [])
                token = data.get("nextPageToken")
                if data.get("isLast", True) or not token:
                    return
        start = 0
        while True:
            data = self.r.get("/rest/api/2/search", {**base, "startAt": start})
            page = data.get("issues", [])
            yield from page
            start += len(page)
            if not page or start >= data.get("total", 0):
                return

    def comments(self, issue_id: str):
        start, v = 0, 3 if self.cloud else 2
        while True:
            data = self.r.get(f"/rest/api/{v}/issue/{issue_id}/comment", {"startAt": start, "maxResults": PAGE_SIZE})
            page = data.get("comments", [])
            yield from page
            start += len(page)
            if not page or start >= data.get("total", 0):
                return

    def person(self, u: dict | None):
        if not u:
            return None, None
        name = u.get("displayName") or u.get("name")
        user = self.ctx.user(u.get("emailAddress"), u.get("name"), name)
        return user, (None if user else name)

    def _cycle(self, values):
        sprints = [s for s in (parse_sprint(v) for v in (values or [])) if s]
        if not sprints:
            return None
        pick = next((s for s in sprints if str(s.get("state", "")).lower() == "active"), sprints[-1])
        cyc = None
        for s in sprints:
            c = self.ctx.cycle(f"{s['id']}", s.get("name") or f"Sprint {s['id']}", s.get("startDate"),
                               s.get("endDate"), str(s.get("state", "")).lower() == "closed", s.get("goal") or "")
            if s is pick:
                cyc = c
        return cyc

    def run(self):
        ctx = self.ctx
        self._fields()
        ctx.say(f"Jira {'Cloud' if self.cloud else 'Server/Data Center'}, project {self.key}")
        parents: list[tuple[object, str | None, str | None]] = []
        by_key: dict[str, str] = {}
        done = 0
        for it in self.issues():
            f = it.get("fields", {})
            reporter, reporter_name = self.person(f.get("reporter"))
            assignee, _ = self.person(f.get("assignee"))
            status = f.get("status") or {"name": "To Do"}
            itype = (f.get("issuetype") or {}).get("name", "").lower()
            prio = PRIORITIES.get(((f.get("priority") or {}).get("name") or "").lower(), Priority.none)
            points = f.get(self.f_points) if self.f_points else None
            mods = [ctx.module(f"component:{c['id']}", c["name"]) for c in f.get("components") or [] if c.get("name")]
            url = f"{self.r.base}/browse/{it['key']}"
            issue = ctx.issue(
                it["id"], title=f.get("summary") or it["key"],
                description=self.text(f.get("description")) + footer("Jira", it["key"], url, reporter_name),
                state=ctx.state(status.get("name") or "To Do", category(status)),
                created_at=parse_dt(f.get("created")), type_=TYPES.get(itype, IssueType.task), priority=prio,
                reporter=reporter, assignees=[assignee] if assignee else [],
                labels=[ctx.label(x) for x in f.get("labels") or []],
                sprint=self._cycle(f.get(self.f_sprint)) if self.f_sprint else None, modules=mods,
                due_date=f.get("duedate"), estimate=float(points) if isinstance(points, (int, float)) else None,
                completed_at=parse_dt(f.get("resolutiondate")))
            by_key[it["key"]] = it["id"]
            parents.append((issue, (f.get("parent") or {}).get("id"), f.get(self.f_epic) if self.f_epic else None))
            if self.params.get("include_comments", True):
                for c in self.comments(it["id"]):
                    author, author_name = self.person(c.get("author"))
                    ctx.comment(issue, f"{it['id']}/{c['id']}", self.text(c.get("body")), author, author_name,
                                parse_dt(c.get("created")))
            done += 1
            if done % 50 == 0:
                ctx.say(f"{done} issues")
                ctx.checkpoint()
        for issue, parent_id, epic_key in parents:
            parent_id = parent_id or by_key.get(epic_key or "")
            parent = ctx.linked(type(issue), "issue", parent_id) if parent_id else None
            issue.parent_id = parent.id if parent and parent.id != issue.id else None
        ctx.say(f"{done} issues imported")

    def close(self):
        self.r.close()
