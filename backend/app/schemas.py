import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import IssueType, Priority, StateCategory


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- users / auth
class UserOut(ORM):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    is_admin: bool
    is_active: bool
    source: str


class UserBrief(ORM):
    id: uuid.UUID
    username: str
    display_name: str


class MeOut(UserOut):
    permissions: list[str] = []


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=512)
    provider: str | None = None  # slug of an LDAP provider when there are several


class ProviderBrief(BaseModel):
    slug: str
    type: str
    name: str


class AuthConfig(BaseModel):
    setup_required: bool
    password: bool  # show the username/password form
    password_providers: list[ProviderBrief]  # local / ldap
    sso: list[ProviderBrief]  # oidc buttons


# ---------- auth providers (admin, setup wizard)
class ProviderIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    type: str = Field(pattern=r"^(local|ldap|oidc)$")
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    position: int = 0
    config: dict = {}  # secrets (bind_password, client_secret) may be included; they are stored encrypted


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    position: int | None = None
    config: dict | None = None  # replaces non-secret settings
    secrets: dict | None = None  # {"client_secret": "..."}; omitted keys are kept, "" clears


class ProviderOut(ORM):
    id: uuid.UUID
    slug: str
    type: str
    name: str
    enabled: bool
    position: int
    config: dict
    secrets_set: list[str] = []
    redirect_uri: str | None = None  # OIDC: register this in the IdP


class ProviderTest(BaseModel):
    provider: ProviderIn | None = None  # unsaved settings (wizard)
    provider_id: uuid.UUID | None = None  # or a saved provider
    username: str = ""  # LDAP: also look this user up


class TestResult(BaseModel):
    ok: bool
    message: str


# ---------- setup wizard
class SetupAdmin(BaseModel):
    username: str = Field(min_length=2, max_length=150, pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=255)
    email: str | None = None
    password: str = Field(min_length=10, max_length=256)


class SetupIn(BaseModel):
    token: str = Field(max_length=200)
    admin: SetupAdmin
    local_mode: str = Field(default="all", pattern=r"^(all|admins)$")  # admins = break-glass only
    providers: list[ProviderIn] = []  # ldap / oidc


class SetupToken(BaseModel):
    token: str = Field(max_length=200)


class SetupStatus(BaseModel):
    required: bool
    base_url: str


# ---------- RBAC
class PermissionInfo(BaseModel):
    key: str
    scope: str


class RoleBrief(ORM):
    id: uuid.UUID
    key: str
    name: str


class RoleOut(RoleBrief):
    description: str
    scope: str
    permissions: list[str]
    builtin: bool
    is_default: bool


class RoleIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    scope: str = Field(pattern=r"^(global|project)$")
    permissions: list[str] = []


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    permissions: list[str] | None = None
    is_default: bool | None = None


class BindingIn(BaseModel):
    group: str = Field(min_length=1, max_length=500)  # LDAP group DN or IdP group name
    role: str  # role key
    provider: str | None = None  # provider slug; empty = group of that name from any provider


class BindingOut(ORM):
    id: uuid.UUID
    group: str
    role: RoleBrief
    provider: ProviderBrief | None
    project_key: str | None = None


class UserRolesIn(BaseModel):
    roles: list[str]  # global role keys


class UserAdminPatch(BaseModel):
    is_admin: bool | None = None
    is_active: bool | None = None


class LocalUserIn(BaseModel):
    username: str = Field(min_length=2, max_length=150, pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=255)
    email: str | None = None
    password: str = Field(min_length=10, max_length=256)
    is_admin: bool = False


# ---------- projects
KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


class StateOut(ORM):
    id: uuid.UUID
    name: str
    category: StateCategory
    position: int


class StateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    category: StateCategory
    position: int | None = None


class StatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    category: StateCategory | None = None
    position: int | None = None


class ProjectIn(BaseModel):
    key: str
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    is_private: bool = True

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = v.strip().upper()
        if not KEY_RE.match(v):
            raise ValueError("key: 2-10 Latin letters/digits, starting with a letter")
        return v


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_private: bool | None = None
    lead_id: uuid.UUID | None = None
    archived: bool | None = None


class ProjectOut(ORM):
    id: uuid.UUID
    key: str
    name: str
    description: str
    is_private: bool
    archived: bool
    lead: UserBrief | None
    created_at: datetime


class ProjectDetail(ProjectOut):
    states: list[StateOut]
    my_role: str | None = None  # key of the direct membership role
    my_permissions: list[str] = []
    open_issues: int = 0


class MemberOut(ORM):
    user: UserBrief
    role: RoleBrief


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role: str = "member"  # project role key


class MemberPatch(BaseModel):
    role: str


class LabelOut(ORM):
    id: uuid.UUID
    name: str
    color: str


class LabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(default="#8a8f98", pattern=r"^#[0-9a-fA-F]{6}$")


class SprintIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    goal: str = ""
    start_date: date | None = None
    end_date: date | None = None


class SprintPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    closed: bool | None = None


class Progress(BaseModel):
    total: int = 0
    scope: int = 0
    done: int = 0
    percent: int = 0
    by_category: dict[str, int] = {}
    points_scope: float = 0
    points_done: float = 0
    points_percent: int = 0


class SprintOut(ORM):
    id: uuid.UUID
    name: str
    goal: str
    start_date: date | None
    end_date: date | None
    closed: bool
    closed_at: datetime | None = None
    status: str = "draft"  # draft (no dates) | upcoming | active | completed
    progress: Progress = Progress()


class SprintComplete(BaseModel):
    move_to: uuid.UUID | None = None  # unfinished issues go to this cycle, or to no cycle


class ModuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    status: str = Field(default="planned", pattern=r"^(backlog|planned|in_progress|paused|completed|cancelled)$")
    lead_id: uuid.UUID | None = None
    start_date: date | None = None
    target_date: date | None = None


class ModulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    status: str | None = Field(default=None, pattern=r"^(backlog|planned|in_progress|paused|completed|cancelled)$")
    lead_id: uuid.UUID | None = None
    start_date: date | None = None
    target_date: date | None = None


class ModuleOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    status: str
    lead: UserBrief | None
    start_date: date | None
    target_date: date | None
    created_at: datetime
    progress: Progress = Progress()


class BurnPoint(BaseModel):
    date: date
    scope: int | None
    done: int | None
    points_scope: float | None
    points_done: float | None


class ProgressDetail(BaseModel):
    progress: Progress
    start: date
    end: date
    burndown: list[BurnPoint]
    people: list[dict]


# ---------- issues
class IssueIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    type: IssueType = IssueType.task
    state_id: uuid.UUID | None = None
    priority: Priority = Priority.none
    assignee_ids: list[uuid.UUID] = []
    label_ids: list[uuid.UUID] = []
    module_ids: list[uuid.UUID] = []
    parent_key: str | None = None
    sprint_id: uuid.UUID | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimate: float | None = Field(default=None, ge=0)


class IssuePatch(BaseModel):
    """Only fields present in the request are changed (exclude_unset)."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    type: IssueType | None = None
    state_id: uuid.UUID | None = None
    priority: Priority | None = None
    assignee_ids: list[uuid.UUID] | None = None
    label_ids: list[uuid.UUID] | None = None
    module_ids: list[uuid.UUID] | None = None
    parent_key: str | None = None
    sprint_id: uuid.UUID | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimate: float | None = Field(default=None, ge=0)
    position: float | None = None


class IssueOut(ORM):
    id: uuid.UUID
    key: str
    number: int
    type: IssueType
    title: str
    priority: Priority
    state: StateOut
    assignees: list[UserBrief]
    labels: list[LabelOut]
    parent_key: str | None = None
    sprint_id: uuid.UUID | None
    module_ids: list[uuid.UUID] = []
    start_date: date | None
    due_date: date | None
    estimate: float | None
    position: float
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    subtasks_total: int = 0
    subtasks_done: int = 0


class IssueDetail(IssueOut):
    description: str
    reporter: UserBrief | None
    project_key: str = ""
    started_at: datetime | None
    subtasks: list[IssueOut] = []


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)


class CommentOut(ORM):
    id: uuid.UUID
    body: str
    author: UserBrief | None
    created_at: datetime
    edited_at: datetime | None


class ActivityOut(ORM):
    id: int
    field: str
    old_value: str | None
    new_value: str | None
    actor: UserBrief | None
    created_at: datetime


# ---------- notifications
class NotifyPrefs(BaseModel):
    email_enabled: bool = True
    events: list[str] = []
    lang: str | None = Field(default=None, pattern=r"^(en|ru)$")


class SmtpIn(BaseModel):
    enabled: bool = True
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    security: str = Field(default="starttls", pattern=r"^(none|starttls|ssl)$")
    username: str = ""
    password: str | None = None  # None = keep the stored one
    from_address: str = Field(default="", max_length=320)


class SmtpOut(BaseModel):
    enabled: bool
    host: str
    port: int
    security: str
    username: str
    from_address: str
    password_set: bool


class SmtpTest(BaseModel):
    to: str = Field(min_length=3, max_length=320)


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(pattern=r"^(slack|mattermost|rocketchat|teams|discord|telegram|generic)$")
    enabled: bool = True
    events: list[str] = ["created", "assigned", "state_changed", "commented"]
    lang: str = Field(default="en", pattern=r"^(en|ru)$")
    config: dict = {}  # telegram: chat_id, thread_id, api_url
    secrets: dict = {}  # url / bot_token / signing_secret; omitted or "" keeps the stored value on update


class ChannelOut(ORM):
    id: uuid.UUID
    name: str
    type: str
    enabled: bool
    events: list[str]
    lang: str
    config: dict
    secrets_set: list[str] = []
    project_key: str | None = None


class OutboxOut(ORM):
    id: int
    kind: str
    recipient: str
    subject: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None
    next_attempt_at: datetime


# ---------- documentation pages
class PageIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=2_000_000)
    parent_id: uuid.UUID | None = None


class PagePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=2_000_000)
    parent_id: uuid.UUID | None = None
    position: float | None = None


class PageBrief(ORM):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    position: float
    updated_at: datetime


class PageOut(PageBrief):
    body: str
    created_at: datetime
    updated_by: UserBrief | None


# ---------- imports
class ImportSource(BaseModel):
    """Where to import from. Credentials are kept encrypted only while the job runs."""

    source: str = Field(pattern=r"^(jira|plane|confluence)$")
    url: str = Field(min_length=8, max_length=500)
    workspace: str = Field(default="", max_length=100)  # Plane workspace slug
    username: str = Field(default="", max_length=200)  # Jira/Confluence Cloud: account e-mail; Server: login
    token: str = Field(default="", max_length=2000)  # API token / personal access token / password


class ImportIn(ImportSource):
    remote: str = Field(min_length=1, max_length=200)  # Jira project key, Plane project id, Confluence space key
    target_key: str = Field(min_length=2, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9]{1,9}$")
    target_name: str = Field(default="", max_length=200)  # used when the project is created
    include_comments: bool = True


class RemoteProject(BaseModel):
    id: str
    key: str
    name: str


class ImportJobOut(ORM):
    id: uuid.UUID
    source: str
    status: str
    params: dict
    stats: dict
    log: str
    error: str | None
    project_key: str | None
    created_by: UserBrief | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
