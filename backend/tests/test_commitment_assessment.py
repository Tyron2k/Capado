"""Tests for :func:`app.services.lead_time.assess_commitment`.

`end_date` used to carry two facts at once: what the plan says and what was promised.
That works until they diverge — the only moment anybody cares — and then one field has to
silently pick one and hide the other.

The case these tests exist for is the third row of the truth table: the plan meets the
commitment and the recorded lead times do not. Nothing on a date-based report shows it,
which is why the result carries a `hidden` flag rather than being folded in with the
obvious kind of lateness.

Pure over an ``is_working_day`` predicate. No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date

from app.services.lead_time import assess_commitment

# 2026-06-01 is a Monday.
COMMITTED = date(2026, 6, 26)  # a Friday


def five_day_week(day: date) -> bool:
    """Monday to Friday are working days."""
    return day.weekday() < 5


def never(_day: date) -> bool:
    """A misconfigured calendar with no working days at all."""
    return False


class TestNothingToReport:
    """The cases that must stay silent."""

    def test_no_commitment_is_not_lateness(self):
        """A project nobody promised anything about is not running late."""
        assert assess_commitment(None, date(2026, 12, 31), None, five_day_week) is None

    def test_a_plan_that_fits_reports_nothing(self):
        assert (
            assess_commitment(COMMITTED, date(2026, 6, 20), None, five_day_week) is None
        )

    def test_a_plan_ending_exactly_on_the_commitment_is_on_time(self):
        """The commitment is a deadline, not an exclusive bound."""
        assert assess_commitment(COMMITTED, COMMITTED, None, five_day_week) is None

    def test_lead_times_that_fit_report_nothing(self):
        result = assess_commitment(
            COMMITTED, date(2026, 6, 20), date(2026, 6, 24), five_day_week
        )
        assert result is None


class TestVisibleLateness:
    """The plan itself already ends after the commitment."""

    def test_a_late_plan_is_reported(self):
        result = assess_commitment(COMMITTED, date(2026, 7, 3), None, five_day_week)
        assert result is not None
        assert result.committed == COMMITTED
        assert result.planned_end == date(2026, 7, 3)

    def test_visible_lateness_is_not_flagged_hidden(self):
        result = assess_commitment(COMMITTED, date(2026, 7, 3), None, five_day_week)
        assert result is not None
        assert result.hidden is False

    def test_the_shortfall_is_counted_in_working_days(self):
        """Friday 26 June to Friday 3 July is five working days, not seven.

        Nobody can recover a weekend, so counting calendar days would overstate what
        there is to make up.
        """
        result = assess_commitment(COMMITTED, date(2026, 7, 3), None, five_day_week)
        assert result is not None
        assert result.working_days_short == 5


class TestHiddenLateness:
    """The plan fits and the durations do not. The reason this feature exists."""

    def test_lead_times_overrunning_a_met_commitment_is_reported(self):
        result = assess_commitment(
            COMMITTED, date(2026, 6, 24), date(2026, 7, 1), five_day_week
        )
        assert result is not None
        assert result.derived_end == date(2026, 7, 1)

    def test_it_is_flagged_hidden(self):
        """Every date-based report on this project looks fine."""
        result = assess_commitment(
            COMMITTED, date(2026, 6, 24), date(2026, 7, 1), five_day_week
        )
        assert result is not None
        assert result.hidden is True

    def test_the_shortfall_is_measured_against_the_derived_end(self):
        result = assess_commitment(
            COMMITTED, date(2026, 6, 24), date(2026, 7, 1), five_day_week
        )
        assert result is not None
        assert result.working_days_short == 3


class TestLateOnBothCounts:
    """When plan and durations both overrun, the worse one governs."""

    def test_the_later_of_the_two_ends_sets_the_shortfall(self):
        """Reporting the smaller gap would understate the project."""
        result = assess_commitment(
            COMMITTED, date(2026, 6, 30), date(2026, 7, 8), five_day_week
        )
        assert result is not None
        assert result.working_days_short == 8
        assert result.hidden is False

    def test_a_planned_end_later_than_the_derived_end_still_governs(self):
        result = assess_commitment(
            COMMITTED, date(2026, 7, 8), date(2026, 6, 30), five_day_week
        )
        assert result is not None
        assert result.working_days_short == 8


class TestEdges:
    """Shapes that must not produce nonsense."""

    def test_a_broken_calendar_reports_the_breach_with_a_zero_shortfall(self):
        """The breach is real even when the shortfall cannot be counted.

        With no working days at all there is nothing to count, but the plan still ends
        after the commitment — suppressing the breach would hide a fact because a
        secondary number is unavailable.
        """
        result = assess_commitment(COMMITTED, date(2026, 7, 3), None, never)
        assert result is not None
        assert result.working_days_short == 0

    def test_the_commitment_is_never_adjusted(self):
        """It is the one date in the system belonging to somebody outside it."""
        result = assess_commitment(
            COMMITTED, date(2026, 9, 1), date(2026, 10, 1), five_day_week
        )
        assert result is not None
        assert result.committed == COMMITTED
