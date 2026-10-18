import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class StateCategory(str, enum.Enum):
    backlog = "backlog"
    todo = "todo"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


CLOSED = (StateCategory.done, StateCategory.cancelled)


class Priority(str, enum.Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class IssueType(str, enum.Enum):
    task = "task"
    bug = "bug"
    story = "story"
    epic = "epic"


def _enum(e, name):
    return Enum(e, name=name, values_callable=lambda x: [i.value for i in x])


class AuthProvider(Base):
    """A way to sign in: local accounts, an LDAP/AD directory or an OpenID Connect identity provider (SSO)."""

    __tablename__ = "auth_providers"
    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    type: Mapped[str] = mapped_column(String(10))  # local | ldap | oidc
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    secrets: Mapped[str | None] = mapped_column(Text)  # encrypted JSON, see crypto.py
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(10), default="local")  # local | ldap | oidc
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("auth_providers.id", ondelete="SET NULL"))
    external_id: Mapped[str | None] = mapped_column(String(255))  # OIDC "sub"
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_private: Mapped[bool] = mapped_column(Boolean, default=True)
    issue_seq: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lead: Mapped[User | None] = relationship()
    states: Mapped[list["State"]] = relationship(order_by="State.position", cascade="all, delete-orphan")
    members: Mapped[list["ProjectMember"]] = relationship(cascade="all, delete-orphan")


class Role(Base):
    """Named set of permissions (see rbac.py). scope: global | project."""

    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(String(10))
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # global role every user has


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class UserGroup(Base):
    """Directory/IdP groups of a user, refreshed at every sign-in. name is lower-cased."""

    __tablename__ = "user_groups"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("auth_providers.id", ondelete="CASCADE"),
                                                   primary_key=True)
    name: Mapped[str] = mapped_column(String(500), primary_key=True)


class GroupBinding(Base):
    """Gives a role to everyone in a directory group: globally (project_id is NULL) or in one project."""

    __tablename__ = "group_bindings"
    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("auth_providers.id", ondelete="CASCADE"))
    group: Mapped[str] = mapped_column(String(500))
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[Role] = relationship()
    provider: Mapped[AuthProvider | None] = relationship()


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"))
    user: Mapped[User] = relationship()
    role: Mapped[Role] = relationship()


class State(Base):
    __tablename__ = "states"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    category: Mapped[StateCategory] = mapped_column(_enum(StateCategory, "state_category"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("project_id", "name"),)


class Label(Base):
    __tablename__ = "labels"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(7), default="#8a8f98")
    __table_args__ = (UniqueConstraint("project_id", "name"),)


class Sprint(Base):
    __tablename__ = "sprints"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    goal: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)


issue_assignees = Table(
    "issue_assignees", Base.metadata,
    Column("issue_id", ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
)

issue_labels = Table(
    "issue_labels", Base.metadata,
    Column("issue_id", ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
)


class Issue(Base):
    __tablename__ = "issues"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    type: Mapped[IssueType] = mapped_column(_enum(IssueType, "issue_type"), default=IssueType.task)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    state_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("states.id"), index=True)
    priority: Mapped[Priority] = mapped_column(_enum(Priority, "priority"), default=Priority.none)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id", ondelete="SET NULL"), index=True)
    sprint_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sprints.id", ondelete="SET NULL"), index=True)
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    estimate: Mapped[float | None] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship()
    state: Mapped[State] = relationship()
    reporter: Mapped[User | None] = relationship(foreign_keys=[reporter_id])
    assignees: Mapped[list[User]] = relationship(secondary=issue_assignees, order_by=User.display_name)
    labels: Mapped[list[Label]] = relationship(secondary=issue_labels, order_by=Label.name)
    parent: Mapped["Issue | None"] = relationship(remote_side=[id])
    __table_args__ = (UniqueConstraint("project_id", "number"),)

    @property
    def key(self) -> str:
        return f"{self.project.key}-{self.number}"


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[uuid.UUID] = uuid_pk()
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    author: Mapped[User | None] = relationship()


class Activity(Base):
    """Field-level change log. state changes keep state ids → lead/cycle time analytics."""

    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    old_ref: Mapped[str | None] = mapped_column(String(64))
    new_ref: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    actor: Mapped[User | None] = relationship()


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), index=True)
    ip: Mapped[str] = mapped_column(String(64))
    ok: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


DEFAULT_STATES = [
    ("Backlog", StateCategory.backlog),
    ("To Do", StateCategory.todo),
    ("In Progress", StateCategory.in_progress),
    ("In Review", StateCategory.in_progress),
    ("Done", StateCategory.done),
    ("Cancelled", StateCategory.cancelled),
]


class NotificationChannel(Base):
    """A messenger webhook: Slack, Mattermost, Rocket.Chat, Teams, Discord, Telegram or generic JSON.
    project_id NULL = events from every project (managed by admins)."""

    __tablename__ = "notification_channels"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    events: Mapped[list[str]] = mapped_column(ARRAY(String(30)), default=list)
    lang: Mapped[str] = mapped_column(String(5), default="en")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    secrets: Mapped[str | None] = mapped_column(Text)  # encrypted: url, bot_token, signing_secret
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationPref(Base):
    """Personal e-mail settings. No row = defaults (e-mail on, every event)."""

    __tablename__ = "notification_prefs"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    events: Mapped[list[str]] = mapped_column(ARRAY(String(30)), default=list)
    lang: Mapped[str | None] = mapped_column(String(5))


class OutboxMessage(Base):
    """Transactional outbox: written together with the change, sent by the worker with retries."""

    __tablename__ = "notification_outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10))  # email | webhook
    recipient: Mapped[str] = mapped_column(String(320))  # e-mail address or channel id
    subject: Mapped[str] = mapped_column(String(300), default="")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | sent | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
