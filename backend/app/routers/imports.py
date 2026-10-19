"""Starting and watching imports from Jira, Plane and Confluence (global permission imports.run)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import crypto, importers, rbac
from ..db import get_db
from ..deps import require
from ..models import DEFAULT_STATES, ImportJob, Project, ProjectMember, Role, State, User
from ..schemas import ImportIn, ImportJobOut, ImportSource, RemoteProject

router = APIRouter(prefix="/api/imports", tags=["imports"])
can_import = require(rbac.IMPORTS_RUN)


def _src(body: ImportSource) -> dict:
    return {"source": body.source, "url": body.url.strip().rstrip("/"), "workspace": body.workspace.strip()}


@router.post("/remote", response_model=list[RemoteProject])
def remote_projects(body: ImportSource, _: User = Depends(can_import)):
    """Checks the connection and lists projects (Jira, Plane) or spaces (Confluence) of the source."""
    try:
        return importers.list_remote({**_src(body), "username": body.username.strip(), "token": body.token})
    except importers.SourceError as e:
        raise HTTPException(502, str(e)) from e


@router.post("", response_model=ImportJobOut, status_code=202)
def start(body: ImportIn, db: Session = Depends(get_db), user: User = Depends(can_import)):
    key = body.target_key.upper()
    project = db.scalar(select(Project).where(Project.key == key))
    if project is None:
        # a new project, owned by whoever started the import
        role = db.scalar(select(Role).where(Role.key == "admin", Role.scope == "project"))
        project = Project(key=key, name=(body.target_name or body.remote).strip()[:200] or key, lead_id=user.id)
        project.states = [State(name=n, category=c, position=i) for i, (n, c) in enumerate(DEFAULT_STATES)]
        project.members = [ProjectMember(user_id=user.id, role_id=role.id)]
        db.add(project)
    elif rbac.PROJECT_MANAGE not in rbac.project_permissions(db, project, user):
        raise HTTPException(403, f"Importing into {key} requires {rbac.PROJECT_MANAGE} in that project")
    busy = db.scalar(select(ImportJob.id).where(ImportJob.project_key == key,
                                                ImportJob.status.in_(("queued", "running"))))
    if busy:
        raise HTTPException(409, f"An import into {key} is already running")
    job = ImportJob(source=body.source, project_key=key, created_by_id=user.id,
                    params={**_src(body), "remote": body.remote.strip(), "include_comments": body.include_comments},
                    secrets=crypto.encrypt({"username": body.username.strip(), "token": body.token}),
                    status="queued", stats={}, log="")
    db.add(job)
    db.commit()
    importers.launch(job.id)
    return get_job(job.id, db, user)


@router.get("", response_model=list[ImportJobOut])
def jobs(db: Session = Depends(get_db), _: User = Depends(can_import)):
    return db.scalars(select(ImportJob).options(selectinload(ImportJob.created_by))
                      .order_by(ImportJob.created_at.desc()).limit(50)).all()


@router.get("/{job_id}", response_model=ImportJobOut)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(can_import)):
    db.expire_all()
    job = db.get(ImportJob, job_id, options=[selectinload(ImportJob.created_by)])
    if not job:
        raise HTTPException(404, "Import not found")
    return job
