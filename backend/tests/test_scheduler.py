"""Tests for :mod:`app.services.scheduler`.

The due-ness rules are tested in test_job_schedule.py. What is tested here is the machinery
around them, where the failures are quiet rather than loud:

- The advisory-lock key must be identical in two different processes. Python's ``hash`` is
  salted per interpreter, so the obvious implementation would produce different keys per
  container and the lock would exclude nothing while appearing to work.
- A job that raises must be recorded as FAILED and must not stop the other jobs. Recorded as
  succeeded, a job broken for a year reports as having run every night — the exact failure this
  module was written to end.
- A disabled scheduler must start nothing.

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization_settings import OrganizationSettings
from app.models.scheduled_job_run import JobRunStatus
from app.services import scheduler as sched

NOW = datetime(2026, 8, 26, 3, 0)


class TestJobKey:
    def test_the_key_is_deterministic(self):
        """Across processes, which is the whole requirement. A per-process salt would give
        two containers different keys and the lock would exclude nothing."""
        assert sched._job_key("prune-audit-log") == sched._job_key("prune-audit-log")

    def test_different_jobs_get_different_keys(self):
        """Otherwise one prune would block the other for no reason."""
        assert sched._job_key(sched.PRUNE_AUDIT) != sched._job_key(
            sched.PRUNE_BASELINES
        )

    def test_the_key_fits_a_postgres_integer(self):
        """pg_try_advisory_lock takes two 32-bit ints; overflowing would be a runtime
        error at the least convenient moment."""
        for name in (sched.PRUNE_AUDIT, sched.PRUNE_BASELINES, "x" * 100):
            key = sched._job_key(name)
            assert 0 <= key < 0x7FFF_FFFF

    def test_it_does_not_collapse_similar_names(self):
        assert sched._job_key("prune-audit-log") != sched._job_key("prune-audit-logs")


def _session(settings: OrganizationSettings | None, last_success=None) -> AsyncMock:
    """Session double: settings query yields ``settings``, run-log query yields
    ``last_success``, advisory lock always granted."""
    session = AsyncMock(spec=AsyncSession)

    def execute(statement, params=None):
        result = MagicMock()
        text = str(statement)
        if "pg_try_advisory_lock" in text:
            result.scalar = MagicMock(return_value=True)
            return result
        if "pg_advisory_unlock" in text:
            result.scalar = MagicMock(return_value=True)
            return result
        scalars = MagicMock()
        if "scheduled_job_runs" in text:
            scalars.first = MagicMock(return_value=last_success)
        else:
            scalars.first = MagicMock(return_value=settings)
        result.scalars = MagicMock(return_value=scalars)
        return result

    session.execute = AsyncMock(side_effect=execute)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


class TestRunDueJobs:
    async def test_a_disabled_scheduler_starts_nothing(self):
        settings = OrganizationSettings(scheduler_enabled=False, maintenance_hour=2)
        assert await sched.run_due_jobs(_session(settings), now=NOW) == []

    async def test_before_the_configured_hour_nothing_starts(self):
        settings = OrganizationSettings(scheduler_enabled=True, maintenance_hour=5)
        assert await sched.run_due_jobs(_session(settings), now=NOW) == []

    async def test_both_jobs_start_when_due(self):
        settings = OrganizationSettings(
            scheduler_enabled=True,
            maintenance_hour=2,
            audit_retention_months=0,
            baseline_retention_months=0,
        )
        started = await sched.run_due_jobs(_session(settings), now=NOW)
        assert set(started) == {sched.PRUNE_AUDIT, sched.PRUNE_BASELINES}

    async def test_a_lock_held_elsewhere_skips_that_job(self):
        """A second instance skips the cycle rather than queueing behind the first and
        then running the same prune a moment later."""
        settings = OrganizationSettings(
            scheduler_enabled=True, maintenance_hour=2, audit_retention_months=0
        )
        session = _session(settings)
        original = session.execute.side_effect

        def execute(statement, params=None):
            result = original(statement, params)
            if "pg_try_advisory_lock" in str(statement):
                result.scalar = MagicMock(return_value=False)
            return result

        session.execute = AsyncMock(side_effect=execute)
        assert await sched.run_due_jobs(session, now=NOW) == []

    async def test_a_failing_job_is_recorded_as_failed_and_the_others_still_run(
        self, monkeypatch
    ):
        """Recorded as succeeded, a job broken for a year reports as having run every
        night — the exact failure this module ends."""
        settings = OrganizationSettings(
            scheduler_enabled=True,
            maintenance_hour=2,
            audit_retention_months=0,
            baseline_retention_months=0,
        )
        recorded: list[tuple[str, JobRunStatus]] = []

        async def boom(session):
            raise RuntimeError("Datenbank weg")

        real_record_end = sched._record_end

        async def spy_record_end(session, run, status, items, detail):
            recorded.append((run.job_name, status))
            await real_record_end(session, run, status, items, detail)

        monkeypatch.setitem(sched.JOBS, sched.PRUNE_AUDIT, boom)
        monkeypatch.setattr(sched, "_record_end", spy_record_end)

        started = await sched.run_due_jobs(_session(settings), now=NOW)
        assert set(started) == {sched.PRUNE_AUDIT, sched.PRUNE_BASELINES}
        outcomes = dict(recorded)
        assert outcomes[sched.PRUNE_AUDIT] == JobRunStatus.failed
        assert outcomes[sched.PRUNE_BASELINES] == JobRunStatus.succeeded

    async def test_zero_retention_is_reported_as_nothing_to_do_not_as_failure(self):
        """0 disables pruning by design. A job reporting failure for a deliberate setting
        would train an operator to ignore the run log."""
        settings = OrganizationSettings(
            scheduler_enabled=True, maintenance_hour=2, audit_retention_months=0
        )
        items, detail = await sched._prune_audit_job(_session(settings))
        assert items == 0
        assert "unbegrenzt" in detail

    async def test_missing_settings_row_falls_back_to_running(self):
        """A fresh install must still prune once configured, rather than silently never
        scheduling because the settings row was created lazily."""
        started = await sched.run_due_jobs(_session(None), now=NOW)
        assert set(started) == {sched.PRUNE_AUDIT, sched.PRUNE_BASELINES}
