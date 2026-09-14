"""Tests for :mod:`app.services.job_schedule`.

Three rules here are choices rather than mechanics, and each wrong choice produces a scheduler
that looks like it works: one that runs a missed job once per missed day, one that drifts out
of its maintenance window, and one that reports a permanently failing job as having run.

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import datetime

from app.services.job_schedule import JobSchedule, is_due, next_wake_seconds

NIGHTLY = JobSchedule(name="prune-audit-log", hour=2)


class TestIsDue:
    def test_a_job_that_never_ran_runs_once_the_hour_has_passed(self):
        assert is_due(NIGHTLY, datetime(2026, 8, 26, 3, 0), None) is True

    def test_a_job_that_never_ran_waits_until_the_hour(self):
        """Running early would shift the cadence permanently on the first day."""
        assert is_due(NIGHTLY, datetime(2026, 8, 26, 1, 0), None) is False

    def test_the_configured_hour_itself_counts_as_arrived(self):
        assert is_due(NIGHTLY, datetime(2026, 8, 26, 2, 0), None) is True

    def test_a_job_that_ran_today_does_not_run_again(self):
        last = datetime(2026, 8, 26, 2, 5)
        assert is_due(NIGHTLY, datetime(2026, 8, 26, 15, 0), last) is False

    def test_a_job_that_ran_yesterday_runs_again(self):
        last = datetime(2026, 8, 25, 2, 5)
        assert is_due(NIGHTLY, datetime(2026, 8, 26, 3, 0), last) is True

    def test_a_missed_day_is_not_made_up_more_than_once(self):
        """Three days down means ONE run on return, not three. is_due can only answer yes
        or no, so what this pins is that the answer does not depend on HOW overdue the job
        is — the caller runs it once and records success, and the next check says no."""
        last = datetime(2026, 8, 20, 2, 5)
        now = datetime(2026, 8, 26, 3, 0)
        assert is_due(NIGHTLY, now, last) is True
        # After that single run, recorded now, it is no longer due.
        assert is_due(NIGHTLY, now, now) is False

    def test_the_comparison_is_by_date_not_by_elapsed_hours(self):
        """An elapsed-24h rule drifts the run later every day until it walks out of the
        maintenance window. Ran at 02:05 yesterday, it is due at 02:00 today even though
        fewer than 24 hours have passed."""
        last = datetime(2026, 8, 25, 2, 5)
        assert is_due(NIGHTLY, datetime(2026, 8, 26, 2, 0), last) is True

    def test_a_disabled_job_never_runs_however_overdue(self):
        """An off switch, not a delay."""
        disabled = JobSchedule(name="prune-audit-log", hour=2, enabled=False)
        assert is_due(disabled, datetime(2026, 8, 26, 23, 0), None) is False
        assert (
            is_due(disabled, datetime(2026, 8, 26, 23, 0), datetime(2020, 1, 1))
            is False
        )

    def test_only_a_successful_run_counts(self):
        """last_success is the contract: a job failing every night keeps being retried
        rather than reporting as done for a year. Passing None — which is what the caller
        does when there is no SUCCESSFUL run on record — must make it due."""
        assert is_due(NIGHTLY, datetime(2026, 8, 26, 3, 0), None) is True

    def test_a_midnight_job_is_due_all_day(self):
        """hour=0 must not accidentally mean "never", which is what a strict `<` against a
        falsy hour would produce in a language with looser truthiness."""
        midnight = JobSchedule(name="x", hour=0)
        assert is_due(midnight, datetime(2026, 8, 26, 0, 0), None) is True
        assert is_due(midnight, datetime(2026, 8, 26, 23, 59), None) is True


class TestNextWakeSeconds:
    def test_the_interval_is_converted_to_seconds(self):
        assert next_wake_seconds(15) == 900

    def test_a_floor_prevents_a_busy_loop(self):
        """A misconfigured zero must not turn the scheduler into a spin."""
        assert next_wake_seconds(0) == 60
        assert next_wake_seconds(-5) == 60
