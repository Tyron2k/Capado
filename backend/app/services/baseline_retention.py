"""Retention for plan baselines.

A baseline is a different kind of record from an audit entry, and the default here is
deliberately the opposite one: **disabled**.

An audit entry accumulates as a side effect of working. Nobody decided to create it, so
deleting it after a period is a privacy measure with no cost to anyone.

A baseline is the opposite: somebody deliberately froze the plan because that state
mattered — a customer sign-off, an agreed delivery schedule. Silently deleting the state
a commitment was measured against is destructive in a way an expired audit row is not, and
an operator who has not thought about it should not lose it by omission.

So retention exists — the snapshots do reference people, and an operator with a deletion
obligation needs a way to satisfy it — but it only runs when someone sets a period.
Manual deletion via the API remains the normal path for a baseline that is simply no
longer needed.

Deleting a baseline removes its entries too, via the ON DELETE CASCADE on
``baseline_entries.baseline_id``: an entry without its header is unreadable, not a partial
record.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_retention import KEEP_FOREVER, months_before

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BaselinePruneResult:
    """What a pruning run did."""

    cutoff: datetime | None
    deleted: int
    kept_current: bool
    """True when a baseline old enough to delete was kept because it is the current
    comparison point."""


def cutoff_for(retention_months: int, now: datetime | None = None) -> datetime | None:
    """The timestamp before which baselines may be deleted.

    Returns None when retention is disabled. Zero and negative both mean keep
    everything: a negative period would compute a cutoff in the FUTURE and delete
    every baseline, so it is refused rather than trusted — the same guard as the audit
    log, and for the same reason.
    """
    if retention_months <= KEEP_FOREVER:
        return None
    reference = now or datetime.now(UTC)
    boundary = months_before(reference.date(), retention_months)
    return datetime.combine(boundary, reference.timetz())


async def prune_baselines(
    session: AsyncSession,
    retention_months: int,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> BaselinePruneResult:
    """Delete baselines older than the retention period.

    The baseline marked ``is_current`` is never deleted, however old it is. It is the
    point drift is measured against, and removing it would silently turn every "the
    plan has not moved" answer into "there is nothing to compare with" — a comparison
    tool that quietly stops comparing is worse than one that keeps an old record.

    Not batched, unlike the audit log: a deployment has baselines in the dozens, not
    the millions, so a single statement is honest here. Their entries go with them
    through the cascade, which is where the row volume actually is.
    """
    cutoff = cutoff_for(retention_months, now)
    if cutoff is None:
        logger.info("Baseline retention is disabled; nothing pruned.")
        return BaselinePruneResult(cutoff=None, deleted=0, kept_current=False)

    count_stmt = sa.text(
        "SELECT count(*) FROM baselines "
        "WHERE created_at < :cutoff AND is_current = false"
    )
    result = await session.execute(count_stmt, {"cutoff": cutoff})
    eligible = int(result.scalar_one())

    current_stmt = sa.text(
        "SELECT count(*) FROM baselines "
        "WHERE created_at < :cutoff AND is_current = true"
    )
    kept = int((await session.execute(current_stmt, {"cutoff": cutoff})).scalar_one())

    if dry_run:
        logger.info("Would delete %s baselines created before %s.", eligible, cutoff)
        return BaselinePruneResult(
            cutoff=cutoff, deleted=eligible, kept_current=kept > 0
        )

    await session.execute(
        sa.text(
            "DELETE FROM baselines WHERE created_at < :cutoff AND is_current = false"
        ),
        {"cutoff": cutoff},
    )
    await session.commit()

    logger.info(
        "Deleted %s baselines created before %s%s.",
        eligible,
        cutoff,
        " (the current baseline was kept)" if kept else "",
    )
    return BaselinePruneResult(cutoff=cutoff, deleted=eligible, kept_current=kept > 0)
