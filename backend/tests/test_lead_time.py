"""Tests for :mod:`app.services.lead_time`.

This is the arithmetic behind the two-week-per-unit underestimate that started this
work: the templates say "34 Arbeitstage" and the system planned 34 calendar days.
The off-by-one at the start day is the easiest way to reintroduce a version of that
error, so it is pinned first.

Pure over an ``is_working_day`` predicate, so no database and no calendar fixture.
All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date

from app.services.lead_time import (
    MAX_LOOKAHEAD_DAYS,
    add_working_days,
    count_working_days,
    schedule_warning,
)

# 2026-06-01 is a Monday.
MONDAY = date(2026, 6, 1)
FRIDAY = date(2026, 6, 5)
SATURDAY = date(2026, 6, 6)
SUNDAY = date(2026, 6, 7)
NEXT_MONDAY = date(2026, 6, 8)


def five_day_week(day: date) -> bool:
    """Monday to Friday are working days."""
    return day.weekday() < 5


def never(_day: date) -> bool:
    """No day grants working time — a misconfigured calendar."""
    return False


def always(_day: date) -> bool:
    """Every day is a working day — a plant running seven days."""
    return True


class TestAddWorkingDays:
    """Where a process of N working days ends."""

    def test_one_day_starting_on_a_working_day_ends_that_day(self):
        """Inclusive of the start.

        A job beginning on a working Monday spends that Monday on the work. Treating
        the start as exclusive would shift every computed end date by one day.
        """
        assert add_working_days(MONDAY, 1, five_day_week) == MONDAY

    def test_five_days_from_monday_ends_friday(self):
        assert add_working_days(MONDAY, 5, five_day_week) == FRIDAY

    def test_six_days_skips_the_weekend(self):
        """This is the whole point: the sixth working day is the next Monday."""
        assert add_working_days(MONDAY, 6, five_day_week) == NEXT_MONDAY

    def test_start_on_a_weekend_waits_for_the_next_working_day(self):
        assert add_working_days(SATURDAY, 1, five_day_week) == NEXT_MONDAY

    def test_thirty_four_working_days_is_about_seven_weeks(self):
        """The reference case, stated as a test.

        34 working days from a Monday lands on 2026-07-16 — a span of 46 calendar
        days. Planning it as 34 calendar days would have promised 2026-07-04, twelve
        days early.
        """
        end = add_working_days(MONDAY, 34, five_day_week)
        assert end == date(2026, 7, 16)
        assert (end - MONDAY).days == 45

    def test_seven_day_operation_needs_no_weekend_skip(self):
        assert add_working_days(MONDAY, 7, always) == SUNDAY

    def test_zero_or_negative_is_no_claim(self):
        """A zero-day process is a data error, not a shorter process."""
        assert add_working_days(MONDAY, 0, five_day_week) is None
        assert add_working_days(MONDAY, -3, five_day_week) is None

    def test_a_calendar_with_no_working_days_gives_up(self):
        """Rather than walking forever.

        Hitting the bound means the calendar is wrong, not that the answer was far
        away, so returning None is the honest result.
        """
        assert add_working_days(MONDAY, 1, never) is None
        assert MAX_LOOKAHEAD_DAYS >= 3650


class TestCountWorkingDays:
    """Working days in an inclusive range."""

    def test_full_week(self):
        assert count_working_days(MONDAY, FRIDAY, five_day_week) == 5

    def test_range_including_a_weekend(self):
        assert count_working_days(MONDAY, NEXT_MONDAY, five_day_week) == 6

    def test_single_working_day(self):
        assert count_working_days(MONDAY, MONDAY, five_day_week) == 1

    def test_single_non_working_day(self):
        assert count_working_days(SATURDAY, SATURDAY, five_day_week) == 0

    def test_inverted_range_is_zero_not_negative(self):
        assert count_working_days(FRIDAY, MONDAY, five_day_week) == 0


class TestScheduleWarning:
    """Whether a lead time overruns the commitment."""

    def test_no_lead_time_means_nothing_to_check(self):
        assert schedule_warning(MONDAY, FRIDAY, None, five_day_week) is None

    def test_work_that_fits_raises_nothing(self):
        """Five working days ending Friday, committed to Friday."""
        assert schedule_warning(MONDAY, FRIDAY, 5, five_day_week) is None

    def test_finishing_early_raises_nothing(self):
        assert schedule_warning(MONDAY, NEXT_MONDAY, 3, five_day_week) is None

    def test_overrun_is_reported_with_the_derived_date(self):
        """Six working days cannot end on Friday."""
        warning = schedule_warning(MONDAY, FRIDAY, 6, five_day_week)
        assert warning is not None
        assert warning.derived_end == NEXT_MONDAY
        assert warning.entered_end == FRIDAY

    def test_shortfall_is_counted_in_working_days(self):
        """The unit the process is expressed in, and the number to act on.

        "One working day short" says what to recover. Measuring the gap in calendar
        days would report three for the same situation, because a weekend sits in
        between and nobody can recover a Saturday.
        """
        warning = schedule_warning(MONDAY, FRIDAY, 6, five_day_week)
        assert warning is not None
        assert warning.working_days_short == 1

    def test_larger_overrun(self):
        warning = schedule_warning(MONDAY, FRIDAY, 10, five_day_week)
        assert warning is not None
        assert warning.working_days_short == 5

    def test_the_entered_date_is_never_changed(self):
        """It is a commitment. The warning reports the discrepancy, nothing more."""
        warning = schedule_warning(MONDAY, FRIDAY, 20, five_day_week)
        assert warning is not None
        assert warning.entered_end == FRIDAY

    def test_a_broken_calendar_raises_no_false_warning(self):
        """With no working days at all the derivation fails, and a failed
        derivation must not be reported as a late project."""
        assert schedule_warning(MONDAY, FRIDAY, 5, never) is None

    def test_zero_lead_time_is_ignored(self):
        assert schedule_warning(MONDAY, FRIDAY, 0, five_day_week) is None
