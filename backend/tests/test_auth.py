from app.config import get_settings

from .conftest import make_client


def test_ldap_login_provisions_user_and_admin_group():
    c = make_client()
    r = c.post("/api/auth/login", json={"username": "Akzhol", "password": "ak-pass"})
    assert r.status_code == 200
    me = c.get("/api/auth/me").json()
    assert me["username"] == "akzhol"
    assert me["display_name"] == "Akzhol Muratov"
    assert me["email"] == "akzhol@corp.local"
    assert me["source"] == "ldap"
    assert me["is_admin"] is True  # member of tracker-admins


def test_ldap_regular_user_is_not_admin(nurlan):
    assert nurlan.get("/api/auth/me").json()["is_admin"] is False


def test_ldap_wrong_password():
    r = make_client().post("/api/auth/login", json={"username": "akzhol", "password": "nope"})
    assert r.status_code == 401


def test_ldap_user_outside_allowed_group_rejected():
    r = make_client().post("/api/auth/login", json={"username": "outsider", "password": "out-pass"})
    assert r.status_code == 401


def test_ldap_filter_injection_is_escaped():
    r = make_client().post("/api/auth/login", json={"username": "*)(uid=*", "password": "ak-pass"})
    assert r.status_code == 401


def test_empty_password_never_binds():
    r = make_client().post("/api/auth/login", json={"username": "akzhol", "password": " "})
    assert r.status_code == 401


def test_local_admin_login(admin):
    me = admin.get("/api/auth/me").json()
    assert me["is_admin"] and me["source"] == "local"


def test_unauthenticated_is_401():
    assert make_client().get("/api/projects").status_code == 401


def test_lockout_after_failures():
    c = make_client()
    for _ in range(get_settings().login_max_failures):
        assert c.post("/api/auth/login", json={"username": "nurlan", "password": "bad"}).status_code == 401
    r = c.post("/api/auth/login", json={"username": "nurlan", "password": "nu-pass"})
    assert r.status_code == 429


def test_logout_clears_session(akzhol):
    assert akzhol.post("/api/auth/logout").status_code == 204
    assert akzhol.get("/api/auth/me").status_code == 401


def test_bearer_token_works(akzhol):
    from app.security import COOKIE
    token = akzhol.cookies.get(COOKIE)
    c = make_client()
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_admin_creates_local_user(admin):
    r = admin.post("/api/users", json={"username": "contractor", "display_name": "Contractor",
                                       "password": "long-enough-pass"})
    assert r.status_code == 201
    assert make_client("contractor", "long-enough-pass").get("/api/auth/me").status_code == 200


def test_non_admin_cannot_create_users(nurlan):
    r = nurlan.post("/api/users", json={"username": "x1", "display_name": "X", "password": "long-enough-pass"})
    assert r.status_code == 403
