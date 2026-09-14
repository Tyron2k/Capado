"""The maintenance loop: runs the pruning jobs that nothing was running before.

Structure, and why it is this and not a library:

The loop polls. Every ``CHECK_INTERVAL_MINUTES`` it asks each job whether it is due
(:func:`app.services.job_schedule.is_due`, pure and tested), and runs the ones that are. Due-ness
is decided from the run log in the database, so a restart neither re-runs a completed job nor
skips a missed one — which is the property a scheduler holding its state in memory cannot have.

Concurrency is handled with a PostgreSQL advisory lock, not with an assumption. Capado is a
single-organization deployment (ADR-003) and normally runs one container, but "normally" is not
a guarantee: somebody scaling to two replicas would otherwise get two simultaneous prunes
against the same rows. The lock is per job name and released when the session ends, including on
a crash — a lock that outlived the process would be worse than no lock, because it would wedge
the job silently.

Failures are contained per job. One job raising must not stop the loop or prevent the other jobs
from running, and it must not be recorded as a success — see the run log's docstring for why
that distinction is the whole point.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.organization_settings import OrganizationSettings
from app.models.scheduled_job_run import JobRunStatus, ScheduledJobRun
from app.services.audit_retention import prune_audit_log
from app.services.baseline_retention import prune_baselines
from app.services.job_schedule import JobSchedule, is_due, next_wake_seconds

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MINUTES = 15

# Ceiling on batches per run. Sized so a first run against several years of history finishes
# rather than draining one batch per day, while still bounding how long one cycle can hold a
# transaction open against an unexpectedly large table.
MAX_PRUNE_BATCHES = 50

# Advisory lock namespace. An arbitrary but FIXED number: advisory locks share one global
# space per database, so a collision with another application's key would make two unrelated
# jobs exclude each other. Namespacing by a constant plus a per-job hash keeps that contained.
_LOCK_NAMESPACE = 0x43_41_50_4F  # "CAPO"

PRUNE_AUDIT = "prune-audit-log"
PRUNE_BASELINES = "prune-baselines"


async def _last_success(session: AsyncSession, job_name: str) -> datetime | None:
    """When this job last completed successfully, or None.

    Only successful runs count. A job failing every night must keep being retried rather than
    reporting as done, which is exactly what reading the last ATTEMPT would produce.
    """
    result = await session.execute(
        select(ScheduledJobRun)
        .where(
            ScheduledJobRun.job_name == job_name,
            ScheduledJobRun.status == JobRunStatus.succeeded,
        )
        .order_by(ScheduledJobRun.started_at.desc())
        .limit(1)
    )
    run = result.scalars().first()
    return run.started_at if run else None


async def _try_lock(session: AsyncSession, job_name: str) -> bool:
    """Take the advisory lock for this job, without waiting.

    ``pg_try_advisory_lock`` rather than ``pg_advisory_lock``: a second instance should skip
    this cycle, not queue up behind the first and then run the same prune a moment later.
    """
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:ns, :key)"),
        {"ns": _LOCK_NAMESPACE, "key": _job_key(job_name)},
    )
    return bool(result.scalar())


async def _unlock(session: AsyncSession, job_name: str) -> None:
    """Release the advisory lock."""
    await session.execute(
        text("SELECT pg_advisory_unlock(:ns, :key)"),
        {"ns": _LOCK_NAMESPACE, "key": _job_key(job_name)},
    )


def _job_key(job_name: str) -> int:
    """Stable 31-bit key for a job name.

    Python's ``hash`` is salted per process, so two containers would compute DIFFERENT keys for
    the same job and the lock would not exclude anything. This has to be deterministic across
    processes, which is the entire reason it is not a one-liner.
    """
    total = 0
    for char in job_name:
        total = (total * 131 + ord(char)) % 0x7FFF_FFFF
    return total


async def _record_start(session: AsyncSession, job_name: str) -> ScheduledJobRun:
    """Write the running row before the job starts.

    Before, not after: a container killed mid-prune then leaves a visible ``running`` row
    instead of no trace, and "hung" stops being indistinguishable from "never started".
    """
    run = ScheduledJobRun(job_name=job_name, status=JobRunStatus.running)
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def _record_end(
    session: AsyncSession,
    run: ScheduledJobRun,
    status: JobRunStatus,
    items: int | None,
    detail: str,
) -> None:
    """Close out the run row."""
    run.status = status
    run.finished_at = datetime.now(UTC).replace(tzinfo=None)
    run.items_affected = items
    # Truncated to the column width: a repeating failure must not grow the table, and a stack
    # trace belongs in the process log.
    run.detail = detail[:1000]
    session.add(run)
    await session.commit()


async def _prune_audit_job(session: AsyncSession) -> tuple[int, str]:
    """Delete audit entries past the configured retention.

    Loops over batches. ``prune_audit_log`` deletes up to a ceiling per call and reports
    ``truncated`` when rows remain; a single call would therefore report success while leaving
    the retention unmet, and since due-ness is per calendar day the backlog would drain one
    batch per day. A first run against years of history has to actually finish.

    Bounded anyway, because an unbounded loop against an unexpectedly huge table would hold a
    transaction open for an unknown time. When the bound is hit the detail says so rather than
    reporting a clean run.
    """
    settings = (
        (await session.execute(select(OrganizationSettings).limit(1))).scalars().first()
    )
    months = settings.audit_retention_months if settings else 0
    if months == 0:
        return 0, "Aufbewahrung unbegrenzt (0) — nichts zu löschen"

    total = 0
    incomplete = False
    for _ in range(MAX_PRUNE_BATCHES):
        result = await prune_audit_log(session, months)
        total += result.deleted
        if not result.truncated:
            break
    else:
        incomplete = True

    detail = f"{total} Einträge älter als {months} Monate gelöscht"
    if incomplete:
        detail += (
            f" — Stapelgrenze nach {MAX_PRUNE_BATCHES} Durchläufen erreicht, "
            f"weitere Einträge bleiben bis zum nächsten Lauf"
        )
    return total, detail


async def _prune_baselines_job(session: AsyncSession) -> tuple[int, str]:
    """Delete baselines past the configured retention.

    Not batched, matching prune_baselines: a deployment has baselines in the dozens, not the
    millions.
    """
    settings = (
        (await session.execute(select(OrganizationSettings).limit(1))).scalars().first()
    )
    months = settings.baseline_retention_months if settings else 0
    if months == 0:
        return 0, "Aufbewahrung unbegrenzt (0) — nichts zu löschen"
    result = await prune_baselines(session, months)
    detail = f"{result.deleted} Planstände älter als {months} Monate gelöscht"
    if result.kept_current:
        detail += " (aktueller Planstand behalten)"
    return result.deleted, detail


JOBS: dict[str, Callable[[AsyncSession], Awaitable[tuple[int, str]]]] = {
    PRUNE_AUDIT: _prune_audit_job,
    PRUNE_BASELINES: _prune_baselines_job,
}


async def run_due_jobs(
    session: AsyncSession,
    now: datetime | None = None,
) -> list[str]:
    """Run every job that is due. Returns the names of the jobs that were started.

    Each job is independent: one raising is recorded as a failure and the rest still run.
    """
    moment = now or datetime.now(UTC).replace(tzinfo=None)
    settings = (
        (await session.execute(select(OrganizationSettings).limit(1))).scalars().first()
    )
    enabled = settings.scheduler_enabled if settings else True
    hour = settings.maintenance_hour if settings else 2

    started: list[str] = []
    for job_name, job in JOBS.items():
        schedule = JobSchedule(name=job_name, hour=hour, enabled=enabled)
        if not is_due(schedule, moment, await _last_success(session, job_name)):
            continue
        if not await _try_lock(session, job_name):
            logger.info("Job %s läuft bereits in einer anderen Instanz", job_name)
            continue
        started.append(job_name)
        run = await _record_start(session, job_name)
        try:
            items, detail = await job(session)
            await _record_end(session, run, JobRunStatus.succeeded, items, detail)
            logger.info("Job %s: %s", job_name, detail)
        except Exception as exc:  # noqa: BLE001 — one job must not stop the others
            await session.rollback()
            await _record_end(
                session, run, JobRunStatus.failed, None, f"{type(exc).__name__}: {exc}"
            )
            logger.exception("Job %s fehlgeschlagen", job_name)
        finally:
            await _unlock(session, job_name)
    return started


async def scheduler_loop(session_factory: Callable[[], AsyncSession]) -> None:
    """Poll for due jobs until cancelled.

    A fresh session per cycle rather than one long-lived one: a connection held open for weeks
    is the kind of thing that dies quietly behind a pooler and takes the scheduler with it.

    Polls rather than sleeping until the next computed run, so that changing the configured
    hour takes effect within one interval instead of after the old sleep expires.
    """
    logger.info(
        "Wartungs-Scheduler gestartet, Prüfintervall %d Minuten", CHECK_INTERVAL_MINUTES
    )
    while True:
        try:
            async with session_factory() as session:
                await run_due_jobs(session)
        except asyncio.CancelledError:
            logger.info("Wartungs-Scheduler beendet")
            raise
        except Exception:  # noqa: BLE001 — the loop must survive anything
            # Including the database being unreachable. A scheduler that exits on the first
            # failed connection is a scheduler that silently stops after any restart ordering
            # hiccup, which is the failure mode this whole module replaces.
            logger.exception(
                "Scheduler-Zyklus fehlgeschlagen, weiter im nächsten Intervall"
            )
        await asyncio.sleep(next_wake_seconds(CHECK_INTERVAL_MINUTES))
