"""Shared parts of the importers: HTTP access to the source, matching users, and the registry of imported objects
(import_links) that makes running the same import again update what is there instead of duplicating it."""
import logging
import uuid
from datetime import date, datetime

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import (
    CLOSED,
    Activity,
    Comment,
    ImportJob,
    ImportLink,
    Issue,
    IssueType,
    Label,
    Module,
    Priority,
    Project,
    ProjectMember,
    Role,
    Sprint,
    State,
    StateCategory,
    User,
    utcnow,
)

log = logging.getLogger("lodestone.import")

PAGE_SIZE = 100
MAX_LOG = 20_000


class SourceError(Exception):
    """The source answered with an error or something we cannot read; the message is shown to the admin."""


def http_client() -> httpx.Client:
    """Separate function so tests can swap in httpx.MockTransport."""
    return httpx.Client(timeout=30, follow_redirects=False)


class Remote:
    """JSON API of the source. Auth: basic (user + token/password) or a bearer/API-key header."""

    def __init__(self, base_url: str, username: str = "", token: str = "", header: str | None = None):
        if not base_url.startswith(("http://", "https://")):
            raise SourceError("URL must start with http:// or https://")
        self.base = base_url.rstrip("/")
        self.auth = (username, token) if username else None
        self.headers = {"Accept": "application/json"}
        if header and token:
            self.headers[header] = token
        elif token and not username:
            self.headers["Authorization"] = f"Bearer {token}"
        self.client = http_client()

    def get(self, path: str, params: dict | None = None, ok404: bool = False):
        url = path if path.startswith("http") else self.base + path
        try:
            r = self.client.get(url, params=params, auth=self.auth, headers=self.headers)
        except httpx.HTTPError as e:
            raise SourceError(f"{self.base}: {e}") from e
        if r.status_code == 404 and ok404:
            return None
        if r.status_code in (401, 403):
            raise SourceError(f"{r.status_code}: access denied, check the user name and token")
        if r.status_code >= 300:
            raise SourceError(f"{r.status_code} from {url.split('?')[0]}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError as e:
            raise SourceError(f"{url.split('?')[0]} did not return JSON (is the URL right?)") from e

    def close(self):
        self.client.close()


def parse_dt(v) -> datetime | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        # Jira: 2026-10-01T09:30:00.000+0500
        try:
            dt = datetime.strptime(str(v), "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def parse_date(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _norm(name: str) -> str:
    return "".join(name.lower().split())


class Context:
    """One import job writing into one project."""

    def __init__(self, db: Session, job: ImportJob, project: Project, source_id: str):
        self.db, self.job, self.project, self.source_id = db, job, project, source_id[:200]
        self.actor = db.get(User, job.created_by_id) if job.created_by_id else None
        self.stats: dict = {}
        self.unmatched: set[str] = set()
        self._users: dict[str, User | None] = {}
        self._states = {_norm(s.name): s for s in db.scalars(select(State).where(State.project_id == project.id))}
        self._labels = {x.name.lower(): x for x in db.scalars(select(Label).where(Label.project_id == project.id))}
        self._member_role = db.scalar(select(Role).where(Role.key == "member", Role.scope == "project"))

    # ---------- progress
    def count(self, what: str, n: int = 1):
        self.stats[what] = self.stats.get(what, 0) + n

    def say(self, msg: str):
        log.info("import %s: %s", self.job.id, msg)
        line = f"{utcnow():%H:%M:%S} {msg}\n"
        self.job.log = ((self.job.log or "") + line)[-MAX_LOG:]

    def checkpoint(self):
        """Commits what is done so far: progress shows in the UI, and a failure later keeps it."""
        self.job.stats = {**self.stats, "unmatched_users": sorted(self.unmatched)}
        self.job.updated_at = utcnow()
        self.db.commit()

    # ---------- registry of imported objects
    def link(self, kind: str, external_id) -> str | None:
        row = self.db.get(ImportLink, (self.source_id, kind, str(external_id)[:200]))
        return row.local_id if row and row.project_id == self.project.id else None

    def remember(self, kind: str, external_id, local_id):
        values = {"source": self.source_id, "kind": kind, "external_id": str(external_id)[:200],
                  "project_id": self.project.id, "local_id": str(local_id)}
        self.db.execute(pg_insert(ImportLink).values(**values).on_conflict_do_update(
            index_elements=["source", "kind", "external_id"],
            set_={"project_id": values["project_id"], "local_id": values["local_id"]}))

    def linked(self, model, kind: str, external_id):
        local = self.link(kind, external_id)
        if not local:
            return None
        obj = self.db.get(model, uuid.UUID(local))
        return obj if obj is not None and getattr(obj, "project_id", self.project.id) == self.project.id else None

    # ---------- users
    def user(self, email: str | None = None, username: str | None = None, name: str | None = None) -> User | None:
        """Finds a Lodestone user by e-mail, then by login, and makes them a project member.
        Unknown people are listed in the job result; their work is kept with their name in the text."""
        key = (email or username or name or "").lower()
        if not key:
            return None
        if key in self._users:
            return self._users[key]
        u = None
        if email:
            u = self.db.scalar(select(User).where(func.lower(User.email) == email.lower(), User.is_active.is_(True))
                               .order_by(User.created_at).limit(1))
        if not u and username:
            u = self.db.scalar(select(User).where(User.username == username.lower(), User.is_active.is_(True)))
        if u:
            if not self.db.get(ProjectMember, (self.project.id, u.id)) and self._member_role:
                self.db.add(ProjectMember(project_id=self.project.id, user_id=u.id, role_id=self._member_role.id))
                self.db.flush()
                self.count("members")
        else:
            self.unmatched.add(name or username or email)
        self._users[key] = u
        return u

    # ---------- project objects
    def state(self, name: str, category: StateCategory) -> State:
        k = _norm(name)
        st = self._states.get(k)
        if not st:
            pos = (self.db.scalar(select(func.max(State.position)).where(State.project_id == self.project.id)) or 0)
            st = State(project_id=self.project.id, name=name[:60], category=category, position=pos + 1)
            self.db.add(st)
            self.db.flush()
            self._states[k] = st
            self.count("states")
        return st

    def label(self, name: str, color: str | None = None) -> Label:
        name = name.strip()[:60]
        lb = self._labels.get(name.lower())
        if not lb:
            lb = Label(project_id=self.project.id, name=name)
            if color and len(color) == 7 and color.startswith("#"):
                lb.color = color
            self.db.add(lb)
            self.db.flush()
            self._labels[name.lower()] = lb
            self.count("labels")
        return lb

    def cycle(self, external_id, name: str, start=None, end=None, closed: bool = False, goal: str = "") -> Sprint:
        sp = self.linked(Sprint, "cycle", external_id)
        if not sp:
            sp = Sprint(project_id=self.project.id)
            self.db.add(sp)
            self.count("cycles")
        sp.name, sp.goal, sp.start_date, sp.end_date = name[:120], goal or "", parse_date(start), parse_date(end)
        if sp.start_date and sp.end_date and sp.end_date < sp.start_date:
            sp.end_date = sp.start_date
        if closed and not sp.closed:
            sp.closed, sp.closed_at = True, parse_dt(end) or utcnow()
        self.db.flush()
        self.remember("cycle", external_id, sp.id)
        return sp

    def module(self, external_id, name: str, **fields) -> Module:
        md = self.linked(Module, "module", external_id)
        if not md:
            name = name.strip()[:120]
            md = self.db.scalar(select(Module).where(Module.project_id == self.project.id,
                                                     func.lower(Module.name) == name.lower()))
        if not md:
            md = Module(project_id=self.project.id, name=name.strip()[:120], status="planned")
            self.db.add(md)
            self.count("modules")
        for k, v in fields.items():
            if v is not None:
                setattr(md, k, v)
        self.db.flush()
        self.remember("module", external_id, md.id)
        return md

    def issue(self, external_id, *, title: str, description: str, state: State, created_at: datetime | None,
              type_: IssueType = IssueType.task, priority: Priority = Priority.none, reporter: User | None = None,
              assignees: list[User] = (), labels: list[Label] = (), sprint: Sprint | None = None,
              modules: list[Module] = (), start_date=None, due_date=None, estimate: float | None = None,
              completed_at: datetime | None = None) -> Issue:
        issue = self.linked(Issue, "issue", external_id)
        created_at = created_at or utcnow()
        new = issue is None
        if new:
            number = self.db.execute(update(Project).where(Project.id == self.project.id)
                                     .values(issue_seq=Project.issue_seq + 1).returning(Project.issue_seq)).scalar_one()
            issue = Issue(project_id=self.project.id, number=number, created_at=created_at, position=number * 1024.0)
            self.db.add(issue)
        old_state = issue.state_id
        issue.title, issue.description = (title.strip() or "(untitled)")[:300], description
        issue.type, issue.priority, issue.state_id = type_, priority, state.id
        issue.reporter_id = reporter.id if reporter else None
        issue.start_date, issue.due_date, issue.estimate = parse_date(start_date), parse_date(due_date), estimate
        if sprint is not None or new:
            issue.sprint_id = sprint.id if sprint else None
        issue.assignees, issue.labels = list({u.id: u for u in assignees}.values()), list(labels)
        if modules or new:
            issue.modules = list({m.id: m for m in modules}.values())
        if state.category in CLOSED:
            issue.completed_at = completed_at or issue.completed_at or created_at
        else:
            issue.completed_at = None
        if state.category == StateCategory.in_progress and not issue.started_at:
            issue.started_at = created_at if new else utcnow()
        self.db.flush()
        actor = self.actor.id if self.actor else None
        if new:
            self.db.add(Activity(issue_id=issue.id, actor_id=actor, field="created", new_value=issue.title[:500],
                                 created_at=created_at))
            if state.category in CLOSED:
                # one state change at the completion date, so flow and lead-time charts see when it was finished
                opened = next((s for s in self._states.values() if s.category == StateCategory.todo), None)
                if opened:
                    self.db.add(Activity(issue_id=issue.id, actor_id=actor, field="state", old_value=opened.name,
                                         new_value=state.name, old_ref=str(opened.id), new_ref=str(state.id),
                                         created_at=issue.completed_at))
            self.count("issues")
        else:
            if old_state != state.id:
                self.db.add(Activity(issue_id=issue.id, actor_id=actor, field="state", new_value=state.name,
                                     old_ref=str(old_state), new_ref=str(state.id)))
            self.count("issues_updated")
        self.remember("issue", external_id, issue.id)
        return issue

    def comment(self, issue: Issue, external_id, body: str, author: User | None, author_name: str,
                created_at: datetime | None):
        if not author and author_name:
            body = f"**{author_name}:**\n\n{body}"
        local = self.link("comment", external_id)
        c = self.db.get(Comment, uuid.UUID(local)) if local else None
        if c is None:
            c = Comment(issue_id=issue.id, created_at=created_at or utcnow())
            self.db.add(c)
            self.count("comments")
        c.body, c.author_id = body or "(empty)", author.id if author else None
        self.db.flush()
        self.remember("comment", external_id, c.id)


def footer(source: str, ref: str, url: str, reporter_name: str | None) -> str:
    who = f" · {reporter_name}" if reporter_name else ""
    return f"\n\n---\n*{source}: [{ref}]({url}){who}*"
