"""Sending notifications: SMTP e-mail and messenger webhooks, from the outbox table with retries.

Several workers/replicas can run at once: each takes due rows with FOR UPDATE SKIP LOCKED.
"""
import hashlib
import hmac
import ipaddress
import json
import logging
import smtplib
import socket
import ssl
import threading
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto
from .config import get_settings
from .db import session_factory
from .models import AppSetting, NotificationChannel, OutboxMessage, utcnow

log = logging.getLogger("lodestone.notify")

SMTP_KEY = "smtp"
BACKOFF_MINUTES = [1, 5, 30, 120, 360]  # after the last one the message is marked failed
CHANNEL_TYPES = ["slack", "mattermost", "rocketchat", "teams", "discord", "telegram", "generic"]
CHANNEL_SECRETS = {"telegram": ("bot_token",), "generic": ("url", "signing_secret")}


def secret_fields(type_: str) -> tuple[str, ...]:
    return CHANNEL_SECRETS.get(type_, ("url",))


class DeliveryError(Exception):
    pass


# ---------- SMTP settings (DB first, env as the initial value)
def smtp_config(db: Session) -> dict:
    row = db.get(AppSetting, SMTP_KEY)
    if row:
        cfg = dict(row.value)
        cfg["password"] = crypto.decrypt(cfg.pop("secrets", None)).get("password", "")
        return cfg
    s = get_settings()
    return {"host": s.smtp_host, "port": s.smtp_port, "security": s.smtp_security, "username": s.smtp_username,
            "password": s.smtp_password, "from_address": s.smtp_from, "enabled": bool(s.smtp_host)}


def save_smtp_config(db: Session, cfg: dict, password: str | None):
    """password: None = keep the stored one, "" = clear."""
    current = smtp_config(db)
    pw = current.get("password", "") if password is None else password
    value = {k: cfg[k] for k in ("host", "port", "security", "username", "from_address", "enabled") if k in cfg}
    value["secrets"] = crypto.encrypt({"password": pw})
    row = db.get(AppSetting, SMTP_KEY)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=SMTP_KEY, value=value))


def smtp_ready(cfg: dict) -> bool:
    return bool(cfg.get("enabled") and cfg.get("host") and cfg.get("from_address"))


def smtp_client(cfg: dict) -> smtplib.SMTP:
    """Separate function so tests can swap in a fake server."""
    timeout = 15
    if cfg.get("security") == "ssl":
        return smtplib.SMTP_SSL(cfg["host"], int(cfg.get("port") or 465), timeout=timeout,
                                context=ssl.create_default_context())
    client = smtplib.SMTP(cfg["host"], int(cfg.get("port") or 25), timeout=timeout)
    if cfg.get("security", "starttls") == "starttls":
        client.starttls(context=ssl.create_default_context())
    return client


