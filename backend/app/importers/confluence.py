"""Confluence Cloud (REST API v2) and Confluence Server / Data Center (REST API /rest/api/content).

A space becomes the documentation of a project: pages keep their hierarchy and order, the storage format is
converted to Markdown, and links between pages of the space point to the imported pages. Attachments and images
are not downloaded (a placeholder with the file name stays in the text); blog posts and comments are skipped.
"""
from urllib.parse import urlparse

from sqlalchemy import func, select

from ..models import Page, utcnow
from .base import PAGE_SIZE, Context, Remote, SourceError, parse_dt
from .convert import html_to_md, resolve_page_links


def _cloud(url: str) -> bool:
    return (urlparse(url).hostname or "").endswith(".atlassian.net")


def remote(src: dict) -> Remote:
    url = src["url"].rstrip("/")
    if _cloud(url) and url.endswith("/wiki"):
        url = url[:-5]
    return Remote(url, src.get("username", ""), src.get("token", ""))


def _cursor_pages(r: Remote, path: str, params: dict):
    data = r.get(path, params)
    while True:
        yield from data.get("results", [])
        nxt = (data.get("_links") or {}).get("next")
        if not nxt:
            return
        data = r.get(nxt)


def _offset_pages(r: Remote, path: str, params: dict):
    start = 0
    while True:
        data = r.get(path, {**params, "start": start, "limit": PAGE_SIZE})
        page = data.get("results", [])
        yield from page
        start += len(page)
        if not page or not (data.get("_links") or {}).get("next"):
            return


def list_projects(src: dict) -> list[dict]:
    r = remote(src)
    try:
        if _cloud(r.base):
            rows = _cursor_pages(r, "/wiki/api/v2/spaces", {"limit": 250})
        else:
            rows = _offset_pages(r, "/rest/api/space", {})
        return [{"id": str(s.get("id")), "key": s["key"], "name": s.get("name", s["key"])} for s in rows]
    finally:
        r.close()


class ConfluenceImport:
    name = "Confluence"

    def __init__(self, ctx: Context, src: dict, params: dict):
        self.ctx, self.src, self.params = ctx, src, params
        self.r = remote(src)
        self.space = params["remote"]

    def fetch(self) -> list[dict]:
        """[{id, title, parent, position, body (storage XHTML), url, created}] of the space."""
        r, out = self.r, []
        if _cloud(r.base):
            found = r.get("/wiki/api/v2/spaces", {"keys": self.space}).get("results", [])
            if not found:
                raise SourceError(f"Space {self.space} not found")
            for p in _cursor_pages(r, f"/wiki/api/v2/spaces/{found[0]['id']}/pages",
                                   {"body-format": "storage", "limit": PAGE_SIZE, "status": "current"}):
                out.append({"id": str(p["id"]), "title": p.get("title") or "", "position": p.get("position") or 0,
                            "parent": str(p["parentId"]) if p.get("parentId") and p.get("parentType", "page") == "page"
                            else None, "body": ((p.get("body") or {}).get("storage") or {}).get("value", ""),
                            "url": r.base + "/wiki" + ((p.get("_links") or {}).get("webui") or ""),
                            "created": p.get("createdAt")})
        else:
            for i, p in enumerate(_offset_pages(r, "/rest/api/content", {
                    "spaceKey": self.space, "type": "page", "status": "current",
                    "expand": "body.storage,ancestors,history,extensions.position"})):
                anc = p.get("ancestors") or []
                pos = (p.get("extensions") or {}).get("position")
                out.append({"id": str(p["id"]), "title": p.get("title") or "",
                            "position": pos if isinstance(pos, (int, float)) and pos >= 0 else i,
                            "parent": str(anc[-1]["id"]) if anc else None,
                            "body": ((p.get("body") or {}).get("storage") or {}).get("value", ""),
                            "url": r.base + ((p.get("_links") or {}).get("webui") or ""),
                            "created": (p.get("history") or {}).get("createdDate")})
        return out

    def run(self):
        ctx, db = self.ctx, self.ctx.db
        rows = self.fetch()
        ctx.say(f"Confluence space {self.space}: {len(rows)} pages")
        known = {p["id"] for p in rows}
        children: dict[str | None, list[dict]] = {}
        for p in rows:
            children.setdefault(p["parent"] if p["parent"] in known else None, []).append(p)
        actor = ctx.actor.id if ctx.actor else None
        by_title: dict[str, Page] = {}
        order: list[tuple[Page, dict]] = []

        def last(parent: Page | None) -> float:
            cond = Page.parent_id.is_(None) if parent is None else Page.parent_id == parent.id
            return db.scalar(select(func.max(Page.position)).where(Page.project_id == ctx.project.id, cond)) or 0

        def put(parent: Page | None, items: list[dict]):
            for p in sorted(items, key=lambda x: (x["position"], x["title"])):
                pg = ctx.linked(Page, "page", p["id"])
                if pg is None or pg.parent_id != (parent.id if parent else None):
                    # new pages go after what the project already has; moved ones to the end of their new parent
                    position = last(parent) + 1024
                else:
                    position = pg.position
                if pg is None:
                    pg = Page(project_id=ctx.project.id, created_by_id=actor,
                              created_at=parse_dt(p["created"]) or utcnow())
                    db.add(pg)
                    ctx.count("pages")
                else:
                    ctx.count("pages_updated")
                pg.parent_id = parent.id if parent else None
                pg.title, pg.position = (p["title"] or "(untitled)")[:300], position
                pg.updated_at, pg.updated_by_id = utcnow(), actor
                db.flush()
                ctx.remember("page", p["id"], pg.id)
                by_title.setdefault(pg.title, pg)
                order.append((pg, p))
                put(pg, children.get(p["id"], []))

        put(None, children.get(None, []))
        ctx.checkpoint()
        key = ctx.project.key
        existing = {t: i for t, i in db.execute(select(Page.title, Page.id).where(Page.project_id == ctx.project.id))}

        def url_of(title: str):
            pid = by_title[title].id if title in by_title else existing.get(title)
            return f"/p/{key}/docs/{pid}" if pid else None

        for pg, p in order:
            md = resolve_page_links(html_to_md(p["body"]), url_of)
            pg.body = md + f"\n\n---\n*Confluence: [{p['title']}]({p['url']})*"
        ctx.say(f"{len(order)} pages imported")

    def close(self):
        self.r.close()
