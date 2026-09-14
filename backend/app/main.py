"""FastAPI application: app instance, CORS, middleware, and router registration."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings as app_settings
from app.database import async_session_factory, wait_for_db
from app.exceptions import CatchAllExceptionMiddleware, register_exception_handlers
from app.routers import (
    absences,
    assignments,
    audit,
    auth,
    autocomplete,
    baselines,
    calendar,
    capacity,
    conflicts,
    customers,
    dashboard,
    digest,
    gantt,
    import_export,
    maintenance,
    me,
    oidc,
    projects,
    reports,
    resources,
    settings,
    skills,
    suggestions,
    team_week,
    templates,
    users,
    work_package_requirements,
)
from app.services.audit import register_audit_listener
from app.services.scheduler import scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# CORS origins are validated centrally in Settings (wildcards rejected).
CORS_ORIGINS: list[str] = app_settings.cors_origins


def run_migrations() -> None:
    """Run Alembic migrations to head."""
    import subprocess

    logger.info("Running database migrations...")
    env = os.environ.copy()
    env["PYTHONPATH"] = "/app"
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd="/app",
        env=env,
    )
    if result.returncode != 0:
        logger.error("Migration failed: %s", result.stderr)
        raise RuntimeError(f"Alembic migration failed: {result.stderr}")
    logger.info("Database migrations applied successfully.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle: verify DB connection and run migrations."""
    logger.info("Starting Capado backend...")
    # Registered before any request can arrive, so no write escapes the trail.
    register_audit_listener()
    await wait_for_db()
    run_migrations()
    # Started after migrations, because the run-log table has to exist before the first
    # cycle, and as a background task so a slow first prune cannot delay readiness.
    scheduler_task = asyncio.create_task(scheduler_loop(async_session_factory))
    logger.info("Backend ready.")
    yield
    logger.info("Backend shutting down.")
    scheduler_task.cancel()
    # Awaited rather than abandoned: a cancelled task that is never awaited can be killed
    # mid-transaction and leaves a "running" row that never resolves.
    with suppress(asyncio.CancelledError):
        await scheduler_task


app = FastAPI(
    title="Capado",
    description="REST API for production capacity planning and scheduling",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration: origins configurable via CORS_ORIGINS env var
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Catch-all middleware for unexpected errors (HTTP 500)
app.add_middleware(CatchAllExceptionMiddleware)

# Register exception handlers
register_exception_handlers(app)


# Register routers
app.include_router(auth.router, prefix="/api")
app.include_router(oidc.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(import_export.router, prefix="/api")
app.include_router(resources.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(digest.router, prefix="/api")
app.include_router(absences.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(assignments.router, prefix="/api")
app.include_router(capacity.router, prefix="/api")
app.include_router(conflicts.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(gantt.router, prefix="/api")
app.include_router(suggestions.router, prefix="/api")
app.include_router(autocomplete.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(baselines.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(maintenance.router, prefix="/api")
app.include_router(team_week.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(work_package_requirements.router, prefix="/api")


@app.get("/api/health", summary="Health check", response_model=dict[str, str])
async def health_check():
    """Health check endpoint for Docker and monitoring.

    Returns:
        JSON object with status 'ok' when the service is running.

    """
    return {"status": "ok"}
