import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import delivery, providers
from .config import get_settings
from .db import engine, session_factory
from .models import User, utcnow
from .routers import admin, auth, issues, notifications, planning, projects, setup, users
from .security import hash_password

log = logging.getLogger("lodestone")


def bootstrap():
    """Builtin roles, sign-in providers / setup wizard state, then the break-glass admin."""
    with session_factory()() as db:
        providers.bootstrap(db)
    bootstrap_admin()


def bootstrap_admin():
    """Creates/updates the break-glass local admin from env (LODESTONE_ADMIN_USERNAME/PASSWORD)."""
    s = get_settings()
    if not (s.admin_username and s.admin_password):
        return
    name = s.admin_username.lower()
    with session_factory()() as db:
        # several workers/replicas start at once: insert-if-missing must not race
        created = db.execute(pg_insert(User).values(
            id=uuid.uuid4(), username=name, display_name="Administrator", source="local", is_admin=True,
            is_active=True, created_at=utcnow()).on_conflict_do_nothing(index_elements=["username"])).rowcount
        if created:
            log.info("bootstrap admin created: %s", name)
        u = db.scalar(select(User).where(User.username == name))
        u.password_hash, u.is_admin, u.is_active, u.source = hash_password(s.admin_password), True, True, "local"
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if s.secret_key == "change-me":
        log.warning("LODESTONE_SECRET_KEY is the default value — set a random secret in production")
    bootstrap()
    worker = None
    if s.notify_worker:
        worker = delivery.Worker()
        worker.start()
    yield
    if worker:
        worker.stop.set()


app = FastAPI(title="Lodestone", version="0.1.0", lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json", redoc_url=None)

for r in (auth.router, setup.router, admin.router, users.router, projects.router, issues.router,
          notifications.router, planning.router):
    app.include_router(r)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/docs"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.get("/healthz", include_in_schema=False)
def healthz():
    with engine().connect() as c:
        c.execute(text("select 1"))
    return {"status": "ok"}


@app.exception_handler(404)
async def not_found(request: Request, exc):
    """API 404s stay JSON; everything else falls back to the SPA so client-side routes work on reload."""
    static = get_settings().static_dir
    if not request.url.path.startswith("/api/") and static and (Path(static) / "index.html").exists():
        return FileResponse(Path(static) / "index.html")
    detail = getattr(exc, "detail", "Not found")
    return JSONResponse({"detail": detail}, status_code=404)


_static = get_settings().static_dir
if _static and Path(_static).is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="spa")
