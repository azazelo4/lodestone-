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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Role(str, enum.Enum):
    admin = "admin"
    member = "member"
    viewer = "viewer"


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


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(10), default="local")  # local | ldap
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


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "member_role"), default=Role.member)
    user: Mapped[User] = relationship()


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
