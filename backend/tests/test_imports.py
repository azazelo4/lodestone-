"""Imports against fake Jira, Plane and Confluence APIs (httpx.MockTransport)."""
import base64
import json

import httpx
import pytest
from sqlalchemy import text

from app import importers
from app.db import engine
from app.importers import base
from app.importers.convert import adf_to_md, html_to_md, wiki_to_md


class Fake:
    """Routes by path; a value is JSON or a function(request) -> JSON. Records requests."""

    def __init__(self, routes: dict, status: int = 200):
        self.routes, self.status, self.calls = routes, status, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if self.status != 200:
            return httpx.Response(self.status, text="nope")
        h = self.routes.get(req.url.path)
        if h is None:
            return httpx.Response(404, json={"message": f"no route {req.url.path}"})
        return httpx.Response(200, json=h(req) if callable(h) else h)


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def use(routes, status=200):
        holder["fake"] = Fake(routes, status)
        return holder["fake"]
    monkeypatch.setattr(base, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda r: holder["fake"](r))))
    monkeypatch.setattr(importers, "launch", importers.run_job)  # run in the request thread
    return use


def _rows(q, **kw):
    with engine().connect() as c:
        return c.execute(text(q), kw).mappings().all()


def _start(client, **body):
    r = client.post("/api/imports", json={"username": "", "token": "secret-token", **body})
    assert r.status_code == 202, r.text
    job = client.get(f"/api/imports/{r.json()['id']}").json()
    return job


# ---------- Jira Server
SPRINT = ("com.atlassian.greenhopper.service.sprint.Sprint@1a[id=7,rapidViewId=1,state=CLOSED,name=Sprint 7,"
          "startDate=2026-09-01T09:00:00.000+05:00,endDate=2026-09-14T18:00:00.000+05:00,completeDate=<null>,"
          "sequence=7,goal=Ship SSO]")
GHOST = {"name": "ghost", "displayName": "Ghost User"}


def jira_issues(title="Auth epic"):
    return [
        {"id": "1001", "key": "OPS-1", "fields": {
            "summary": title, "description": "h2. Goal\n*SSO* for {{all}}", "issuetype": {"name": "Epic"},
            "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
            "priority": {"name": "Highest"}, "labels": ["backend"], "created": "2026-09-01T10:00:00.000+0500",
            "assignee": {"name": "akzhol.m", "emailAddress": "Akzhol@corp.local", "displayName": "Akzhol"},
            "reporter": GHOST, "components": [{"id": "1", "name": "Auth"}], "customfield_10010": [SPRINT],
            "customfield_10020": 5}},
        {"id": "1002", "key": "OPS-2", "fields": {
            "summary": "Login page", "description": None, "issuetype": {"name": "Story"},
            "status": {"name": "Done", "statusCategory": {"key": "done"}}, "priority": {"name": "Major"},
            "labels": ["backend", "sso"], "created": "2026-09-02T10:00:00.000+0500",
            "resolutiondate": "2026-09-10T12:00:00.000+0500", "assignee": {"name": "nurlan", "displayName": "N"},
            "customfield_10030": "OPS-1", "customfield_10010": [SPRINT]}},
        {"id": "1003", "key": "OPS-3", "fields": {
            "summary": "Old idea", "issuetype": {"name": "Sub-task"}, "parent": {"id": "1002", "key": "OPS-2"},
            "status": {"name": "Won't Do", "statusCategory": {"key": "done"}}, "priority": {"name": "Minor"},
            "created": "2026-09-03T10:00:00.000+0500"}},
    ]


