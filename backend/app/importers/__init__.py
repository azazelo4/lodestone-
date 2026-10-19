"""Import from Jira, Plane and Confluence. A job runs in a background thread of the web process; its credentials
are stored encrypted only until it ends. Running the same import again updates the objects it created before."""
import logging
import threading
import traceback
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import update

from .. import crypto
from ..db import session_factory
from ..models import ImportJob, Project, utcnow
from . import confluence, jira, plane
from .base import Context, SourceError

log = logging.getLogger("lodestone.import")
STALE = timedelta(minutes=15)

SOURCES = {"jira": (jira.list_projects, jira.JiraImport), "plane": (plane.list_projects, plane.PlaneImport),
           "confluence": (confluence.list_projects, confluence.ConfluenceImport)}

__all__ = ["SourceError", "list_remote", "launch", "run_job", "fail_interrupted", "source_id"]


def source_id(src: dict) -> str:
    u = urlparse(src["url"].rstrip("/"))
    sid = f"{src['source']}:{u.scheme}://{(u.netloc + u.path).lower()}"
    return sid + (f"/{src['workspace']}" if src["source"] == "plane" else "")


def list_remote(src: dict) -> list[dict]:
    return SOURCES[src["source"]][0](src)


def run_job(job_id: uuid.UUID):
    with session_factory()() as db:
        job = db.get(ImportJob, job_id)
        if not job or job.status != "queued":
            return
        job.status, job.started_at = "running", utcnow()
        db.commit()
        src = {**job.params, **crypto.decrypt(job.secrets)}
        ctx, importer = None, None
        try:
            project = db.query(Project).filter(Project.key == job.project_key).one()
            ctx = Context(db, job, project, source_id(src))
            importer = SOURCES[job.source][1](ctx, src, job.params)
            importer.run()
            ctx.checkpoint()
            job.status = "done"
        except Exception as e:  # noqa: BLE001 - every failure has to end up in the job, not in the thread
            text = job.log
            db.rollback()  # what was committed at the last checkpoint stays
            job = db.get(ImportJob, job_id)
            job.status, job.log = "failed", text
            job.error = str(e) if isinstance(e, SourceError) else f"{type(e).__name__}: {e}"
            if not isinstance(e, SourceError):
                log.error("import %s failed\n%s", job_id, traceback.format_exc())
            if ctx:
                job.stats = {**ctx.stats, "unmatched_users": sorted(ctx.unmatched)}
        finally:
            if importer:
                importer.close()
        job.secrets, job.finished_at = None, utcnow()
        db.commit()


def launch(job_id: uuid.UUID):
    """Separate function so tests can run the job in the request thread."""
    threading.Thread(target=run_job, args=(job_id,), name=f"import-{job_id}", daemon=True).start()


def fail_interrupted():
    """Jobs that were running when their process stopped will never finish. A running job writes its progress
    at least every few minutes, so one silent for STALE is taken as dead (other replicas may be running theirs)."""
    with session_factory()() as db:
        db.execute(update(ImportJob).where(ImportJob.status.in_(("queued", "running")),
                                           ImportJob.updated_at < utcnow() - STALE)
                   .values(status="failed", error="Interrupted by a restart, run it again", secrets=None,
                           finished_at=utcnow()))
        db.commit()
