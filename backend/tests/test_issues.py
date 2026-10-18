import concurrent.futures

from sqlalchemy import text

from app.db import engine


def _project(client, key="OPS", private=True):
    r = client.post("/api/projects", json={"key": key, "name": "Operations", "is_private": private})
    assert r.status_code == 201, r.text
    return r.json()


def _uid(client):
    return client.get("/api/auth/me").json()["id"]


def _state(project, name):
    return next(s["id"] for s in project["states"] if s["name"] == name)


def test_create_project_defaults(nurlan):
    p = _project(nurlan)
    assert [s["name"] for s in p["states"]] == ["Backlog", "To Do", "In Progress", "In Review", "Done", "Cancelled"]
    assert p["my_role"] == "admin"


def test_project_key_validation(nurlan):
    assert nurlan.post("/api/projects", json={"key": "1AB", "name": "x"}).status_code == 422
    assert nurlan.post("/api/projects", json={"key": "ops", "name": "x"}).json()["key"] == "OPS"
    assert nurlan.post("/api/projects", json={"key": "OPS", "name": "x"}).status_code == 409


def test_issue_keys_are_sequential(nurlan):
    _project(nurlan)
    keys = [nurlan.post("/api/projects/OPS/issues", json={"title": f"t{i}"}).json()["key"] for i in range(3)]
    assert keys == ["OPS-1", "OPS-2", "OPS-3"]


def test_issue_numbers_unique_under_concurrency(nurlan):
    _project(nurlan)
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda i: nurlan.post("/api/projects/OPS/issues", json={"title": f"c{i}"}), range(16)))
    assert all(r.status_code == 201 for r in res)
    assert sorted(r.json()["number"] for r in res) == list(range(1, 17))


def test_private_project_hidden_from_non_members(nurlan, akzhol):
    _project(nurlan)
    # akzhol is a global admin via LDAP group -> sees it; make a plain non-member instead
    from .conftest import make_client
    admin = make_client("admin", "admin-password-1")
    admin.post("/api/users", json={"username": "guest", "display_name": "Guest", "password": "guest-password"})
    guest = make_client("guest", "guest-password")
    assert guest.get("/api/projects/OPS").status_code == 404
    assert guest.get("/api/projects").json() == []
    nurlan.post("/api/projects/OPS/issues", json={"title": "secret"})
    assert guest.get("/api/issues/OPS-1").status_code == 404


def test_public_project_read_only_for_non_members(nurlan):
    _project(nurlan, private=False)
    from .conftest import make_client
    admin = make_client("admin", "admin-password-1")
    admin.post("/api/users", json={"username": "guest", "display_name": "Guest", "password": "guest-password"})
    guest = make_client("guest", "guest-password")
    assert guest.get("/api/projects/OPS").status_code == 200
    assert guest.post("/api/projects/OPS/issues", json={"title": "x"}).status_code == 403


def test_viewer_cannot_edit(nurlan, akzhol):
    _project(nurlan)
    from .conftest import make_client
    admin = make_client("admin", "admin-password-1")
    admin.post("/api/users", json={"username": "viewer", "display_name": "V", "password": "viewer-password"})
    viewer = make_client("viewer", "viewer-password")
    nurlan.post("/api/projects/OPS/members", json={"user_id": _uid(viewer), "role": "viewer"})
    nurlan.post("/api/projects/OPS/issues", json={"title": "x"})
    assert viewer.get("/api/issues/OPS-1").status_code == 200
    assert viewer.patch("/api/issues/OPS-1", json={"title": "y"}).status_code == 403


def test_assignees_must_be_members(nurlan, akzhol):
    _project(nurlan)
    ak = _uid(akzhol)
    r = nurlan.post("/api/projects/OPS/issues", json={"title": "x", "assignee_ids": [ak]})
    assert r.status_code == 422
    nurlan.post("/api/projects/OPS/members", json={"user_id": ak, "role": "member"})
    r = nurlan.post("/api/projects/OPS/issues", json={"title": "x", "assignee_ids": [ak]})
    assert r.status_code == 201
    assert [a["username"] for a in r.json()["assignees"]] == ["akzhol"]


def test_state_change_sets_times_and_activity(nurlan):
    p = _project(nurlan)
    nurlan.post("/api/projects/OPS/issues", json={"title": "x"})
    r = nurlan.patch("/api/issues/OPS-1", json={"state_id": _state(p, "In Progress")}).json()
    assert r["started_at"] and r["completed_at"] is None
    r = nurlan.patch("/api/issues/OPS-1", json={"state_id": _state(p, "Done")}).json()
    assert r["completed_at"]
    r = nurlan.patch("/api/issues/OPS-1", json={"state_id": _state(p, "To Do")}).json()
    assert r["completed_at"] is None  # reopened
    acts = nurlan.get("/api/issues/OPS-1/activity").json()
    assert [(a["field"], a["new_value"]) for a in acts] == [
        ("created", "x"), ("state", "In Progress"), ("state", "Done"), ("state", "To Do")]


