def _project(client, key="OPS"):
    r = client.post("/api/projects", json={"key": key, "name": key})
    assert r.status_code == 201, r.text


def _uid(client):
    return client.get("/api/auth/me").json()["id"]


def test_pages_tree_crud(akzhol):
    _project(akzhol)
    home = akzhol.post("/api/projects/OPS/pages", json={"title": "Home", "body": "# Hi"}).json()
    setup = akzhol.post("/api/projects/OPS/pages", json={"title": "Setup", "parent_id": home["id"]}).json()
    deep = akzhol.post("/api/projects/OPS/pages", json={"title": "LDAP", "parent_id": setup["id"]}).json()
    other = akzhol.post("/api/projects/OPS/pages", json={"title": "FAQ"}).json()
    assert home["updated_by"]["username"] == "akzhol" and home["body"] == "# Hi"

    rows = akzhol.get("/api/projects/OPS/pages").json()
    assert [r["title"] for r in rows if r["parent_id"] is None] == ["Home", "FAQ"]
    assert "body" not in rows[0]

    r = akzhol.patch(f"/api/projects/OPS/pages/{setup['id']}", json={"title": "Install", "body": "steps"})
    assert r.json()["title"] == "Install" and r.json()["body"] == "steps"
    # no cycles in the tree
    assert akzhol.patch(f"/api/projects/OPS/pages/{home['id']}", json={"parent_id": deep["id"]}).status_code == 422
    assert akzhol.patch(f"/api/projects/OPS/pages/{setup['id']}", json={"parent_id": other["id"]}).json()[
        "parent_id"] == other["id"]
    assert akzhol.patch(f"/api/projects/OPS/pages/{setup['id']}", json={"parent_id": None}).json()["parent_id"] is None

    assert akzhol.delete(f"/api/projects/OPS/pages/{setup['id']}").status_code == 204
    assert akzhol.get(f"/api/projects/OPS/pages/{deep['id']}").status_code == 404  # subpages go too
    assert {r["title"] for r in akzhol.get("/api/projects/OPS/pages").json()} == {"Home", "FAQ"}


def test_pages_permissions(akzhol, nurlan):
    _project(akzhol)
    page = akzhol.post("/api/projects/OPS/pages", json={"title": "Home"}).json()
    assert nurlan.get(f"/api/projects/OPS/pages/{page['id']}").status_code == 404  # private project
    akzhol.post("/api/projects/OPS/members", json={"user_id": _uid(nurlan), "role": "viewer"})
    assert nurlan.get(f"/api/projects/OPS/pages/{page['id']}").status_code == 200
    assert nurlan.post("/api/projects/OPS/pages", json={"title": "X"}).status_code == 403
    akzhol.post("/api/projects/OPS/members", json={"user_id": _uid(nurlan), "role": "member"})
    assert nurlan.post("/api/projects/OPS/pages", json={"title": "X"}).status_code == 201

    _project(akzhol, "WEB")
    assert akzhol.get(f"/api/projects/WEB/pages/{page['id']}").status_code == 404
    assert akzhol.post("/api/projects/WEB/pages", json={"title": "Y", "parent_id": page["id"]}).status_code == 404
