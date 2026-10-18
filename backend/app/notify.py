"""Turns issue events into outbox messages: e-mails to the people involved and posts to messenger channels.

Called inside the request transaction, so a notification exists only if the change was committed.
"""
import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import messages, rbac
from .config import get_settings
from .models import Comment, Issue, NotificationChannel, NotificationPref, OutboxMessage, User

MENTION = re.compile(r"(?<![\w@.])@([A-Za-z0-9._-]{2,150})")
EXCERPT = 1000


def mentioned_users(db: Session, body: str) -> list[User]:
    names = {m.lower().rstrip(".") for m in MENTION.findall(body or "")}
    if not names:
        return []
    return list(db.scalars(select(User).where(User.username.in_(names), User.is_active.is_(True))).all())


def _data(issue: Issue, actor: User, **extra) -> dict:
    base = get_settings().base_url.rstrip("/")
    key = issue.key
    data = {"key": key, "title": issue.title, "url": f"{base}/i/{key}", "actor": actor.display_name,
            "project": issue.project.key, "project_name": issue.project.name}
    data.update(extra)
    return data


def _channels(db: Session, issue: Issue, event: str) -> list[NotificationChannel]:
    return list(db.scalars(select(NotificationChannel).where(
        NotificationChannel.enabled.is_(True), NotificationChannel.events.any(event),
        or_(NotificationChannel.project_id == issue.project_id, NotificationChannel.project_id.is_(None)))).all())


def _email(db: Session, issue: Issue, event: str, users: list[User], actor: User, data: dict, sent: set):
    s = get_settings()
    settings_url = f"{s.base_url.rstrip('/')}/settings/notifications"
    for u in users:
        if u.id == actor.id or u.id in sent or not u.email or not u.is_active:
            continue
        pref = db.get(NotificationPref, u.id)
        if pref and (not pref.email_enabled or event not in (pref.events or [])):
            continue
        if rbac.PROJECT_READ not in rbac.project_permissions(db, issue.project, u):
            continue  # lost access to a private project
        lang = messages.lang_or_default(pref.lang if pref else None, s.notify_lang)
        subject, plain, html = messages.email(lang, event, data, settings_url)
        db.add(OutboxMessage(kind="email", recipient=u.email, subject=subject,
                             payload={"text": plain, "html": html, "event": event, "issue": data["key"]}))
        sent.add(u.id)


def _post(db: Session, issue: Issue, event: str, data: dict):
    for ch in _channels(db, issue, event):
        lang = messages.lang_or_default(ch.lang, get_settings().notify_lang)
        txt = messages.headline(lang, event, data, channel=True)
        if data.get("excerpt"):
            txt += "\n> " + data["excerpt"][:300].replace("\n", "\n> ")
        db.add(OutboxMessage(kind="webhook", recipient=str(ch.id), subject=data["key"], payload={
            "channel_id": str(ch.id), "event": event, "text": txt, "url": data["url"], "key": data["key"],
            "data": {k: v for k, v in data.items() if k != "url"}}))


def _participants(issue: Issue) -> list[User]:
    people = list(issue.assignees)
    if issue.reporter:
        people.append(issue.reporter)
    return people


# ---------- events
def issue_created(db: Session, issue: Issue, actor: User):
    data = _data(issue, actor, assignees=", ".join(u.display_name for u in issue.assignees) or "—")
    sent: set[uuid.UUID] = set()
    _email(db, issue, "mentioned", mentioned_users(db, issue.description), actor, data, sent)
    _email(db, issue, "assigned", list(issue.assignees), actor, data, sent)
    _post(db, issue, "created", data)


def issue_assigned(db: Session, issue: Issue, actor: User, added: list[User]):
    if not added:
        return
    data = _data(issue, actor, assignees=", ".join(u.display_name for u in added))
    _email(db, issue, "assigned", added, actor, data, set())
    _post(db, issue, "assigned", data)


def issue_state_changed(db: Session, issue: Issue, actor: User, old: str, new: str):
    data = _data(issue, actor, old=old, new=new)
    _email(db, issue, "state_changed", _participants(issue), actor, data, set())
    _post(db, issue, "state_changed", data)


def comment_added(db: Session, issue: Issue, actor: User, comment: Comment):
    data = _data(issue, actor, excerpt=comment.body[:EXCERPT])
    sent: set[uuid.UUID] = set()
    _email(db, issue, "mentioned", mentioned_users(db, comment.body), actor, data, sent)
    earlier = db.scalars(select(User).join(Comment, Comment.author_id == User.id).where(
        Comment.issue_id == issue.id, Comment.id != comment.id).distinct()).all()
    _email(db, issue, "commented", _participants(issue) + list(earlier), actor, data, sent)
    _post(db, issue, "commented", data)


def test_message(db: Session, ch: NotificationChannel):
    lang = messages.lang_or_default(ch.lang, get_settings().notify_lang)
    return {"channel_id": str(ch.id), "event": "test", "text": messages.text(lang, "test.body"),
            "url": get_settings().base_url, "key": "Lodestone", "data": {}}
