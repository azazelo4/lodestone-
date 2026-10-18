"""First-start wizard and sign-in providers."""
import concurrent.futures

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.main import bootstrap

from .conftest import make_client, reset_db

LDAP = {"slug": "corp", "type": "ldap", "name": "Corp AD", "config": {
    "url": "ldap://fake", "bind_dn": "cn=svc,dc=corp,dc=local", "bind_password": "svc-pass",
    "user_base": "ou=users,dc=corp,dc=local", "user_filter": "(uid={username})",
    "allowed_group": "cn=tracker-users,ou=groups,dc=corp,dc=local"}}
ADMIN = {"username": "root", "display_name": "Root", "password": "root-password-1"}


@pytest.fixture
def fresh(monkeypatch):
    """An empty install without env admin/LDAP: the wizard is required."""
    s = get_settings()
    for k, v in {"admin_username": "", "admin_password": "", "ldap_enabled": False, "setup_token": ""}.items():
        monkeypatch.setattr(s, k, v)
    reset_db()
    bootstrap()
    with engine().connect() as c:
        return c.execute(text("SELECT value->>'token' FROM app_settings WHERE key = 'setup'")).scalar_one()


def test_headless_install_imports_env_providers():
    cfg = make_client().get("/api/auth/config").json()
    assert cfg["setup_required"] is False
    assert [p["slug"] for p in cfg["password_providers"]] == ["local", "ldap"]
    assert make_client().get("/api/setup").json()["required"] is False


def test_wizard_needs_token(fresh):
    c = make_client()
    assert c.get("/api/auth/config").json()["setup_required"] is True
    assert c.post("/api/setup/verify", json={"token": "nope"}).status_code == 403
    assert c.post("/api/setup/verify", json={"token": fresh}).status_code == 204
    r = c.post("/api/setup", json={"token": "nope", "admin": ADMIN})
    assert r.status_code == 403


def test_wizard_creates_admin_and_several_providers(fresh):
    c = make_client()
    assert c.post("/api/setup/test", json={"provider": LDAP, "username": "nurlan"},
                  headers={"X-Setup-Token": fresh}).json()["ok"] is True
    r = c.post("/api/setup", json={"token": fresh, "admin": ADMIN, "local_mode": "all", "providers": [LDAP]})
    assert r.status_code == 200, r.text
    assert r.json()["is_admin"] is True and "auth.manage" in r.json()["permissions"]
    assert c.get("/api/auth/me").json()["username"] == "root"  # signed in right away

    cfg = make_client().get("/api/auth/config").json()
    assert cfg["setup_required"] is False
    assert [p["slug"] for p in cfg["password_providers"]] == ["local", "corp"]
    assert make_client("nurlan", "nu-pass").get("/api/auth/me").json()["source"] == "ldap"
    assert make_client("root", "root-password-1")
    # the wizard runs once
    assert c.post("/api/setup", json={"token": fresh, "admin": ADMIN}).status_code == 409


def test_wizard_runs_once_under_concurrency(fresh):
    def go(i):
        return make_client().post("/api/setup", json={"token": fresh, "admin": {**ADMIN, "username": f"root{i}"}})
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        codes = sorted(r.status_code for r in ex.map(go, range(4)))
    assert codes == [200, 409, 409, 409]


def test_local_accounts_for_admins_only(fresh):
    c = make_client()
    c.post("/api/setup", json={"token": fresh, "admin": ADMIN, "local_mode": "admins", "providers": [LDAP]})
    c.post("/api/users", json={"username": "contractor", "display_name": "C", "password": "contractor-pw"})
    assert make_client().post("/api/auth/login", json={"username": "contractor", "password": "contractor-pw"}) \
        .status_code == 401
    assert make_client("root", "root-password-1")  # break-glass admin still works
    assert make_client("nurlan", "nu-pass")


def test_several_ldap_directories(admin):
    second = {**LDAP, "slug": "branch", "name": "Branch",
              "config": {**LDAP["config"], "user_filter": "(cn={username})"}}
    assert admin.post("/api/admin/auth-providers", json=second).status_code == 201
    # "Nurlan" is the cn in the directory: only the second provider's filter finds it
    c = make_client()
    r = c.post("/api/auth/login", json={"username": "Nurlan", "password": "nu-pass", "provider": "branch"})
    assert r.status_code == 200, r.text


def test_last_enabled_provider_cannot_be_disabled(admin):
    rows = {p["slug"]: p for p in admin.get("/api/admin/auth-providers").json()}
    assert admin.patch(f"/api/admin/auth-providers/{rows['ldap']['id']}", json={"enabled": False}).status_code == 200
    assert admin.patch(f"/api/admin/auth-providers/{rows['local']['id']}", json={"enabled": False}).status_code == 400
    assert admin.delete(f"/api/admin/auth-providers/{rows['local']['id']}").status_code == 400


def test_provider_secret_kept_when_config_edited(admin):
    p = next(p for p in admin.get("/api/admin/auth-providers").json() if p["slug"] == "ldap")
    cfg = {**p["config"], "bind_password": ""}  # UI sends the form back with an empty password field
    r = admin.patch(f"/api/admin/auth-providers/{p['id']}", json={"config": cfg, "name": "Corp"})
    assert r.json()["secrets_set"] == ["bind_password"]
    assert make_client("nurlan", "nu-pass")  # still binds with the stored service password


def test_non_admin_cannot_manage_providers(nurlan):
    assert nurlan.get("/api/admin/auth-providers").status_code == 403