def jira_server(title="Auth epic"):
    issues = jira_issues(title)

    def search(req):
        start = int(req.url.params["startAt"])
        assert req.url.params["jql"] == 'project = "OPS" ORDER BY created ASC'
        return {"issues": issues[start:start + 2], "total": len(issues), "startAt": start}
    return {
        "/rest/api/2/serverInfo": {"deploymentType": "Server", "version": "9.12.0"},
        "/rest/api/2/field": [
            {"id": "customfield_10010", "name": "Sprint", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            {"id": "customfield_10020", "name": "Story Points", "schema": {"custom": "x:float"}},
            {"id": "customfield_10030", "name": "Epic Link",
             "schema": {"custom": "com.pyxis.greenhopper.jira:gh-epic-link"}},
            {"id": "summary", "name": "Summary"}],
        "/rest/api/2/project": [{"id": "10000", "key": "OPS", "name": "Operations"}],
        "/rest/api/2/search": search,
        "/rest/api/2/issue/1001/comment": {"comments": [
            {"id": "1", "author": GHOST, "body": "Looks *good*", "created": "2026-09-05T10:00:00.000+0500"}],
            "total": 1},
        "/rest/api/2/issue/1002/comment": {"comments": [], "total": 0},
        "/rest/api/2/issue/1003/comment": {"comments": [], "total": 0},
    }


JIRA = {"source": "jira", "url": "https://jira.corp.local/", "username": "svc", "remote": "OPS",
        "target_key": "JIR", "target_name": "From Jira"}


def test_jira_server_import_and_rerun(admin, akzhol, nurlan, fake):
    f = fake(jira_server())
    # akzhol and nurlan sign in first, so they exist in Lodestone
    assert akzhol.get("/api/auth/me").status_code == nurlan.get("/api/auth/me").status_code == 200
    r = admin.post("/api/imports/remote", json={"source": "jira", "url": JIRA["url"], "username": "svc",
                                                "token": "secret-token"})
    assert r.json() == [{"id": "10000", "key": "OPS", "name": "Operations"}]
    assert f.calls[0].headers["authorization"] == "Basic " + base64.b64encode(b"svc:secret-token").decode()

    job = _start(admin, **JIRA)
    assert job["status"] == "done", job
    assert job["stats"]["issues"] == 3 and job["stats"]["comments"] == 1 and job["stats"]["cycles"] == 1
    assert job["stats"]["unmatched_users"] == ["Ghost User"]
    assert job["params"]["remote"] == "OPS" and "token" not in json.dumps(job)
    assert _rows("SELECT secrets FROM import_jobs")[0]["secrets"] is None

    p = admin.get("/api/projects/JIR").json()
    assert p["name"] == "From Jira"
    issues = {i["key"]: i for i in admin.get("/api/projects/JIR/issues").json()}
    assert sorted(issues) == ["JIR-1", "JIR-2", "JIR-3"]
    epic = admin.get("/api/issues/JIR-1").json()
    assert (epic["type"], epic["priority"], epic["state"]["name"], epic["estimate"]) == ("epic", "urgent",
                                                                                         "In Progress", 5)
    assert [a["username"] for a in epic["assignees"]] == ["akzhol"]  # matched by e-mail
    assert "## Goal" in epic["description"] and "**SSO** for `all`" in epic["description"]
    assert "*Jira: [OPS-1](https://jira.corp.local/browse/OPS-1) · Ghost User*" in epic["description"]
    assert epic["reporter"] is None and [x["name"] for x in epic["labels"]] == ["backend"]
    assert epic["created_at"].startswith("2026-09-01T05:00:00")

    story = admin.get("/api/issues/JIR-2").json()
    assert story["parent_key"] == "JIR-1" and story["state"]["category"] == "done"  # epic link
    assert story["completed_at"].startswith("2026-09-10T07:00") and story["priority"] == "medium"
    assert [a["username"] for a in story["assignees"]] == ["nurlan"]  # matched by login
    sub = admin.get("/api/issues/JIR-3").json()
    assert sub["parent_key"] == "JIR-2" and sub["state"]["name"] == "Won't Do"
    assert sub["state"]["category"] == "cancelled" and sub["type"] == "task"

    [cycle] = admin.get("/api/projects/JIR/sprints").json()
    assert (cycle["name"], cycle["status"], cycle["start_date"], cycle["goal"]) == ("Sprint 7", "completed",
                                                                                     "2026-09-01", "Ship SSO")
    assert cycle["progress"]["total"] == 2
    [mod] = admin.get("/api/projects/JIR/modules").json()
    assert mod["name"] == "Auth" and epic["module_ids"] == [mod["id"]]
    [c] = admin.get("/api/issues/JIR-1/comments").json()
    assert c["body"] == "**Ghost User:**\n\nLooks **good**"
    members = {m["user"]["username"]: m["role"]["key"] for m in admin.get("/api/projects/JIR/members").json()}
    assert members == {"admin": "admin", "akzhol": "member", "nurlan": "member"}
    # the completion date is in the history, so flow charts see when it was done
    act = admin.get("/api/issues/JIR-2/activity").json()
    assert any(a["field"] == "state" and a["new_value"] == "Done" for a in act)

    # running it again updates instead of duplicating
    fake(jira_server(title="Auth epic v2"))
    job = _start(admin, **JIRA)
    assert job["status"] == "done" and job["stats"]["issues_updated"] == 3 and "issues" not in job["stats"]
    assert len(admin.get("/api/projects/JIR/issues").json()) == 3
    assert admin.get("/api/issues/JIR-1").json()["title"] == "Auth epic v2"
    assert len(admin.get("/api/issues/JIR-1/comments").json()) == 1
    assert len(admin.get("/api/projects/JIR/sprints").json()) == 1


def test_jira_cloud_import(admin, fake):
    adf = {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Use "},
                                          {"type": "text", "text": "OIDC", "marks": [{"type": "strong"}]}]}]}

    def search(req):
        token = req.url.params.get("nextPageToken")
        if not token:
            return {"issues": [{"id": "1", "key": "WEB-1", "fields": {
                "summary": "First", "description": adf, "issuetype": {"name": "Bug"},
                "status": {"name": "To Do", "statusCategory": {"key": "new"}}, "priority": {"name": "High"},
                "created": "2026-10-01T10:00:00.000+0000"}}], "nextPageToken": "p2", "isLast": False}
        assert token == "p2"
        return {"issues": [{"id": "2", "key": "WEB-2", "fields": {
            "summary": "Second", "issuetype": {"name": "Task"}, "parent": {"id": "1"},
            "status": {"name": "Backlog", "statusCategory": {"key": "new"}},
            "customfield_10010": [{"id": 3, "name": "WEB Sprint 3", "state": "active", "startDate":
                                   "2026-10-10T00:00:00.000Z", "endDate": "2026-10-24T00:00:00.000Z"}]}}],
                "isLast": True}
    fake({"/rest/api/2/serverInfo": {"deploymentType": "Cloud"},
          "/rest/api/2/field": [{"id": "customfield_10010", "name": "Sprint",
                                 "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}}],
          "/rest/api/3/search/jql": search,
          "/rest/api/3/issue/1/comment": {"comments": [{"id": "9", "body": adf, "author": {
              "accountId": "x", "displayName": "Someone"}}], "total": 1},
          "/rest/api/3/issue/2/comment": {"comments": [], "total": 0}})
    job = _start(admin, source="jira", url="https://acme.atlassian.net", username="me@acme.io", remote="WEB",
                 target_key="WEB")
    assert job["status"] == "done", job
    one = admin.get("/api/issues/WEB-1").json()
    assert one["type"] == "bug" and one["priority"] == "high" and one["state"]["name"] == "To Do"
    assert one["description"].startswith("Use **OIDC**")
    two = admin.get("/api/issues/WEB-2").json()
    assert two["parent_key"] == "WEB-1" and two["state"]["category"] == "backlog"
    [cyc] = admin.get("/api/projects/WEB/sprints").json()
    assert cyc["name"] == "WEB Sprint 3" and cyc["end_date"] == "2026-10-24" and two["sprint_id"] == cyc["id"]
    assert admin.get("/api/issues/WEB-1/comments").json()[0]["body"] == "**Someone:**\n\nUse **OIDC**"


def test_failed_import_keeps_error_and_drops_secrets(admin, fake):
    fake({}, status=401)
    r = admin.post("/api/imports/remote", json={"source": "jira", "url": "https://jira.corp.local", "token": "t"})
    assert r.status_code == 502 and "access denied" in r.json()["detail"]
    job = _start(admin, **JIRA)
    assert job["status"] == "failed" and "access denied" in job["error"] and job["finished_at"]
    assert _rows("SELECT secrets FROM import_jobs")[0]["secrets"] is None
    assert [j["id"] for j in admin.get("/api/imports").json()] == [job["id"]]


def test_imports_need_permission(akzhol, nurlan, admin, fake):
    fake(jira_server())
    assert nurlan.get("/api/imports").status_code == 403
    assert nurlan.post("/api/imports", json={**JIRA, "token": "x"}).status_code == 403
    # an existing project needs project.manage there, even for someone allowed to import
    nurlan.post("/api/projects", json={"key": "NUR", "name": "Nurlan's"})
    assert admin.post("/api/imports", json={**JIRA, "target_key": "NUR", "token": "x"}).status_code == 202
    with engine().begin() as c:
        c.execute(text("UPDATE import_jobs SET status = 'running'"))
    assert admin.post("/api/imports", json={**JIRA, "target_key": "NUR", "token": "x"}).status_code == 409


def test_interrupted_jobs_fail_on_start(admin, fake):
    fake(jira_server())
    with engine().begin() as c:
        c.execute(text("INSERT INTO import_jobs (id, source, status, params, stats, log, created_at, updated_at, "
                       "secrets) VALUES (gen_random_uuid(), 'jira', 'running', '{}', '{}', '', now(), "
                       "now() - interval '1 hour', 'x'), (gen_random_uuid(), 'jira', 'running', '{}', '{}', '', "
                       "now(), now(), 'y')"))
    importers.fail_interrupted()
    rows = _rows("SELECT status, secrets FROM import_jobs ORDER BY status")
    assert [(r["status"], r["secrets"]) for r in rows] == [("failed", None), ("running", "y")]


# ---------- Plane
def plane_api():
    b = "/api/v1/workspaces/acme/projects/p1"

    def issues(req):
        if req.url.params.get("cursor") != "100:1:0":
            return {"results": [{"id": "i1", "sequence_id": 1, "name": "Hero", "description_html":
                                 "<p>Big <strong>hero</strong></p>", "state": "s3", "priority": "high",
                                 "assignees": ["u1"], "labels": ["l1"], "created_by": "u1",
                                 "created_at": "2026-10-01T10:00:00Z", "target_date": "2026-11-01"}],
                    "next_cursor": "100:1:0", "next_page_results": True}
        return {"results": [{"id": "i2", "sequence_id": 2, "name": "Footer", "state": "s4", "parent": "i1",
                             "priority": "none", "created_by": "u2", "completed_at": "2026-10-05T10:00:00Z"}],
                "next_page_results": False}
    return {
        "/api/v1/workspaces/acme/projects/": {"results": [{"id": "p1", "identifier": "WEB", "name": "Website"}]},
        b + "/": {"id": "p1", "identifier": "WEB", "name": "Website"},
        b + "/members/": [{"id": "u1", "email": "akzhol@corp.local", "display_name": "akzhol"},
                          {"id": "u2", "email": "anna@else.io", "display_name": "anna", "first_name": "Anna"}],
        b + "/states/": [{"id": "s1", "name": "Backlog", "group": "backlog", "sequence": 1},
                         {"id": "s2", "name": "Todo", "group": "unstarted", "sequence": 2},
                         {"id": "s3", "name": "QA", "group": "started", "sequence": 3},
                         {"id": "s4", "name": "Done", "group": "completed", "sequence": 4}],
        b + "/labels/": [{"id": "l1", "name": "ui", "color": "#ff0000"}],
        b + "/cycles/": [{"id": "c1", "name": "Cycle 1", "start_date": "2026-10-01T00:00:00Z",
                          "end_date": "2026-10-14T00:00:00Z"}],
        b + "/cycles/c1/cycle-issues/": [{"id": "i2"}],
        b + "/modules/": [{"id": "m1", "name": "Landing", "status": "in-progress", "lead": "u1",
                           "description_html": "<p>New site</p>"}],
        b + "/modules/m1/module-issues/": {"results": [{"issue": "i1"}]},
        b + "/issues/": issues,
        b + "/issues/i1/comments/": [{"id": "cm1", "comment_html": "<p>ok</p>", "actor": "u1"}],
        b + "/issues/i2/comments/": [],
    }


def test_plane_import(admin, akzhol, fake):
    akzhol.get("/api/auth/me")
    f = fake(plane_api())
    r = admin.post("/api/imports/remote", json={"source": "plane", "url": "https://plane.corp.local",
                                                "workspace": "acme", "token": "plane-key"})
    assert r.json() == [{"id": "p1", "key": "WEB", "name": "Website"}]
    assert f.calls[0].headers["x-api-key"] == "plane-key" and "authorization" not in f.calls[0].headers

    job = _start(admin, source="plane", url="https://plane.corp.local", workspace="acme", remote="p1",
                 target_key="SITE", token="plane-key")
    assert job["status"] == "done", job
    assert job["stats"]["unmatched_users"] == ["Anna"]
    states = {s["name"]: s["category"] for s in admin.get("/api/projects/SITE").json()["states"]}
    assert states["QA"] == "in_progress" and "Todo" not in states  # "Todo" is our "To Do"
    hero = admin.get("/api/issues/SITE-1").json()
    assert hero["description"].startswith("Big **hero**") and hero["state"]["name"] == "QA"
    assert hero["priority"] == "high" and hero["due_date"] == "2026-11-01"
    assert [a["username"] for a in hero["assignees"]] == ["akzhol"] and hero["reporter"]["username"] == "akzhol"
    assert [x["name"] for x in hero["labels"]] == ["ui"]
    footer = admin.get("/api/issues/SITE-2").json()
    assert footer["parent_key"] == "SITE-1" and footer["state"]["name"] == "Done"
    assert "· Anna*" in footer["description"]
    [cyc] = admin.get("/api/projects/SITE/sprints").json()
    assert cyc["status"] == "completed" and footer["sprint_id"] == cyc["id"] and cyc["end_date"] == "2026-10-14"
    [mod] = admin.get("/api/projects/SITE/modules").json()
    assert (mod["name"], mod["status"], mod["lead"]["username"], mod["description"]) == (
        "Landing", "in_progress", "akzhol", "New site")
    assert hero["module_ids"] == [mod["id"]]
    assert admin.get("/api/issues/SITE-1/comments").json()[0]["body"] == "ok"
    [lb] = admin.get("/api/projects/SITE/labels").json()
    assert lb["color"] == "#ff0000"


# ---------- Confluence
HOME = ('<h1>Welcome</h1><p>See <ac:link><ri:page ri:content-title="Install guide" />'
        '<ac:plain-text-link-body><![CDATA[how to install]]></ac:plain-text-link-body></ac:link> '
        'and <ac:link><ri:page ri:content-title="Missing page" /></ac:link>.</p>')
INSTALL = ('<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">bash</ac:parameter>'
           '<ac:plain-text-body><![CDATA[helm install lodestone ./chart]]></ac:plain-text-body>'
           '</ac:structured-macro><ac:image><ri:attachment ri:filename="arch.png" /></ac:image>')


def confluence_server():
    pages = [
        {"id": "10", "title": "Home", "ancestors": [], "body": {"storage": {"value": HOME}},
         "_links": {"webui": "/display/DOC/Home"}, "history": {"createdDate": "2025-01-01T10:00:00.000Z"}},
        {"id": "11", "title": "Setup", "ancestors": [{"id": "10"}], "body": {"storage": {"value": "<p>Steps</p>"}},
         "_links": {"webui": "/display/DOC/Setup"}},
        {"id": "12", "title": "Install guide", "ancestors": [{"id": "10"}, {"id": "11"}],
         "body": {"storage": {"value": INSTALL}}, "_links": {"webui": "/display/DOC/Install"}},
    ]

    def content(req):
        assert req.url.params["spaceKey"] == "DOC" and "body.storage" in req.url.params["expand"]
        start = int(req.url.params["start"])
        return {"results": pages[start:start + 2], "_links": {"next": "/x"} if start == 0 else {}}
    return {"/confluence/rest/api/space": {"results": [{"id": 1, "key": "DOC", "name": "Docs"}], "_links": {}},
            "/confluence/rest/api/content": content}


def test_confluence_server_into_existing_project(admin, fake):
    fake(confluence_server())
    admin.post("/api/projects", json={"key": "OPS", "name": "Ops"})
    url = "https://wiki.corp.local/confluence"
    assert admin.post("/api/imports/remote", json={"source": "confluence", "url": url, "username": "svc",
                                                   "token": "pw"}).json()[0]["key"] == "DOC"
    job = _start(admin, source="confluence", url=url, username="svc", remote="DOC", target_key="OPS")
    assert job["status"] == "done", job
    assert job["stats"]["pages"] == 3
    rows = {r["title"]: r for r in admin.get("/api/projects/OPS/pages").json()}
    assert rows["Home"]["parent_id"] is None and rows["Setup"]["parent_id"] == rows["Home"]["id"]
    assert rows["Install guide"]["parent_id"] == rows["Setup"]["id"]
    home = admin.get(f"/api/projects/OPS/pages/{rows['Home']['id']}").json()
    assert f"[how to install](/p/OPS/docs/{rows['Install guide']['id']})" in home["body"]
    assert "and Missing page." in home["body"]  # a link to a page outside the space keeps only its text
    assert "*Confluence: [Home](https://wiki.corp.local/confluence/display/DOC/Home)*" in home["body"]
    install = admin.get(f"/api/projects/OPS/pages/{rows['Install guide']['id']}").json()
    assert "```bash\nhelm install lodestone ./chart\n```" in install["body"] and "*[image: arch.png]*" in install[
        "body"]

    job = _start(admin, source="confluence", url=url, username="svc", remote="DOC", target_key="OPS")
    assert job["stats"] == {"pages_updated": 3, "unmatched_users": []}
    assert len(admin.get("/api/projects/OPS/pages").json()) == 3


def test_confluence_cloud(admin, fake):
    def pages(req):
        assert req.url.params["body-format"] == "storage"
        if req.url.params.get("cursor") == "abc":
            return {"results": [{"id": "2", "title": "Child", "parentId": "1", "parentType": "page", "position": 0,
                                 "body": {"storage": {"value": "<ul><li>a</li><li>b</li></ul>"}}}], "_links": {}}
        return {"results": [{"id": "1", "title": "Root", "parentId": "77", "parentType": "folder",
                             "body": {"storage": {"value": "<p>root</p>"}}, "_links": {"webui": "/spaces/D/pages/1"}}],
                "_links": {"next": "/wiki/api/v2/spaces/99/pages?cursor=abc&body-format=storage"}}
    fake({"/wiki/api/v2/spaces": {"results": [{"id": "99", "key": "D", "name": "D"}]},
          "/wiki/api/v2/spaces/99/pages": pages})
    job = _start(admin, source="confluence", url="https://acme.atlassian.net/wiki", username="me@acme.io",
                 remote="D", target_key="DOCS")
    assert job["status"] == "done", job
    rows = {r["title"]: r for r in admin.get("/api/projects/DOCS/pages").json()}
    assert rows["Root"]["parent_id"] is None and rows["Child"]["parent_id"] == rows["Root"]["id"]
    child = admin.get(f"/api/projects/DOCS/pages/{rows['Child']['id']}").json()
    assert child["body"].startswith("- a\n- b")
    root = admin.get(f"/api/projects/DOCS/pages/{rows['Root']['id']}").json()
    assert "(https://acme.atlassian.net/wiki/spaces/D/pages/1)" in root["body"]


# ---------- converters
def test_converters():
    assert wiki_to_md("h1. T\n* a\n** b\n# one\n[Docs|https://x.io] [~ivan] -old-") == (
        "# T\n\n- a\n   - b\n1. one\n[Docs](https://x.io) @ivan ~~old~~")
    assert wiki_to_md("||A||B||\n|1|2|") == "| A | B |\n| --- | --- |\n| 1 | 2 |"
    assert wiki_to_md("{noformat}\na *b*\n{noformat}") == "```\na *b*\n```"
    assert adf_to_md({"type": "doc", "content": [
        {"type": "orderedList", "content": [{"type": "listItem", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [{"type": "code"}]}]}]}]},
        {"type": "taskList", "content": [{"type": "taskItem", "attrs": {"state": "DONE"},
                                          "content": [{"type": "text", "text": "ok"}]}]}]}) == "1. `x`\n\n- [x] ok"
    assert html_to_md('<table><tr><td>a|b</td></tr></table>') == "|  |\n| --- |\n| a\\|b |"
    assert html_to_md('<ac:structured-macro ac:name="warning"><ac:parameter ac:name="title">Careful'
                      '</ac:parameter><ac:rich-text-body><p>hot</p></ac:rich-text-body></ac:structured-macro>') == (
        "> **Careful**\n>\n> hot")
    assert html_to_md('<p>a<script>x</script></p>') == "ax"  # text only; Markdown is sanitized when shown
