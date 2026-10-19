"""Project documentation: Markdown pages in a tree (also where Confluence spaces are imported to)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import rbac
from ..db import get_db
from ..deps import current_user, project_for
from ..models import Page, Project, User, utcnow
from ..schemas import PageBrief, PageIn, PageOut, PagePatch

router = APIRouter(prefix="/api/projects", tags=["docs"])


def _page(db: Session, project: Project, page_id: uuid.UUID) -> Page:
    pg = db.get(Page, page_id, options=[selectinload(Page.updated_by)])
    if not pg or pg.project_id != project.id:
        raise HTTPException(404, "Page not found")
    return pg


def _parent(db: Session, project: Project, parent_id: uuid.UUID | None, moving: Page | None = None) -> Page | None:
    if not parent_id:
        return None
    parent = _page(db, project, parent_id)
    node = parent
    while moving and node:  # a page cannot move under itself or its own subpage
        if node.id == moving.id:
            raise HTTPException(422, "A page cannot be moved under itself")
        node = db.get(Page, node.parent_id) if node.parent_id else None
    return parent


def _last(db: Session, project: Project, parent_id: uuid.UUID | None) -> float:
    cond = Page.parent_id.is_(None) if parent_id is None else Page.parent_id == parent_id
    return (db.scalar(select(func.max(Page.position)).where(Page.project_id == project.id, cond)) or 0) + 1024


@router.get("/{key}/pages", response_model=list[PageBrief])
def list_pages(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """All pages of the project without bodies, ordered for building the tree."""
    p, _ = project_for(db, key, user)
    return db.scalars(select(Page).where(Page.project_id == p.id).order_by(Page.position, Page.title)).all()


@router.post("/{key}/pages", response_model=PageOut, status_code=201)
def create_page(key: str, body: PageIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.DOCS_EDIT)
    _parent(db, p, body.parent_id)
    pg = Page(project_id=p.id, parent_id=body.parent_id, title=body.title.strip(), body=body.body,
              position=_last(db, p, body.parent_id), created_by_id=user.id, updated_by_id=user.id)
    db.add(pg)
    db.commit()
    return _page(db, p, pg.id)


@router.get("/{key}/pages/{page_id}", response_model=PageOut)
def get_page(key: str, page_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _ = project_for(db, key, user)
    return _page(db, p, page_id)


@router.patch("/{key}/pages/{page_id}", response_model=PageOut)
def patch_page(key: str, page_id: uuid.UUID, body: PagePatch, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    p, _ = project_for(db, key, user, rbac.DOCS_EDIT)
    pg = _page(db, p, page_id)
    data = body.model_dump(exclude_unset=True)
    if "parent_id" in data and data["parent_id"] != pg.parent_id:
        _parent(db, p, data["parent_id"], moving=pg)
        pg.parent_id = data["parent_id"]
        if "position" not in data:
            pg.position = _last(db, p, pg.parent_id)
    if data.get("title") is not None:
        pg.title = data["title"].strip()
    if data.get("body") is not None:
        pg.body = data["body"]
    if data.get("position") is not None:
        pg.position = data["position"]
    pg.updated_at, pg.updated_by_id = utcnow(), user.id
    db.commit()
    db.expire(pg)
    return _page(db, p, page_id)


@router.delete("/{key}/pages/{page_id}", status_code=204)
def delete_page(key: str, page_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Deletes the page with all its subpages."""
    p, _ = project_for(db, key, user, rbac.DOCS_EDIT)
    db.delete(_page(db, p, page_id))
    db.commit()
    return Response(status_code=204)
