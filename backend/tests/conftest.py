"""Tests run against a real PostgreSQL (LODESTONE_TEST_DATABASE_URL) with Alembic migrations applied,
and an in-memory LDAP directory (ldap3 MOCK_SYNC)."""
import functools
import os

import pytest

TEST_DB = os.environ.get("LODESTONE_TEST_DATABASE_URL",
                         "postgresql+psycopg://postgres@/lodestone_test?host=/tmp&port=55432")
os.environ.update({
    "LODESTONE_DATABASE_URL": TEST_DB,
    "LODESTONE_SECRET_KEY": "test-secret-key-123",
    "LODESTONE_COOKIE_SECURE": "false",
    "LODESTONE_ADMIN_USERNAME": "admin",
    "LODESTONE_ADMIN_PASSWORD": "admin-password-1",
    "LODESTONE_LDAP_ENABLED": "true",
    "LODESTONE_LDAP_URL": "ldap://fake",
    "LODESTONE_LDAP_BIND_DN": "cn=svc,dc=corp,dc=local",
    "LODESTONE_LDAP_BIND_PASSWORD": "svc-pass",
    "LODESTONE_LDAP_USER_BASE": "ou=users,dc=corp,dc=local",
    "LODESTONE_LDAP_USER_FILTER": "(uid={username})",
    "LODESTONE_LDAP_ALLOWED_GROUP": "cn=tracker-users,ou=groups,dc=corp,dc=local",
    "LODESTONE_LDAP_ADMIN_GROUP": "cn=tracker-admins,ou=groups,dc=corp,dc=local",
})

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from ldap3 import MOCK_SYNC, Connection, Server  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app import ldap_auth  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app, bootstrap_admin  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DIRECTORY = {
    "cn=svc,dc=corp,dc=local": {"objectClass": ["person"], "cn": "svc", "userPassword": "svc-pass"},
    "uid=akzhol,ou=users,dc=corp,dc=local": {
        "objectClass": ["inetOrgPerson"], "uid": "akzhol", "cn": "Akzhol", "sn": "M",
        "displayName": "Akzhol Muratov", "mail": "akzhol@corp.local", "userPassword": "ak-pass"},
    "uid=nurlan,ou=users,dc=corp,dc=local": {
        "objectClass": ["inetOrgPerson"], "uid": "nurlan", "cn": "Nurlan", "sn": "T",
        "displayName": "Nurlan Tasbolatov", "mail": "nurlan@corp.local", "userPassword": "nu-pass"},
    "uid=outsider,ou=users,dc=corp,dc=local": {
        "objectClass": ["inetOrgPerson"], "uid": "outsider", "cn": "Out", "sn": "S",
        "displayName": "Outsider", "userPassword": "out-pass"},
    "cn=tracker-users,ou=groups,dc=corp,dc=local": {
        "objectClass": ["groupOfNames"], "cn": "tracker-users",
        "member": ["uid=akzhol,ou=users,dc=corp,dc=local", "uid=nurlan,ou=users,dc=corp,dc=local"]},
    "cn=tracker-admins,ou=groups,dc=corp,dc=local": {
        "objectClass": ["groupOfNames"], "cn": "tracker-admins",
        "member": ["uid=akzhol,ou=users,dc=corp,dc=local"]},
}


@pytest.fixture(scope="session", autouse=True)
def migrated():
    cfg = Config(os.path.join(HERE, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(HERE, "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_db():
    with engine().begin() as c:
        c.execute(text("TRUNCATE users, projects, login_attempts RESTART IDENTITY CASCADE"))
    bootstrap_admin()
    yield


@pytest.fixture(autouse=True)
def fake_ldap(monkeypatch):
    server = Server("fake")
    loader = Connection(server, user="cn=svc,dc=corp,dc=local", password="svc-pass", client_strategy=MOCK_SYNC)
    for dn, attrs in DIRECTORY.items():
        loader.strategy.add_entry(dn, attrs)
    monkeypatch.setattr(ldap_auth, "_server", lambda s: server)
    real = ldap_auth.authenticate
    monkeypatch.setattr(ldap_auth, "authenticate", functools.partial(
        real, connection_factory=functools.partial(Connection, client_strategy=MOCK_SYNC)))
    yield server


def make_client(username: str | None = None, password: str | None = None) -> TestClient:
    c = TestClient(app)
    if username:
        r = c.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
    return c


@pytest.fixture
def admin():
    return make_client("admin", "admin-password-1")


@pytest.fixture
def akzhol():
    return make_client("akzhol", "ak-pass")


@pytest.fixture
def nurlan():
    return make_client("nurlan", "nu-pass")