def test_subtasks_and_cycle_protection(nurlan):
    _project(nurlan)
    nurlan.post("/api/projects/OPS/issues", json={"title": "epic", "type": "epic"})
    nurlan.post("/api/projects/OPS/issues", json={"title": "child", "parent_key": "OPS-1"})
    nurlan.post("/api/projects/OPS/issues", json={"title": "grandchild", "parent_key": "OPS-2"})
    epic = nurlan.get("/api/issues/OPS-1").json()
    assert epic["subtasks_total"] == 1 and epic["subtasks"][0]["key"] == "OPS-2"
    assert nurlan.patch("/api/issues/OPS-1", json={"parent_key": "OPS-3"}).status_code == 422
    assert nurlan.patch("/api/issues/OPS-1", json={"parent_key": "OPS-1"}).status_code == 422


def test_filters(nurlan):
    p = _project(nurlan)
    me = _uid(nurlan)
    nurlan.post("/api/projects/OPS/issues", json={"title": "Backup GP", "priority": "high", "assignee_ids": [me]})
    nurlan.post("/api/projects/OPS/issues", json={"title": "Upgrade GitLab", "state_id": _state(p, "Done")})
    get = lambda **q: [i["key"] for i in nurlan.get("/api/projects/OPS/issues", params=q).json()]  # noqa: E731
    assert get(q="backup") == ["OPS-1"]
    assert get(q="OPS-2") == ["OPS-2"]
    assert get(priority="high") == ["OPS-1"]
    assert get(assignee="me") == ["OPS-1"]
    assert get(assignee="none") == ["OPS-2"]
    assert get(open_only="true") == ["OPS-1"]
    assert [i["key"] for i in nurlan.get("/api/my/issues").json()] == ["OPS-1"]


def test_comments_permissions(nurlan, akzhol):
    _project(nurlan)
    ak = _uid(akzhol)
    nurlan.post("/api/projects/OPS/members", json={"user_id": ak, "role": "member"})
    nurlan.post("/api/projects/OPS/issues", json={"title": "x"})
    c = akzhol.post("/api/issues/OPS-1/comments", json={"body": "looking"}).json()
    from .conftest import make_client
    admin = make_client("admin", "admin-password-1")
    admin.post("/api/users", json={"username": "m2", "display_name": "M2", "password": "member-password"})
    m2 = make_client("m2", "member-password")
    nurlan.post("/api/projects/OPS/members", json={"user_id": _uid(m2), "role": "member"})
    assert m2.patch(f"/api/comments/{c['id']}", json={"body": "hijack"}).status_code == 403
    assert akzhol.patch(f"/api/comments/{c['id']}", json={"body": "done"}).json()["edited_at"]
    assert nurlan.delete(f"/api/comments/{c['id']}").status_code == 204  # project admin


def test_last_admin_cannot_leave(nurlan):
    _project(nurlan)
    r = nurlan.delete(f"/api/projects/OPS/members/{_uid(nurlan)}")
    assert r.status_code == 400


def test_delete_state_requires_move_target(nurlan):
    p = _project(nurlan)
    review = _state(p, "In Review")
    nurlan.post("/api/projects/OPS/issues", json={"title": "x", "state_id": review})
    assert nurlan.delete(f"/api/projects/OPS/states/{review}").status_code == 409
    todo = _state(p, "To Do")
    assert nurlan.delete(f"/api/projects/OPS/states/{review}", params={"move_to": todo}).status_code == 204
    assert nurlan.get("/api/issues/OPS-1").json()["state"]["name"] == "To Do"


def test_analytics_views(nurlan):
    p = _project(nurlan)
    nurlan.post("/api/projects/OPS/issues", json={"title": "x"})
    nurlan.patch("/api/issues/OPS-1", json={"state_id": _state(p, "In Progress")})
    nurlan.patch("/api/issues/OPS-1", json={"state_id": _state(p, "Done")})
    with engine().connect() as c:
        row = c.execute(text("select issue_key, is_open, lead_time_days from analytics.issues")).one()
        assert row.issue_key == "OPS-1" and row.is_open is False and row.lead_time_days is not None
        tr = c.execute(text("select from_category, to_category from analytics.state_transitions "
                            "order by changed_at")).all()
        assert [tuple(t) for t in tr] == [("backlog", "in_progress"), ("in_progress", "done")]
