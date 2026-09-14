"""Retention for the audit log.

The audit log records who changed what and when, and until now it kept every entry
forever. For a table holding behavioural data about named users that is not a
neutral default — it is the one place in Capado from which nothing is ever removed,
which is also why migration 013 had to rewrite its payloads rather than only the
absence rows.

The retention period is configurable because it is a legal and organisational
decision, not a technical one: it belongs to whoever signs the works agreement, and
different operators will answer it differently. The default is 24 months.

Deletion here is real deletion. A soft-delete would leave the data in place while
reporting that it was removed, which is worse than having no retention at all
because it invites the claim that the obligation was met.

**A configured period does nothing on its own.** Something has to run the pruning —
see ``app/scripts/prune_audit_log.py``. A setting whose executor is never scheduled
is a promise, not a mechanism, and this module cannot enforce its own scheduling.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Deleting years of history in one statement can lock the table for minutes on a
# large log. Pruning walks in bounded batches instead, so a first run on a long
# backlog degrades throughput rather than availability.
DELETE_BATCH_SIZE = 5_000

# A ceiling on batches per invocation, so a single run cannot spin indefinitely if
# rows keep arriving. What is left over is deleted by the next run.
MAX_BATCHES_PER_RUN = 200

KEEP_FOREVER = 0


@dataclass(frozen=True)
class PruneResult:
    """What a pruning run did, so an operator can show that it ran."""

    cutoff: datetime | None
    deleted: int
    truncated: bool
    """True when the batch ceiling was reached and rows remain to delete."""


def months_before(reference: date, months: int) -> date:
    """The same day-of-month ``months`` earlier, clamped to a valid date.

    Whole months rather than a fixed number of days, because a retention period is
    agreed as "24 months" and 730 days drifts against that. The day is clamped to
    the target month's length, so 31 March minus one month is 28 February rather
    than an invalid date.
    """
    total = reference.year * 12 + (reference.month - 1) - months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(reference.day, last_day))


def cutoff_for(retention_months: int, now: datetime | None = None) -> datetime | None:
    """The timestamp before which entries may be deleted.

    Returns None when retention is disabled, which is the caller's signal to delete
    nothing at all. Zero and negative both mean "keep forever": a negative period
    would otherwise compute a cutoff in the FUTURE and delete the entire log, so it
    is refused rather than trusted.
    """
    if retention_months <= KEEP_FOREVER:
        return None
    reference = now or datetime.now(UTC).replace(tzinfo=None)
    boundary = months_before(reference.date(), retention_months)
    return datetime.combine(boundary, reference.time())


async def prune_audit_log(
    session: AsyncSession,
    retention_months: int,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> PruneResult:
    """Delete audit entries older than the retention period.

    Args:
        session: Active async session.
        retention_months: Period in whole months; 0 disables pruning entirely.
        now: Reference point, for tests.
        dry_run: Count what would be deleted and change nothing. Offered because a
            first run against years of history is not something to discover after
            the fact.

    Returns:
        What was done, including whether rows remain.
    """
    cutoff = cutoff_for(retention_months, now)
    if cutoff is None:
        logger.info("Audit log retention is disabled; nothing pruned.")
        return PruneResult(cutoff=None, deleted=0, truncated=False)

    if dry_run:
        result = await session.execute(
            sa.text("SELECT count(*) FROM audit_log WHERE recorded_at < :cutoff"),
            {"cutoff": cutoff},
        )
        count = int(result.scalar_one())
        logger.info("Would delete %s audit entries recorded before %s.", count, cutoff)
        return PruneResult(cutoff=cutoff, deleted=count, truncated=False)

    deleted = 0
    truncated = True
    for _ in range(MAX_BATCHES_PER_RUN):
        result = await session.execute(
            sa.text(
                "DELETE FROM audit_log WHERE id IN ("
                "  SELECT id FROM audit_log WHERE recorded_at < :cutoff LIMIT :size"
                ")"
            ),
            {"cutoff": cutoff, "size": DELETE_BATCH_SIZE},
        )
        batch = result.rowcount or 0
        deleted += batch
        # Commit per batch: an interrupted run should leave the work it already did
        # done, not roll back an hour of deletion.
        await session.commit()
        if batch < DELETE_BATCH_SIZE:
            truncated = False
            break

    logger.info(
        "Deleted %s audit entries recorded before %s%s.",
        deleted,
        cutoff,
        " (batch ceiling reached, more remain)" if truncated else "",
    )
    return PruneResult(cutoff=cutoff, deleted=deleted, truncated=truncated)
