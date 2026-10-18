"""Notifications: e-mail through a fake SMTP server, messenger webhooks through httpx.MockTransport, retries."""
import hashlib
import hmac
import json

import httpx
import pytest
from sqlalchemy import text

from app import delivery
from app.config import get_settings
from app.db import engine

from .conftest import make_client


class FakeSmtp:
    sent: list = []
    fail = False

    def __init__(self, cfg):
        self.cfg = cfg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        assert (user, password) == ("mailer", "mail-pass")

    def send_message(self, msg):
        if FakeSmtp.fail:
            raise delivery.smtplib.SMTPServerDisconnected("down")
        FakeSmtp.sent.append(msg)


@pytest.fixture
def mail(admin, monkeypatch):
    FakeSmtp.sent, FakeSmtp.fail = [], False
    monkeypatch.setattr(delivery, "smtp_client", FakeSmtp)
    r = admin.put("/api/admin/notifications/smtp", json={
        "host": "smtp.corp.local", "port": 587, "username": "mailer", "password": "mail-pass",
        "from_address": "Lodestone <lodestone@corp.local>"})
    assert r.status_code == 200 and r.json()["password_set"] is True and "mail-pass" not in r.text
    return FakeSmtp.sent


@pytest.fixture
def hooks(monkeypatch):
    calls: list[httpx.Request] = []
    status = {"code": 200}

    def handler(req: httpx.Request):
        calls.append(req)
        return httpx.Response(status["code"], text="ok")
    monkeypatch.setattr(delivery, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(get_settings(), "webhook_allow_private", True)  # no DNS in tests
    return calls, status


def _setup_project(akzhol, nurlan):
    """akzhol (LDAP admin) owns OPS, nurlan is a member. Both have e-mails in the directory."""
    akzhol.post("/api/projects", json={"key": "OPS", "name": "Operations", "is_private": True})
    nid = nurlan.get("/api/auth/me").json()["id"]
    akzhol.post("/api/projects/OPS/members", json={"user_id": nid, "role": "member"})
    return nid


def _bodies(sent):
    return [(m["To"], m["Subject"], m.get_body(("plain",)).get_content()) for m in sent]


def test_assignment_emails_the_assignee_only(akzhol, nurlan, mail):
    nid = _setup_project(akzhol, nurlan)
    akzhol.post("/api/projects/OPS/issues", json={"title": "Rotate certs", "assignee_ids": [nid]})
    assert delivery.run_once() == 1
    [(to, subject, body)] = _bodies(mail)
    assert to == "nurlan@corp.local"
    assert subject == "Akzhol Muratov assigned you OPS-1: Rotate certs"
    assert "https://tracker.test/i/OPS-1" in body
    assert mail[0]["Auto-Submitted"] == "auto-generated"


def test_comment_mention_and_state_change(akzhol, nurlan, mail):
    nid = _setup_project(akzhol, nurlan)
    akzhol.post("/api/projects/OPS/issues", json={"title": "Backup", "assignee_ids": [nid]})
    delivery.run_once()
    mail.clear()
    # nurlan comments: the reporter (akzhol) gets "commented", the author gets nothing
    nurlan.post("/api/issues/OPS-1/comments", json={"body": "done, see logs"})
    # akzhol mentions nurlan: one "mentioned" e-mail, not a second "commented" one
    akzhol.post("/api/issues/OPS-1/comments", json={"body": "@nurlan please double-check"})
    done = next(s["id"] for s in akzhol.get("/api/projects/OPS").json()["states"] if s["name"] == "Done")
    nurlan.patch("/api/issues/OPS-1", json={"state_id": done})
    delivery.run_once()
    got = [(to, subject) for to, subject, _ in _bodies(mail)]
    assert got == [
        ("akzhol@corp.local", "Nurlan Tasbolatov commented on OPS-1: Backup"),
        ("nurlan@corp.local", "Akzhol Muratov mentioned you in OPS-1: Backup"),
        ("akzhol@corp.local", "Nurlan Tasbolatov moved OPS-1 from “Backlog” to “Done”: Backup"),
    ]
    assert "done, see logs" in _bodies(mail)[0][2]


def test_mention_without_access_sends_nothing(akzhol, nurlan, mail):
    akzhol.post("/api/projects", json={"key": "SEC", "name": "Secret", "is_private": True})
    akzhol.post("/api/projects/SEC/issues", json={"title": "x"})
    nurlan.get("/api/auth/me")  # account exists
    akzhol.post("/api/issues/SEC-1/comments", json={"body": "@nurlan look"})
    delivery.run_once()
    assert mail == []


def test_personal_preferences(akzhol, nurlan, mail):
    nid = _setup_project(akzhol, nurlan)
    assert nurlan.get("/api/me/notifications").json()["events"] == \
        ["created", "assigned", "state_changed", "commented", "mentioned"]
    r = nurlan.put("/api/me/notifications", json={"email_enabled": True, "events": ["mentioned"], "lang": "ru"})
    assert r.status_code == 200
    akzhol.post("/api/projects/OPS/issues", json={"title": "Quiet", "assignee_ids": [nid]})
    akzhol.post("/api/issues/OPS-1/comments", json={"body": "@nurlan глянь"})
    delivery.run_once()
    [(to, subject, _)] = _bodies(mail)
    assert subject == "Akzhol Muratov упомянул(а) вас в OPS-1: Quiet"
    assert nurlan.put("/api/me/notifications", json={"events": ["bogus"]}).status_code == 422


def test_smtp_failure_is_retried_then_failed(akzhol, nurlan, mail, admin):
    nid = _setup_project(akzhol, nurlan)
    FakeSmtp.fail = True
    akzhol.post("/api/projects/OPS/issues", json={"title": "x", "assignee_ids": [nid]})
    for _ in range(len(delivery.BACKOFF_MINUTES) + 1):
        delivery.run_once()
        with engine().begin() as c:  # skip the backoff wait
            c.execute(text("UPDATE notification_outbox SET next_attempt_at = now()"))
    rows = admin.get("/api/admin/notifications/outbox?status=failed").json()
    assert len(rows) == 1 and rows[0]["attempts"] == 6 and "down" in rows[0]["last_error"]
    FakeSmtp.fail = False
    assert admin.post(f"/api/admin/notifications/outbox/{rows[0]['id']}/retry").json()["status"] == "pending"
    delivery.run_once()
    assert len(mail) == 1


def test_smtp_test_endpoint(admin, mail, nurlan):
    r = admin.post("/api/admin/notifications/smtp/test", json={"to": "ops@corp.local"})
    assert r.json()["ok"] is True and mail[0]["To"] == "ops@corp.local"
    assert nurlan.get("/api/admin/notifications/smtp").status_code == 403


def _channel(client, type_, secrets, config=None, events=None, key="OPS", lang="en"):
    r = client.post(f"/api/projects/{key}/notification-channels", json={
        "name": type_, "type": type_, "secrets": secrets, "config": config or {}, "lang": lang,
        **({"events": events} if events else {})})
    assert r.status_code == 201, r.text
    return r.json()


def test_messenger_formats(akzhol, nurlan, hooks):
    calls, _ = hooks
    _setup_project(akzhol, nurlan)
    _channel(akzhol, "mattermost", {"url": "https://mm.corp/hooks/abc"})
    _channel(akzhol, "teams", {"url": "https://corp.webhook.office.com/wf/1"})
    _channel(akzhol, "discord", {"url": "https://discord.com/api/webhooks/1/x"})
    tg = _channel(akzhol, "telegram", {"bot_token": "123:ABC"}, {"chat_id": "-100500"}, lang="ru")
    assert tg["secrets_set"] == ["bot_token"] and "123:ABC" not in json.dumps(tg)
    akzhol.post("/api/projects/OPS/issues", json={"title": "Upgrade GitLab"})
    assert delivery.run_once() == 4
    by_host = {c.url.host: json.loads(c.content) for c in calls}
    assert by_host["mm.corp"]["text"] == "Akzhol Muratov created OPS-1: Upgrade GitLab\n<https://tracker.test/i/OPS-1>"
    card = by_host["corp.webhook.office.com"]["attachments"][0]["content"]
    assert card["body"][0]["text"] == "Akzhol Muratov created OPS-1: Upgrade GitLab"
    assert by_host["discord.com"]["content"].endswith("https://tracker.test/i/OPS-1")
    tg_call = next(c for c in calls if c.url.host == "api.telegram.org")
    assert tg_call.url.path == "/bot123:ABC/sendMessage"
    assert json.loads(tg_call.content)["chat_id"] == "-100500"
    assert json.loads(tg_call.content)["text"].startswith("Akzhol Muratov создал(а) задачу OPS-1")


def test_generic_webhook_is_signed_and_filtered_by_event(akzhol, nurlan, hooks):
    calls, _ = hooks
    _setup_project(akzhol, nurlan)
    _channel(akzhol, "generic", {"url": "https://hooks.corp/lodestone", "signing_secret": "s1"}, events=["commented"])
    akzhol.post("/api/projects/OPS/issues", json={"title": "t"})
    akzhol.post("/api/issues/OPS-1/comments", json={"body": "hello"})
    delivery.run_once()
    [call] = calls  # "created" is not subscribed
    sig = "sha256=" + hmac.new(b"s1", call.content, hashlib.sha256).hexdigest()
    assert call.headers["X-Lodestone-Signature"] == sig
    body = json.loads(call.content)
    assert body["event"] == "commented" and body["data"]["excerpt"] == "hello"


def test_global_channel_gets_every_project(admin, akzhol, nurlan, hooks):
    calls, _ = hooks
    _setup_project(akzhol, nurlan)
    r = admin.post("/api/admin/notification-channels", json={"name": "all", "type": "slack",
                                                            "secrets": {"url": "https://hooks.slack.com/x"}})
    assert r.status_code == 201
    akzhol.post("/api/projects/OPS/issues", json={"title": "t"})
    delivery.run_once()
    assert [c.url.host for c in calls] == ["hooks.slack.com"]


def test_webhook_failure_backoff_and_test_button(akzhol, nurlan, hooks):
    calls, status = hooks
    _setup_project(akzhol, nurlan)
    ch = _channel(akzhol, "slack", {"url": "https://hooks.slack.com/y"})
    status["code"] = 500
    akzhol.post("/api/projects/OPS/issues", json={"title": "t"})
    delivery.run_once()
    with engine().connect() as c:
        row = c.execute(text("SELECT status, attempts, next_attempt_at > now() FROM notification_outbox")).one()
    assert tuple(row) == ("pending", 1, True)
    r = akzhol.post(f"/api/projects/OPS/notification-channels/{ch['id']}/test")
    assert r.json()["ok"] is False and "500" in r.json()["message"]
    status["code"] = 200
    assert akzhol.post(f"/api/projects/OPS/notification-channels/{ch['id']}/test").json()["ok"] is True


def test_channel_permissions_and_secret_update(akzhol, nurlan, hooks):
    _setup_project(akzhol, nurlan)
    ch = _channel(akzhol, "slack", {"url": "https://hooks.slack.com/z"})
    assert nurlan.get("/api/projects/OPS/notification-channels").status_code == 403
    r = akzhol.put(f"/api/projects/OPS/notification-channels/{ch['id']}", json={
        "name": "renamed", "type": "slack", "secrets": {"url": ""}, "events": ["commented"]})
    assert r.json()["secrets_set"] == ["url"] and r.json()["name"] == "renamed"  # empty keeps the URL


def test_private_addresses_blocked(monkeypatch):
    monkeypatch.setattr(get_settings(), "webhook_allow_private", False)
    for url in ("http://127.0.0.1:8000/x", "http://10.0.0.5/hook", "http://[::1]/x", "http://169.254.169.254/"):
        with pytest.raises(delivery.DeliveryError):
            delivery.check_url(url)
    with pytest.raises(delivery.DeliveryError):
        delivery.check_url("file:///etc/passwd")


def test_channel_with_private_url_rejected_on_save(akzhol, nurlan, monkeypatch):
    monkeypatch.setattr(get_settings(), "webhook_allow_private", False)
    _setup_project(akzhol, nurlan)
    r = akzhol.post("/api/projects/OPS/notification-channels", json={
        "name": "mm", "type": "mattermost", "secrets": {"url": "http://127.0.0.1:8065/hooks/x"}})
    assert r.status_code == 422 and "LODESTONE_WEBHOOK_ALLOW_PRIVATE" in r.text


def test_no_smtp_means_nothing_queued_breaks(akzhol, nurlan):
    """Without SMTP the e-mails stay in the outbox as errors; issue operations still work."""
    nid = _setup_project(akzhol, nurlan)
    assert akzhol.post("/api/projects/OPS/issues", json={"title": "x", "assignee_ids": [nid]}).status_code == 201
    delivery.run_once()
    admin = make_client("admin", "admin-password-1")
    [row] = admin.get("/api/admin/notifications/outbox").json()
    assert row["status"] == "pending" and row["last_error"] == "SMTP is not configured"


def test_parallel_workers_send_each_message_once(akzhol, nurlan, hooks):
    import concurrent.futures
    calls, _ = hooks
    _setup_project(akzhol, nurlan)
    _channel(akzhol, "slack", {"url": "https://hooks.slack.com/p"})
    for i in range(20):
        akzhol.post("/api/projects/OPS/issues", json={"title": f"t{i}"})
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda _: delivery.run_once(limit=5), range(8)))
    assert len(calls) == 20
