from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import engine


def _project(client, key="OPS"):
    r = client.post("/api/projects", json={"key": key, "name": "Operations", "is_private": True})
    assert r.status_code == 201, r.text
    return r.json()


def _state(project, name):
    return next(s["id"] for s in project["states"] if s["name"] == name)


def _uid(client):
    return client.get("/api/auth/me").json()["id"]


def _issue(client, **kw):
    r = client.post("/api/projects/OPS/issues", json={"title": "t", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _sql(q, **kw):
    with engine().begin() as c:
        c.execute(text(q), kw)


TODAY = datetime.now(timezone.utc).date()


def test_cycle_progress_and_status(nurlan):
    p = _project(nurlan)
    cyc = nurlan.post("/api/projects/OPS/sprints", json={
        "name": "Cycle 1", "start_date": str(TODAY - timedelta(days=3)),
        "end_date": str(TODAY + timedelta(days=4))}).json()
    assert cyc["status"] == "active"
    a = _issue(nurlan, sprint_id=cyc["id"], estimate=3)
    b = _issue(nurlan, sprint_id=cyc["id"], estimate=5)
    c = _issue(nurlan, sprint_id=cyc["id"])
    _issue(nurlan)  # not in the cycle
    nurlan.patch(f"/api/issues/{a['key']}", json={"state_id": _state(p, "Done")})
    nurlan.patch(f"/api/issues/{c['key']}", json={"state_id": _state(p, "Cancelled")})
    nurlan.patch(f"/api/issues/{b['key']}", json={"state_id": _state(p, "In Progress")})

    [row] = nurlan.get("/api/projects/OPS/sprints").json()
    prog = row["progress"]
    assert (prog["total"], prog["scope"], prog["done"], prog["percent"]) == (3, 2, 1, 50)
    assert (prog["points_scope"], prog["points_done"], prog["points_percent"]) == (8, 3, 38)
    assert prog["by_category"]["in_progress"] == 1

    d = nurlan.get(f"/api/projects/OPS/sprints/{cyc['id']}/progress").json()
    assert d["start"] == str(TODAY - timedelta(days=3)) and len(d["burndown"]) == 8
    today = next(x for x in d["burndown"] if x["date"] == str(TODAY))
    assert (today["scope"], today["done"]) == (2, 1)
    assert d["burndown"][-1]["scope"] is None  # future days are empty
    # issues created today did not exist at the start of the cycle
    assert d["burndown"][0]["scope"] == 0
    assert d["people"] == []


def test_burndown_uses_history(nurlan):
    p = _project(nurlan)
    cyc = nurlan.post("/api/projects/OPS/sprints", json={
        "name": "C", "start_date": str(TODAY - timedelta(days=5)), "end_date": str(TODAY)}).json()
    a = _issue(nurlan, sprint_id=cyc["id"])
    b = _issue(nurlan, sprint_id=cyc["id"])
    nurlan.patch(f"/api/issues/{a['key']}", json={"state_id": _state(p, "Done")})
    _sql("UPDATE issues SET created_at = now() - interval '10 days'")
    _sql("UPDATE issues SET completed_at = now() - interval '2 days' WHERE number = 1")
    d = nurlan.get(f"/api/projects/OPS/sprints/{cyc['id']}/progress").json()
    assert [x["done"] for x in d["burndown"]] == [0, 0, 0, 1, 1, 1]
    assert {x["scope"] for x in d["burndown"]} == {2}
    assert b["key"] == "OPS-2"


def test_cycle_dates_cannot_overlap(nurlan):
    _project(nurlan)
    ok = nurlan.post("/api/projects/OPS/sprints", json={
        "name": "A", "start_date": "2026-11-02", "end_date": "2026-11-15"})
    assert ok.status_code == 201
    r = nurlan.post("/api/projects/OPS/sprints", json={
        "name": "B", "start_date": "2026-11-15", "end_date": "2026-11-29"})
    assert r.status_code == 409
    assert nurlan.post("/api/projects/OPS/sprints", json={
        "name": "B", "start_date": "2026-11-16", "end_date": "2026-11-29"}).status_code == 201
    assert nurlan.post("/api/projects/OPS/sprints", json={
        "name": "C", "start_date": "2026-12-05", "end_date": "2026-12-01"}).status_code == 422
    upcoming = nurlan.get("/api/projects/OPS/sprints").json()
    assert {c["status"] for c in upcoming} == {"upcoming"}


def test_complete_cycle_moves_unfinished(nurlan):
    p = _project(nurlan)
    c1 = nurlan.post("/api/projects/OPS/sprints", json={"name": "C1"}).json()
    c2 = nurlan.post("/api/projects/OPS/sprints", json={"name": "C2"}).json()
    done = _issue(nurlan, sprint_id=c1["id"])
    open_ = _issue(nurlan, sprint_id=c1["id"])
    nurlan.patch(f"/api/issues/{done['key']}", json={"state_id": _state(p, "Done")})
    assert nurlan.post(f"/api/projects/OPS/sprints/{c1['id']}/complete",
                       json={"move_to": c1["id"]}).status_code == 422
    r = nurlan.post(f"/api/projects/OPS/sprints/{c1['id']}/complete", json={"move_to": c2["id"]})
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["closed_at"]
    assert nurlan.get(f"/api/issues/{done['key']}").json()["sprint_id"] == c1["id"]
    assert nurlan.get(f"/api/issues/{open_['key']}").json()["sprint_id"] == c2["id"]
    act = nurlan.get(f"/api/issues/{open_['key']}/activity").json()
    assert any(a["field"] == "sprint" and a["new_value"] == "C2" for a in act)
    # a completed cycle takes no new issues
    r = nurlan.post("/api/projects/OPS/issues", json={"title": "late", "sprint_id": c1["id"]})
    assert r.status_code == 422


def test_modules_crud_and_issue_links(akzhol, nurlan):
    p = _project(akzhol)
    akzhol.post("/api/projects/OPS/members", json={"user_id": _uid(nurlan), "role": "viewer"})
    m = akzhol.post("/api/projects/OPS/modules", json={"name": "SSO", "lead_id": _uid(akzhol),
                                                       "target_date": "2026-12-01"})
    assert m.status_code == 201, m.text
    m = m.json()
    assert m["lead"]["username"] == "akzhol" and m["status"] == "planned"
    assert akzhol.post("/api/projects/OPS/modules", json={"name": "sso"}).status_code == 409
    other = akzhol.post("/api/projects/OPS/modules", json={"name": "Billing"}).json()

    a = _issue(akzhol, module_ids=[m["id"], other["id"]], estimate=2)
    b = _issue(akzhol, module_ids=[m["id"]])
    _issue(akzhol)
    assert sorted(a["module_ids"]) == sorted([m["id"], other["id"]])
    akzhol.patch(f"/api/issues/{b['key']}", json={"state_id": _state(p, "Done")})

    keys = [i["key"] for i in akzhol.get("/api/projects/OPS/issues", params={"module_id": m["id"]}).json()]
    assert sorted(keys) == [a["key"], b["key"]]
    assert [i["key"] for i in akzhol.get("/api/projects/OPS/issues", params={"module_id": "none"}).json()] == ["OPS-3"]

    rows = {x["name"]: x for x in akzhol.get("/api/projects/OPS/modules").json()}
    assert rows["SSO"]["progress"]["percent"] == 50 and rows["Billing"]["progress"]["total"] == 1

    r = akzhol.patch(f"/api/issues/{a['key']}", json={"module_ids": [other["id"]]})
    assert r.json()["module_ids"] == [other["id"]]
    act = akzhol.get(f"/api/issues/{a['key']}/activity").json()
    assert any(x["field"] == "modules" for x in act)

    # viewers read modules but cannot change them; leads must be project members
    assert nurlan.get("/api/projects/OPS/modules").status_code == 200
    assert nurlan.post("/api/projects/OPS/modules", json={"name": "X"}).status_code == 403
    assert akzhol.patch(f"/api/projects/OPS/modules/{m['id']}", json={"status": "in_progress"}).json()["status"] \
        == "in_progress"
    assert akzhol.patch(f"/api/projects/OPS/modules/{m['id']}", json={"status": "nope"}).status_code == 422

    d = akzhol.get(f"/api/projects/OPS/modules/{m['id']}/progress").json()
    assert d["progress"]["done"] == 1 and d["burndown"][-1]["date"] == "2026-12-01"

    # another project's module cannot be attached
    akzhol.post("/api/projects", json={"key": "WEB", "name": "Web"})
    wm = akzhol.post("/api/projects/WEB/modules", json={"name": "W"}).json()
    assert akzhol.patch(f"/api/issues/{a['key']}", json={"module_ids": [wm["id"]]}).status_code == 422

    assert akzhol.delete(f"/api/projects/OPS/modules/{m['id']}").status_code == 204
    assert akzhol.get(f"/api/issues/{b['key']}").json()["module_ids"] == []


def test_member_role_can_manage_modules(nurlan, akzhol):
    _project(akzhol)
    akzhol.post("/api/projects/OPS/members", json={"user_id": _uid(nurlan), "role": "member"})
    assert nurlan.post("/api/projects/OPS/modules", json={"name": "API"}).status_code == 201


def test_lead_must_be_member(nurlan, akzhol):
    _project(akzhol)
    r = akzhol.post("/api/projects/OPS/modules", json={"name": "X", "lead_id": _uid(nurlan)})
    assert r.status_code == 422


def test_project_analytics(nurlan):
    p = _project(nurlan)
    me = _uid(nurlan)
    a = _issue(nurlan, assignee_ids=[me], due_date=str(TODAY - timedelta(days=1)))
    b = _issue(nurlan, assignee_ids=[me])
    _issue(nurlan, priority="high")
    nurlan.patch(f"/api/issues/{b['key']}", json={"state_id": _state(p, "In Progress")})
    nurlan.patch(f"/api/issues/{b['key']}", json={"state_id": _state(p, "Done")})
    _sql("UPDATE issues SET created_at = now() - interval '4 days', started_at = now() - interval '2 days' "
         "WHERE number = 2")

    r = nurlan.get("/api/projects/OPS/analytics", params={"weeks": 4}).json()
    t = r["totals"]
    assert (t["total"], t["done"], t["overdue"], t["unassigned"]) == (3, 1, 1, 1)
    assert len(r["weekly"]) == 4 and r["weekly"][-1]["completed"] == 1
    assert sum(w["created"] for w in r["weekly"]) == 3
    assert r["lead_time"]["count"] == 1 and 3.9 < r["lead_time"]["median"] < 4.1
    assert 1.9 < r["cycle_time"]["median"] < 2.1
    assert r["people"][0]["name"] == "Nurlan Tasbolatov" and r["people"][0]["done"] == 1
    assert r["priority"]["high"] == 1
    flow = r["flow"]
    assert flow[-1]["date"] == str(TODAY) and flow[-1]["done"] == 1 and flow[-1]["backlog"] == 2
    # four days ago issue 2 existed but issues 1 and 3 did not
    four = next(x for x in flow if x["date"] == str(TODAY - timedelta(days=4)))
    assert sum(four[c] for c in ("backlog", "todo", "in_progress", "done", "cancelled")) == 1
    assert a["key"] == "OPS-1"


def test_analytics_needs_read_access(nurlan, akzhol):
    _project(akzhol)
    assert nurlan.get("/api/projects/OPS/analytics").status_code == 404
