"""Notification settings: SMTP, messenger channels (global and per project), personal e-mail preferences."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto, delivery, messages, notify, rbac
from ..config import get_settings
from ..db import get_db
from ..deps import current_user, project_for, require
from ..models import NotificationChannel, NotificationPref, OutboxMessage, Project, User, utcnow
from ..schemas import (
    ChannelIn,
    ChannelOut,
    NotifyPrefs,
    OutboxOut,
    SmtpIn,
    SmtpOut,
    SmtpTest,
    TestResult,
)

router = APIRouter(prefix="/api", tags=["notifications"])
manage = require(rbac.NOTIFICATIONS_MANAGE)


# ---------- personal
@router.get("/me/notifications", response_model=NotifyPrefs)
def my_prefs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = db.get(NotificationPref, user.id)
    if not p:
        return NotifyPrefs(email_enabled=True, events=messages.EVENTS, lang=None)
    return NotifyPrefs(email_enabled=p.email_enabled, events=p.events, lang=p.lang)


@router.put("/me/notifications", response_model=NotifyPrefs)
def set_my_prefs(body: NotifyPrefs, db: Session = Depends(get_db), user: User = Depends(current_user)):
    bad = set(body.events) - set(messages.EVENTS)
    if bad:
        raise HTTPException(422, f"Unknown events: {', '.join(sorted(bad))}")
    p = db.get(NotificationPref, user.id) or NotificationPref(user_id=user.id)
    p.email_enabled, p.events, p.lang = body.email_enabled, [e for e in messages.EVENTS if e in body.events], body.lang
    db.add(p)
    db.commit()
    return NotifyPrefs(email_enabled=p.email_enabled, events=p.events, lang=p.lang)


# ---------- SMTP
def _smtp_out(cfg: dict) -> SmtpOut:
    return SmtpOut(enabled=bool(cfg.get("enabled")), host=cfg.get("host", ""), port=int(cfg.get("port") or 587),
                   security=cfg.get("security", "starttls"), username=cfg.get("username", ""),
                   from_address=cfg.get("from_address", ""), password_set=bool(cfg.get("password")))


@router.get("/admin/notifications/smtp", response_model=SmtpOut)
def get_smtp(db: Session = Depends(get_db), _: User = Depends(manage)):
    return _smtp_out(delivery.smtp_config(db))


@router.put("/admin/notifications/smtp", response_model=SmtpOut)
def put_smtp(body: SmtpIn, db: Session = Depends(get_db), _: User = Depends(manage)):
    delivery.save_smtp_config(db, body.model_dump(exclude={"password"}), body.password)
    db.commit()
    return _smtp_out(delivery.smtp_config(db))


@router.post("/admin/notifications/smtp/test", response_model=TestResult)
def test_smtp(body: SmtpTest, db: Session = Depends(get_db), _: User = Depends(manage)):
    lang = messages.lang_or_default(None, get_settings().notify_lang)
    try:
        delivery.send_email(delivery.smtp_config(db), body.to, messages.text(lang, "test.subject"),
                            messages.text(lang, "test.body"))
    except delivery.DeliveryError as e:
        return TestResult(ok=False, message=str(e))
    return TestResult(ok=True, message=f"Sent to {body.to}")


# ---------- outbox (delivery log)
@router.get("/admin/notifications/outbox", response_model=list[OutboxOut])
def outbox(status: str | None = None, limit: int = 100, db: Session = Depends(get_db), _: User = Depends(manage)):
    stmt = select(OutboxMessage)
    if status:
        stmt = stmt.where(OutboxMessage.status == status)
    return db.scalars(stmt.order_by(OutboxMessage.id.desc()).limit(min(limit, 500))).all()


@router.post("/admin/notifications/outbox/{msg_id}/retry", response_model=OutboxOut)
def retry(msg_id: int, db: Session = Depends(get_db), _: User = Depends(manage)):
    m = db.get(OutboxMessage, msg_id)
    if not m:
        raise HTTPException(404, "Message not found")
    m.status, m.attempts, m.next_attempt_at = "pending", 0, utcnow()
    db.commit()
    return m


# ---------- channels
def _out(ch: NotificationChannel, project_key: str | None = None) -> ChannelOut:
    out = ChannelOut.model_validate(ch, from_attributes=True)
    out.secrets_set = sorted(k for k, v in delivery.channel_secrets(ch).items() if v)
    out.project_key = project_key
    return out


def _apply(ch: NotificationChannel, body: ChannelIn, creating: bool):
    bad = set(body.events) - set(messages.CHANNEL_EVENTS)
    if bad:
        raise HTTPException(422, f"Unknown events: {', '.join(sorted(bad))}")
    if not creating and body.type != ch.type:
        raise HTTPException(422, "The messenger type cannot be changed; create a new channel")
    ch.name, ch.type, ch.enabled, ch.lang = body.name, body.type, body.enabled, body.lang
    ch.events = [e for e in messages.CHANNEL_EVENTS if e in body.events]
    ch.config = {k: v for k, v in body.config.items() if k in ("chat_id", "thread_id", "api_url")}
    allowed = delivery.secret_fields(body.type)
    current = {} if creating else crypto.decrypt(ch.secrets)
    for k, v in body.secrets.items():
        if k in allowed and v:
            current[k] = v
        elif k in allowed and v is None:
            current.pop(k, None)
    ch.secrets = crypto.encrypt(current)
    url = current.get("url")
    if url:
        try:
            delivery.check_url(url)
        except delivery.DeliveryError as e:
            raise HTTPException(422, str(e)) from None


def _test(db: Session, ch: NotificationChannel) -> TestResult:
    try:
        delivery.send_webhook(ch, notify.test_message(db, ch))
    except delivery.DeliveryError as e:
        return TestResult(ok=False, message=str(e))
    return TestResult(ok=True, message="Sent")


def _channel(db: Session, channel_id: uuid.UUID, project: Project | None) -> NotificationChannel:
    ch = db.get(NotificationChannel, channel_id)
    if not ch or ch.project_id != (project.id if project else None):
        raise HTTPException(404, "Channel not found")
    return ch


@router.get("/admin/notification-channels", response_model=list[ChannelOut])
def global_channels(db: Session = Depends(get_db), _: User = Depends(manage)):
    rows = db.scalars(select(NotificationChannel).where(NotificationChannel.project_id.is_(None))
                      .order_by(NotificationChannel.name)).all()
    return [_out(c) for c in rows]


@router.post("/admin/notification-channels", response_model=ChannelOut, status_code=201)
def add_global_channel(body: ChannelIn, db: Session = Depends(get_db), _: User = Depends(manage)):
    ch = NotificationChannel()
    _apply(ch, body, True)
    db.add(ch)
    db.commit()
    return _out(ch)


@router.put("/admin/notification-channels/{channel_id}", response_model=ChannelOut)
def update_global_channel(channel_id: uuid.UUID, body: ChannelIn, db: Session = Depends(get_db),
                          _: User = Depends(manage)):
    ch = _channel(db, channel_id, None)
    _apply(ch, body, False)
    db.commit()
    return _out(ch)


@router.delete("/admin/notification-channels/{channel_id}", status_code=204)
def delete_global_channel(channel_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(manage)):
    db.delete(_channel(db, channel_id, None))
    db.commit()


@router.post("/admin/notification-channels/{channel_id}/test", response_model=TestResult)
def test_global_channel(channel_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(manage)):
    return _test(db, _channel(db, channel_id, None))


@router.get("/projects/{key}/notification-channels", response_model=list[ChannelOut])
def project_channels(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.PROJECT_MANAGE)
    rows = db.scalars(select(NotificationChannel).where(NotificationChannel.project_id == p.id)
                      .order_by(NotificationChannel.name)).all()
    return [_out(c, p.key) for c in rows]


@router.post("/projects/{key}/notification-channels", response_model=ChannelOut, status_code=201)
def add_project_channel(key: str, body: ChannelIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.PROJECT_MANAGE)
    ch = NotificationChannel(project_id=p.id)
    _apply(ch, body, True)
    db.add(ch)
    db.commit()
    return _out(ch, p.key)


@router.put("/projects/{key}/notification-channels/{channel_id}", response_model=ChannelOut)
def update_project_channel(key: str, channel_id: uuid.UUID, body: ChannelIn, db: Session = Depends(get_db),
                           user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.PROJECT_MANAGE)
    ch = _channel(db, channel_id, p)
    _apply(ch, body, False)
    db.commit()
    return _out(ch, p.key)


@router.delete("/projects/{key}/notification-channels/{channel_id}", status_code=204)
def delete_project_channel(key: str, channel_id: uuid.UUID, db: Session = Depends(get_db),
                           user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.PROJECT_MANAGE)
    db.delete(_channel(db, channel_id, p))
    db.commit()


@router.post("/projects/{key}/notification-channels/{channel_id}/test", response_model=TestResult)
def test_project_channel(key: str, channel_id: uuid.UUID, db: Session = Depends(get_db),
                         user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.PROJECT_MANAGE)
    return _test(db, _channel(db, channel_id, p))
