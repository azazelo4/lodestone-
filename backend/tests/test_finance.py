from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.db import engine


def _project(client, key="OPS"):
    r = client.post("/api/projects", json={"key": key, "name": "Operations", "is_private": True})
    assert r.status_code == 201, r.text
    return r.json()


def _uid(client):
    return client.get("/api/auth/me").json()["id"]


def _issue(client, key="OPS", **extra):
    r = client.post(f"/api/projects/{key}/issues", json={"title": "Work", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _today():
    return datetime.now(timezone.utc).date()


def test_rates_and_costs(akzhol, nurlan):
    _project(akzhol)
    nid = _uid(nurlan)
    akzhol.post("/api/projects/OPS/members", json={"user_id": nid, "role": "member"})
    issue = _issue(akzhol)["key"]
    assert akzhol.put("/api/projects/OPS/finance/settings", json={
        "currency": "KZT", "budget": "100000", "default_rate": "10"}).json()["currency"] == "KZT"
    akzhol.post("/api/projects/OPS/finance/rates", json={"user_id": nid, "rate": "20", "valid_from": "2026-01-01"})
    akzhol.post("/api/projects/OPS/finance/rates", json={"user_id": nid, "rate": "30", "valid_from": "2026-06-01"})
    # the same date replaces the rate instead of adding a second one
    r = akzhol.post("/api/projects/OPS/finance/rates", json={"user_id": nid, "rate": "25", "valid_from": "2026-01-01"})
    assert r.status_code == 201 and r.json()["rate"] == 25
    assert [x["rate"] for x in akzhol.get("/api/projects/OPS/finance/rates").json()] == [25, 30]

    for day, minutes in (("2025-12-15", 60), ("2026-03-01", 120), ("2026-07-01", 90)):
        r = nurlan.post(f"/api/issues/{issue}/worklogs", json={"minutes": minutes, "work_date": day, "note": "x"})
        assert r.status_code == 201, r.text
        assert r.json()["cost"] is None  # members see hours, not money
    akzhol.post(f"/api/issues/{issue}/worklogs", json={"minutes": 30, "work_date": "2026-07-02"})

    logs = akzhol.get(f"/api/issues/{issue}/worklogs").json()
    assert logs["total_minutes"] == 300 and logs["currency"] == "KZT"
    assert nurlan.get(f"/api/issues/{issue}/worklogs").json()["currency"] is None
    # before the first rate: the first rate; then by date; no personal rate: project default
    assert [(w["work_date"], w["cost"]) for w in logs["items"]] == [
        ("2026-07-02", 5.0), ("2026-07-01", 45.0), ("2026-03-01", 50.0), ("2025-12-15", 25.0)]

    s = akzhol.get("/api/projects/OPS/finance").json()
    assert s["totals"]["hours"] == 5 and s["totals"]["labor"] == 125 and s["totals"]["spent"] == 125
    assert s["totals"]["remaining"] == 99875 and s["totals"]["percent"] == 0.1
    assert [(p["name"], p["hours"], p["cost"], p["rate"]) for p in s["people"]] == [
        ("Nurlan Tasbolatov", 4.5, 120.0, 30.0), ("Akzhol Muratov", 0.5, 5.0, 10.0)]
    assert s["issues"][0]["key"] == issue and s["issues"][0]["cost"] == 125

    # BI view uses the same rule
    with engine().connect() as c:
        view = c.execute(text("SELECT sum(cost), sum(hours) FROM analytics.worklogs WHERE project_key = 'OPS'")).one()
        budget = c.execute(text("SELECT labor_cost, hours_logged FROM analytics.project_budgets")).one()
    assert float(view[0]) == 125 and float(view[1]) == 5 and float(budget[0]) == 125


def test_unrated_hours_and_no_default(akzhol):
    _project(akzhol)
    issue = _issue(akzhol)["key"]
    akzhol.post(f"/api/issues/{issue}/worklogs", json={"minutes": 90})
    s = akzhol.get("/api/projects/OPS/finance").json()
    assert s["totals"]["unrated_hours"] == 1.5 and s["totals"]["labor"] == 0
    assert s["settings"]["currency"] == "USD" and s["totals"]["remaining"] is None and s["totals"]["percent"] is None


def test_permissions(akzhol, nurlan):
    _project(akzhol)
    nid = _uid(nurlan)
    issue = _issue(akzhol)["key"]
    akzhol.post("/api/projects/OPS/members", json={"user_id": nid, "role": "viewer"})
    assert nurlan.get(f"/api/issues/{issue}/worklogs").status_code == 200  # hours are visible to readers
    assert nurlan.post(f"/api/issues/{issue}/worklogs", json={"minutes": 30}).status_code == 403
    akzhol.post("/api/projects/OPS/members", json={"user_id": nid, "role": "member"})
    mine = nurlan.post(f"/api/issues/{issue}/worklogs", json={"minutes": 30}).json()
    theirs = akzhol.post(f"/api/issues/{issue}/worklogs", json={"minutes": 45}).json()

    for path in ("finance", "finance/rates", "finance/expenses"):
        assert nurlan.get(f"/api/projects/OPS/{path}").status_code == 403
    assert nurlan.put("/api/projects/OPS/finance/settings", json={"budget": 1}).status_code == 403
    assert nurlan.post("/api/projects/OPS/finance/expenses", json={"spent_on": "2026-01-01",
                                                                    "amount": 1}).status_code == 403
    assert nurlan.post(f"/api/issues/{issue}/worklogs", json={"minutes": 5, "user_id": _uid(akzhol)}).status_code == 403
    assert nurlan.patch(f"/api/worklogs/{theirs['id']}", json={"minutes": 5}).status_code == 403
    assert nurlan.delete(f"/api/worklogs/{theirs['id']}").status_code == 403
    assert nurlan.patch(f"/api/worklogs/{mine['id']}", json={"minutes": 60}).json()["minutes"] == 60
    # a finance manager fixes anyone's time and logs it for others
    assert akzhol.patch(f"/api/worklogs/{mine['id']}", json={"note": "fixed"}).json()["note"] == "fixed"
    r = akzhol.post(f"/api/issues/{issue}/worklogs", json={"minutes": 15, "user_id": nid})
    assert r.status_code == 201 and r.json()["user"]["id"] == nid
    assert nurlan.delete(f"/api/worklogs/{mine['id']}").status_code == 204

    # a custom role can open finances without managing them
    role = akzhol.post("/api/roles", json={"key": "pm", "name": "PM", "scope": "project",
                                           "permissions": ["project.read", "finance.view"]})
    assert role.status_code == 201, role.text
    akzhol.post("/api/projects/OPS/members", json={"user_id": nid, "role": "pm"})
    assert nurlan.get("/api/projects/OPS/finance").status_code == 200
    assert nurlan.get(f"/api/issues/{issue}/worklogs").json()["items"][0]["cost"] == 0
    assert nurlan.put("/api/projects/OPS/finance/settings", json={"budget": 1}).status_code == 403

    _project(akzhol, "WEB")
    assert akzhol.delete(f"/api/projects/WEB/finance/rates/{theirs['id']}").status_code == 404


def test_validation(akzhol):
    _project(akzhol)
    issue = _issue(akzhol)["key"]
    tomorrow = (_today() + timedelta(days=1)).isoformat()
    assert akzhol.post(f"/api/issues/{issue}/worklogs", json={"minutes": 30, "work_date": tomorrow}).status_code == 422
    assert akzhol.post(f"/api/issues/{issue}/worklogs", json={"minutes": 0}).status_code == 422
    assert akzhol.post(f"/api/issues/{issue}/worklogs", json={"minutes": 1441}).status_code == 422
    assert akzhol.put("/api/projects/OPS/finance/settings", json={"currency": "tenge"}).status_code == 422
    assert akzhol.put("/api/projects/OPS/finance/settings", json={"budget": -1}).status_code == 422
    assert akzhol.put("/api/projects/OPS/finance/settings", json={
        "start_date": "2026-02-01", "end_date": "2026-01-01"}).status_code == 422
    _project(akzhol, "WEB")
    other = _issue(akzhol, "WEB")["key"]
    assert akzhol.post("/api/projects/OPS/finance/expenses", json={
        "spent_on": "2026-01-01", "amount": 5, "issue_key": other}).status_code == 422


def test_expenses_plan_and_breakdowns(akzhol):
    _project(akzhol)
    today = _today()
    start, end = today - timedelta(days=9), today + timedelta(days=10)  # 20 days, 10 of them passed
    akzhol.put("/api/projects/OPS/finance/settings", json={
        "budget": "2000", "budget_hours": "100", "default_rate": "100", "start_date": start.isoformat(),
        "end_date": end.isoformat()})
    cycle = akzhol.post("/api/projects/OPS/sprints", json={"name": "C1"}).json()
    m1 = akzhol.post("/api/projects/OPS/modules", json={"name": "API"}).json()
    m2 = akzhol.post("/api/projects/OPS/modules", json={"name": "UI"}).json()
    both = _issue(akzhol, sprint_id=cycle["id"], module_ids=[m1["id"], m2["id"]], estimate=3)["key"]
    akzhol.post(f"/api/issues/{both}/worklogs", json={"minutes": 300, "work_date": today.isoformat()})

    e = akzhol.post("/api/projects/OPS/finance/expenses", json={
        "spent_on": today.isoformat(), "amount": "250.50", "category": "licenses", "description": "IDE",
        "issue_key": both, "module_id": m1["id"]})
    assert e.status_code == 201, e.text
    assert e.json()["issue_key"] == both and e.json()["module"]["name"] == "API"
    e2 = akzhol.post("/api/projects/OPS/finance/expenses", json={"spent_on": start.isoformat(), "amount": 49.5}).json()
    assert akzhol.patch(f"/api/projects/OPS/finance/expenses/{e2['id']}", json={
        "category": "travel", "issue_key": None}).json()["category"] == "travel"
    assert akzhol.patch(f"/api/projects/OPS/finance/expenses/{e2['id']}", json={"amount": None}).status_code == 422
    assert [x["amount"] for x in akzhol.get("/api/projects/OPS/finance/expenses").json()] == [250.5, 49.5]

    s = akzhol.get("/api/projects/OPS/finance").json()
    t = s["totals"]
    assert (t["labor"], t["expenses"], t["spent"], t["remaining"]) == (500, 300, 800, 1200)
    assert t["percent"] == 40 and t["hours_percent"] == 5
    assert t["forecast"] == 1600  # 800 in 10 of 20 days
    assert {b["name"]: b["cost"] for b in s["modules"]} == {"API": 500, "UI": 500}  # modules overlap
    assert s["cycles"] == [{"id": cycle["id"], "name": "C1", "hours": 5, "cost": 500, "rate": None,
                            "estimate": None, "key": None}]
    assert s["issues"][0]["estimate"] == 3
    assert [(c["name"], c["cost"]) for c in s["categories"]] == [("licenses", 250.5), ("travel", 49.5)]

    months = s["months"]
    assert months[0]["month"] == date(start.year, start.month, 1).isoformat()
    assert months[-1]["month"] == date(end.year, end.month, 1).isoformat()
    current = next(m for m in months if m["month"] == date(today.year, today.month, 1).isoformat())
    assert current["actual"] == 800 or start.month != today.month
    assert months[-1]["plan"] == 2000 and months[-1]["actual"] in (800, None)

    assert akzhol.delete(f"/api/projects/OPS/finance/expenses/{e2['id']}").status_code == 204
    assert akzhol.get("/api/projects/OPS/finance").json()["totals"]["expenses"] == 250.5


def test_project_and_personal_time(akzhol, nurlan):
    _project(akzhol)
    akzhol.post("/api/projects/OPS/members", json={"user_id": _uid(nurlan), "role": "member"})
    a, b = _issue(akzhol)["key"], _issue(akzhol)["key"]
    nurlan.post(f"/api/issues/{a}/worklogs", json={"minutes": 60, "work_date": "2026-03-01"})
    nurlan.post(f"/api/issues/{b}/worklogs", json={"minutes": 30, "work_date": "2026-03-05"})
    akzhol.post(f"/api/issues/{b}/worklogs", json={"minutes": 15, "work_date": "2026-03-05"})
    rows = nurlan.get("/api/projects/OPS/worklogs", params={"start": "2026-03-02"}).json()
    assert [(r["issue_key"], r["minutes"]) for r in rows] == [(b, 15), (b, 30)]
    assert all(r["cost"] is None for r in rows)
    mine = nurlan.get("/api/my/worklogs").json()
    assert [(r["issue_key"], r["minutes"]) for r in mine] == [(b, 30), (a, 60)]
    # deleting an issue removes its time with it
    akzhol.delete(f"/api/issues/{a}")
    assert len(nurlan.get("/api/my/worklogs").json()) == 1
