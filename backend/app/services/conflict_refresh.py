"""Shared conflict reconciliation for edits, imports and scheduled checks."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.assignment import Assignment
from app.models.conflict import Conflict
from app.services.conflict_service import ConflictService

CONFLICT_CHECK_JOB = "refresh-conflicts"
CONFLICT_CHECK_INTERVAL_MINUTES = 15


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