def send_email(cfg: dict, to: str, subject: str, plain: str, html: str | None = None):
    if not smtp_ready(cfg):
        raise DeliveryError("SMTP is not configured")
    msg = EmailMessage()
    name, addr = parseaddr(cfg["from_address"])
    msg["From"] = formataddr((name or "Lodestone", addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=addr.split("@")[-1] or None)
    msg["Auto-Submitted"] = "auto-generated"  # RFC 3834: no auto-replies
    msg.set_content(plain)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtp_client(cfg) as client:
            if cfg.get("username"):
                client.login(cfg["username"], cfg.get("password", ""))
            client.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise DeliveryError(f"SMTP: {e}") from e


# ---------- webhooks
def http_client() -> httpx.Client:
    """Separate function so tests can swap in httpx.MockTransport."""
    return httpx.Client(timeout=get_settings().webhook_timeout, follow_redirects=False)


def check_url(url: str):
    """Blocks requests to internal addresses (SSRF) unless LODESTONE_WEBHOOK_ALLOW_PRIVATE=true."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise DeliveryError("Webhook URL must be http(s)://host/...")
    if get_settings().webhook_allow_private:
        return
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except OSError as e:
        raise DeliveryError(f"Cannot resolve {u.hostname}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise DeliveryError(f"{u.hostname} resolves to a private address {ip}; "
                                "set LODESTONE_WEBHOOK_ALLOW_PRIVATE=true to allow internal messengers")


def channel_secrets(ch: NotificationChannel) -> dict:
    return crypto.decrypt(ch.secrets)


def build_request(ch: NotificationChannel, payload: dict) -> tuple[str, dict, dict]:
    """(url, json body, headers) in the format the messenger expects."""
    sec = channel_secrets(ch)
    msg, link = payload["text"], payload.get("url") or ""
    if ch.type == "telegram":
        api = (ch.config.get("api_url") or "https://api.telegram.org").rstrip("/")
        if not sec.get("bot_token") or not ch.config.get("chat_id"):
            raise DeliveryError("Telegram needs a bot token and a chat id")
        body = {"chat_id": ch.config["chat_id"], "text": f"{msg}\n{link}".strip(), "disable_web_page_preview": True}
        if ch.config.get("thread_id"):
            body["message_thread_id"] = ch.config["thread_id"]
        return f"{api}/bot{sec['bot_token']}/sendMessage", body, {}
    url = sec.get("url", "")
    if not url:
        raise DeliveryError("Webhook URL is not set")
    if ch.type in ("slack", "mattermost", "rocketchat"):
        return url, {"text": f"{msg}\n<{link}>" if link else msg}, {}
    if ch.type == "discord":
        return url, {"content": f"{msg}\n{link}".strip()}, {}
    if ch.type == "teams":  # Teams Workflows ("Post to a channel when a webhook request is received")
        actions = [{"type": "Action.OpenUrl", "title": payload.get("key", "Open"), "url": link}] if link else []
        card = {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "version": "1.4", "body": [{"type": "TextBlock", "text": msg, "wrap": True}], "actions": actions}
        return url, {"type": "message", "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}, {}
    # generic JSON, optionally signed like GitHub webhooks
    body = {"event": payload.get("event"), "text": msg, "url": link, "data": payload.get("data", {})}
    headers = {"X-Lodestone-Event": str(payload.get("event"))}
    if sec.get("signing_secret"):
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        headers["X-Lodestone-Signature"] = "sha256=" + hmac.new(sec["signing_secret"].encode(), raw,
                                                               hashlib.sha256).hexdigest()
        return url, {"__raw__": raw.decode()}, headers
    return url, body, headers


def send_webhook(ch: NotificationChannel, payload: dict):
    url, body, headers = build_request(ch, payload)
    check_url(url)
    try:
        with http_client() as c:
            if "__raw__" in body:
                r = c.post(url, content=body["__raw__"].encode(),
                           headers={**headers, "Content-Type": "application/json"})
            else:
                r = c.post(url, json=body, headers=headers)
    except httpx.HTTPError as e:
        raise DeliveryError(f"{type(e).__name__}: {e}".replace(url, "<url>")) from e
    if r.status_code >= 300:
        raise DeliveryError(f"HTTP {r.status_code}: {r.text[:200]}")


# ---------- worker
def _deliver(db: Session, m: OutboxMessage, smtp: dict | None):
    if m.kind == "email":
        send_email(smtp or {}, m.recipient, m.subject, m.payload.get("text", ""), m.payload.get("html"))
    else:
        ch = db.get(NotificationChannel, m.payload.get("channel_id"))
        if not ch or not ch.enabled:
            return  # channel removed or switched off since: drop silently
        send_webhook(ch, m.payload)


def run_once(limit: int = 50) -> int:
    """Sends due messages. Returns how many were processed."""
    with session_factory()() as db:
        rows = db.scalars(select(OutboxMessage).where(OutboxMessage.status == "pending",
                                                      OutboxMessage.next_attempt_at <= utcnow())
                          .order_by(OutboxMessage.id).limit(limit).with_for_update(skip_locked=True)).all()
        smtp = smtp_config(db) if any(m.kind == "email" for m in rows) else None
        for m in rows:
            m.attempts += 1
            try:
                _deliver(db, m, smtp)
                m.status, m.sent_at, m.last_error = "sent", utcnow(), None
            except DeliveryError as e:
                m.last_error = str(e)[:1000]
                if m.attempts > len(BACKOFF_MINUTES):
                    m.status = "failed"
                    log.warning("notification %s failed for good: %s", m.id, e)
                else:
                    m.next_attempt_at = utcnow() + timedelta(minutes=BACKOFF_MINUTES[m.attempts - 1])
        db.commit()
        return len(rows)


class Worker(threading.Thread):
    def __init__(self, interval: float = 5.0):
        super().__init__(name="lodestone-notify", daemon=True)
        self.interval = interval
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                busy = run_once()
            except Exception:  # never let the loop die; DB may be restarting
                log.exception("notification worker error")
                busy = 0
            if not busy:
                self.stop.wait(self.interval)


def main():
    """`python -m app.delivery`: a dedicated worker process."""
    logging.basicConfig(level=logging.INFO)
    w = Worker()
    w.run()


if __name__ == "__main__":
    main()
