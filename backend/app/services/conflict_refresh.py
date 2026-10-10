"""Shared conflict reconciliation for edits, imports and scheduled checks."""

import logging
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.conflict import Conflict
from app.services.conflict_service import ConflictService

CONFLICT_CHECK_JOB = "refresh-conflicts"
CONFLICT_CHECK_INTERVAL_MINUTES = 15
logger = logging.getLogger(__name__)


async def refresh_resources(
    session: AsyncSession, resource_ids: Iterable[UUID] | None = None
) -> int:
    """Reconcile each resource once, including old conflicts with no bookings left.

    Call after committing the input changes. Each resource has its own atomic
    transaction and lock in ConflictService. A failed resource aborts the run,
    which the scheduler records as failed and retries on its next cycle.
    """
    if resource_ids is None:
        assigned = (
            (await session.execute(select(Assignment.resource_id).distinct()))
            .scalars()
            .all()
        )
        conflicted = (
            (await session.execute(select(Conflict.resource_id).distinct()))
            .scalars()
            .all()
        )
        resource_ids = set(assigned) | set(conflicted)
    service = ConflictService(session)
    count = 0
    for rid in sorted(set(resource_ids)):
        count += len(await service.refresh_conflicts(rid))
    return count


async def refresh_after_commit(
    session: AsyncSession, resource_ids: Iterable[UUID] | None = None
) -> None:
    """Reconcile a committed write without reporting that saved input as failed.

    An independent session keeps rollback of derived data from expiring the saved
    ORM objects used in the API response. Scheduler/import entry points retain
    strict refresh_resources and their existing failure reporting/retry behavior.
    """
    try:
        if isinstance(session, AsyncSession):
            async with AsyncSession(
                bind=session.bind, expire_on_commit=False, info=session.info.copy()
            ) as derived:
                await refresh_resources(derived, resource_ids)
        else:
            # Existing DB-free service tests use session doubles. They cannot
            # establish transaction isolation, which the PostgreSQL tests cover.
            await refresh_resources(session, resource_ids)
    except Exception:
        logger.exception(
            "Conflict refresh failed after committed write; scheduler will retry."
        )
