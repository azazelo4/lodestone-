"""Roles and permissions: custom roles, global roles, directory group bindings, no privilege escalation."""
from .conftest import make_client

USERS_GROUP = "cn=tracker-users,ou=groups,dc=corp,dc=local"


def _project(client, key="OPS", private=True):
    r = client.post("/api/projects", json={"key": key, "name": "Operations", "is_private": private})
    assert r.status_code == 201, r.text
    return r.json()


def _local(admin, username):
    r = admin.post("/api/users", json={"username": username, "display_name": username.title(),
                                       "password": f"{username}-password"})
    assert r.status_code == 201, r.text
    return r.json()["id"], make_client(username, f"{username}-password")


def _role(admin, key, scope, perms):
    r = admin.post("/api/roles", json={"key": key, "name": key.title(), "scope": scope, "permissions": perms})
    assert r.status_code == 201, r.text
    return r.json()


def test_builtin_roles_and_catalog(nurlan):
    keys = {r["key"]: r for r in nurlan.get("/api/roles").json()}
    assert {"admin", "member", "viewer", "user"} <= set(keys)
    assert keys["user"]["is_default"] and keys["user"]["scope"] == "global"
    perms = nurlan.get("/api/permissions").json()
    assert {"key": "issues.edit", "scope": "project"} in perms


def test_custom_project_role(admin):
    _project(admin)
    _role(admin, "reporter", "project", ["project.read", "issues.create", "comments.create"])
    uid, rep = _local(admin, "rep")
    assert admin.post("/api/projects/OPS/members", json={"user_id": uid, "role": "reporter"}).status_code == 201
    r = rep.post("/api/projects/OPS/issues", json={"title": "bug report"})
    assert r.status_code == 201
    assert rep.patch("/api/issues/OPS-1", json={"title": "changed"}).status_code == 403
    assert rep.post("/api/issues/OPS-1/comments", json={"body": "more info"}).status_code == 201
    assert rep.get("/api/projects/OPS").json()["my_role"] == "reporter"
    # a role in use cannot be deleted
    role_id = next(r["id"] for r in admin.get("/api/roles").json() if r["key"] == "reporter")
    assert admin.delete(f"/api/roles/{role_id}").status_code == 409


def test_global_role_reads_all_projects(admin, nurlan):
    _project(nurlan)
    _role(admin, "auditor", "global", ["project.read"])
    uid, aud = _local(admin, "aud")
    assert aud.get("/api/projects/OPS").status_code == 404
    assert admin.put(f"/api/users/{uid}/roles", json={"roles": ["auditor"]}).status_code == 200
    assert [p["key"] for p in aud.get("/api/projects").json()] == ["OPS"]
    assert aud.post("/api/projects/OPS/issues", json={"title": "x"}).status_code == 403


def test_ldap_group_binding_gives_project_role(nurlan, akzhol):
    _project(akzhol, "SEC")
    guest_admin = make_client("admin", "admin-password-1")
    assert nurlan.get("/api/projects/SEC").status_code == 404
    r = guest_admin.post("/api/projects/SEC/group-bindings",
                         json={"group": USERS_GROUP.upper(), "role": "viewer", "provider": "ldap"})
    assert r.status_code == 201, r.text
    nurlan2 = make_client("nurlan", "nu-pass")  # groups are refreshed at sign-in
    assert nurlan2.get("/api/projects/SEC").json()["my_permissions"] == ["project.read"]
    assert nurlan2.post("/api/projects/SEC/issues", json={"title": "x"}).status_code == 403
    assert "SEC" in [p["key"] for p in nurlan2.get("/api/projects").json()]


def test_global_group_binding(admin):
    _role(admin, "pmo", "global", ["projects.create", "project.read", "issues.edit"])
    assert admin.post("/api/admin/group-bindings", json={"group": USERS_GROUP, "role": "pmo"}).status_code == 201
    nurlan = make_client("nurlan", "nu-pass")
    assert "issues.edit" in nurlan.get("/api/auth/me").json()["permissions"]


def test_default_role_controls_project_creation(admin, nurlan):
    user_role = next(r for r in admin.get("/api/roles").json() if r["key"] == "user")
    assert admin.patch(f"/api/roles/{user_role['id']}", json={"permissions": []}).status_code == 200
    assert nurlan.post("/api/projects", json={"key": "NOPE", "name": "x"}).status_code == 403


def test_project_admin_role_is_locked(admin):
    role = next(r for r in admin.get("/api/roles").json() if r["key"] == "admin")
    assert admin.patch(f"/api/roles/{role['id']}", json={"permissions": ["project.read"]}).status_code == 400
    assert admin.delete(f"/api/roles/{role['id']}").status_code == 400


def test_unknown_permission_rejected(admin):
    r = admin.post("/api/roles", json={"key": "bad", "name": "Bad", "scope": "project",
                                       "permissions": ["users.manage"]})
    assert r.status_code == 422


def test_user_manager_cannot_escalate(admin):
    _role(admin, "helpdesk", "global", ["users.manage"])
    _role(admin, "security", "global", ["roles.manage", "auth.manage"])
    uid, desk = _local(admin, "desk")
    admin.put(f"/api/users/{uid}/roles", json={"roles": ["helpdesk"]})
    other, _ = _local(admin, "other")
    assert desk.get("/api/users/all").status_code == 200
    assert desk.patch(f"/api/users/{other}", json={"is_admin": True}).status_code == 403
    assert desk.put(f"/api/users/{other}/roles", json={"roles": ["security"]}).status_code == 403
    assert desk.put(f"/api/users/{uid}/roles", json={"roles": ["helpdesk", "security"]}).status_code == 403
    assert desk.post("/api/users", json={"username": "boss", "display_name": "B", "password": "boss-password",
                                         "is_admin": True}).status_code == 403
    assert desk.get("/api/admin/auth-providers").status_code == 403


def test_member_manager_cannot_promote_to_admin(admin):
    _project(admin)
    _role(admin, "lead", "project", ["project.read", "members.manage", "issues.edit"])
    lead_id, lead = _local(admin, "lead")
    dev_id, _ = _local(admin, "dev")
    admin.post("/api/projects/OPS/members", json={"user_id": lead_id, "role": "lead"})
    assert lead.post("/api/projects/OPS/members", json={"user_id": dev_id, "role": "viewer"}).status_code == 201
    assert lead.patch(f"/api/projects/OPS/members/{dev_id}", json={"role": "admin"}).status_code == 403
    me = admin.get("/api/auth/me").json()["id"]
    assert lead.delete(f"/api/projects/OPS/members/{me}").status_code == 403  # cannot remove a project admin


def test_group_admin_counts_as_project_admin(akzhol, nurlan):
    _project(nurlan)
    me = nurlan.get("/api/auth/me").json()["id"]
    assert nurlan.patch(f"/api/projects/OPS/members/{me}", json={"role": "member"}).status_code == 400
    nurlan.post("/api/projects/OPS/group-bindings", json={"group": USERS_GROUP, "role": "admin"})
    assert nurlan.patch(f"/api/projects/OPS/members/{me}", json={"role": "member"}).status_code == 200
