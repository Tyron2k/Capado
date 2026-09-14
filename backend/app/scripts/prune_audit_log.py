"""Apply the configured retention periods: audit log, and optionally plan baselines.

Usage (inside the backend container)::

    python -m app.scripts.prune_audit_log --dry-run
    python -m app.scripts.prune_audit_log
    python -m app.scripts.prune_audit_log --months 12

Periods come from ``organization_settings``: ``audit_retention_months`` (default 24) and
``baseline_retention_months`` (default 0, meaning keep everything). ``--months`` overrides
the AUDIT period for one run without changing the setting, which is what a one-off cleanup
wants; it does not become the new policy.

Baselines are pruned in the same run, using their own configured period. They are skipped
entirely while that period is 0, which is the default: a baseline is a record somebody
deliberately created, unlike an audit entry that accumulated by itself. The baseline marked
``is_current`` is never deleted however old it is — it is what drift is measured against.

**This script is the whole mechanism.** The setting deletes nothing by itself, so
something has to invoke this on a schedule — a systemd timer, a cron entry, or a
Kubernetes CronJob. A configured retention period with no scheduled job is a promise
rather than a mechanism, and it is exactly the kind of gap that only becomes visible
when somebody asks for evidence that deletion happens.

Run ``--dry-run`` first on a long-lived deployment. The first real run against years
of history deletes a lot at once, and seeing the number beforehand is cheaper than
discovering it afterwards.

The output line is deliberately parseable and worth capturing in the job's log: it is
the operator's evidence that the retention period is being applied.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

from app.database import async_session_factory
from app.services.audit_retention import prune_audit_log
from app.services.baseline_retention import prune_baselines
from app.services.settings_service import get_organization_settings


@dataclass(frozen=True)
class RunSummary:
    """What one invocation did, for the output line kept as evidence."""

    audit_months: int
    audit_deleted: int
    audit_truncated: bool
    baseline_months: int
    baseline_deleted: int
    baseline_kept_current: bool


async def _run(months: int | None, dry_run: bool) -> RunSummary:
    """Apply both retention periods once."""
    async with async_session_factory() as session:
        settings = await get_organization_settings(session)
        audit_months = settings.audit_retention_months if months is None else months
        baseline_months = settings.baseline_retention_months

        audit = await prune_audit_log(session, audit_months, dry_run=dry_run)
        baselines = await prune_baselines(session, baseline_months, dry_run=dry_run)

        return RunSummary(
            audit_months=audit_months,
            audit_deleted=audit.deleted,
            audit_truncated=audit.truncated,
            baseline_months=baseline_months,
            baseline_deleted=baselines.deleted,
            baseline_kept_current=baselines.kept_current,
        )


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--months",
        type=int,
        default=None,
        help=(
            "Override the configured period for this run only. 0 keeps everything. "
            "Does not change the stored setting."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many entries would be deleted and change nothing.",
    )
    args = parser.parse_args(argv)

    if args.months is not None and args.months < 0:
        # A negative period would compute a cutoff in the future and delete the
        # entire log. The service refuses it too; failing here gives a clearer
        # message than silently pruning nothing.
        raise SystemExit("--months must not be negative")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    summary = asyncio.run(_run(args.months, args.dry_run))
    verb = "would delete" if args.dry_run else "deleted"

    if summary.audit_months == 0:
        print("audit retention disabled (0 months) — no audit entries deleted")
    else:
        tail = " (batch ceiling reached, run again)" if summary.audit_truncated else ""
        print(
            f"{verb} {summary.audit_deleted} audit entries older than "
            f"{summary.audit_months} months{tail}"
        )

    if summary.baseline_months == 0:
        print("baseline retention disabled (0 months) — no baselines deleted")
    else:
        kept = (
            " (the current baseline was kept)" if summary.baseline_kept_current else ""
        )
        print(
            f"{verb} {summary.baseline_deleted} baselines older than "
            f"{summary.baseline_months} months{kept}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
