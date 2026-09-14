"""Tests for :mod:`app.services.team_week`.

The layout rules are the interesting part, because the wrong choice in each case produces a sheet
that looks fine and misinforms the person reading it off a wall: a cell showing one of two
assignments, a suppressed assignment on a half-absent day, a blank cell that could mean either
"free" or "plant closed".

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.services.team_week import (
    DayCell,
    DayEntry,
    build_rows,
    week_days,
)

ANNA = UUID("11111111-0000-0000-0000-000000000001")
BERND = UUID("11111111-0000-0000-0000-000000000002")

MONDAY = date(2026, 8, 24)
TUESDAY = date(2026, 8, 25)
SATURDAY = date(2026, 8, 29)
SUNDAY = date(2026, 8, 30)


class TestWeekDays:
    def test_a_midweek_anchor_yields_monday_first(self):
        days = week_days(date(2026, 8, 26))
        assert days[0] == MONDAY
        assert days[0].weekday() == 0

    def test_the_week_has_seven_days_including_the_weekend(self):
        """A sheet that omits Saturday cannot show weekend work, which is exactly the thing
        somebody needs warning about."""
        days = week_days(MONDAY)
        assert len(days) == 7
        assert days[5] == SATURDAY
        assert days[6] == SUNDAY

    def test_a_monday_anchor_starts_on_itself(self):
        assert week_days(MONDAY)[0] == MONDAY

    def test_a_sunday_anchor_stays_in_the_same_iso_week(self):
        """ISO weeks end on Sunday, so a Sunday anchor must look BACK to Monday rather than
        forward — otherwise a foreman opening the sheet on Sunday sees next week."""
        assert week_days(SUNDAY)[0] == MONDAY


class TestDayCell:
    def test_an_empty_cell_asks_for_nothing(self):
        assert DayCell(day=MONDAY).assigned_percent == 0.0

    def test_two_assignments_are_both_counted(self):
        """A cell showing one of two would send somebody to half their day."""
        cell = DayCell(
            day=MONDAY,
            entries=[
                DayEntry("WP-1", "Projekt A", 50.0),
                DayEntry("WP-2", "Projekt B", 50.0),
            ],
        )
        assert cell.assigned_percent == 100.0
        assert len(cell.entries) == 2

    def test_a_full_day_within_capacity_is_not_overbooked(self):
        cell = DayCell(day=MONDAY, entries=[DayEntry("WP-1", "A", 100.0)])
        assert cell.is_overbooked is False

    def test_more_than_the_day_holds_is_overbooked(self):
        cell = DayCell(
            day=MONDAY,
            entries=[DayEntry("WP-1", "A", 80.0), DayEntry("WP-2", "B", 50.0)],
        )
        assert cell.is_overbooked is True

    def test_absence_lowers_what_the_day_can_hold(self):
        """50% away plus a 100% assignment is an overbooking, even though 100% alone is
        not."""
        cell = DayCell(
            day=MONDAY,
            entries=[DayEntry("WP-1", "A", 100.0)],
            absence_percent=50.0,
        )
        assert cell.is_overbooked is True

    def test_work_remains_visible_on_a_partially_absent_day(self):
        """Suppressing the assignment because "they are away" is how somebody ends up not
        being told about work that is still planned."""
        cell = DayCell(
            day=MONDAY,
            entries=[DayEntry("WP-1", "A", 50.0)],
            absence_percent=50.0,
        )
        assert cell.entries
        assert cell.is_overbooked is False

    def test_a_non_working_day_with_an_assignment_is_overbooked(self):
        """Work booked onto a closed day is the clearest overbooking there is, and the
        capacity arithmetic would otherwise compare against a 100% that does not exist."""
        cell = DayCell(
            day=SUNDAY,
            entries=[DayEntry("WP-1", "A", 50.0)],
            is_working_day=False,
        )
        assert cell.is_overbooked is True

    def test_an_empty_non_working_day_is_not_overbooked(self):
        assert DayCell(day=SUNDAY, is_working_day=False).is_overbooked is False

    def test_rounding_slack_does_not_create_a_false_overbooking(self):
        """Allocations are floats; 33.33 three times must not read as 100.01 > 100."""
        cell = DayCell(
            day=MONDAY,
            entries=[DayEntry(f"WP-{i}", "A", 100 / 3) for i in range(3)],
        )
        assert cell.is_overbooked is False


class TestBuildRows:
    def test_every_person_gets_a_row_and_every_day_a_cell(self):
        """A sparse structure would push "free or missing from the data" onto the reader."""
        rows = build_rows(
            days=week_days(MONDAY),
            people=[(ANNA, "A. Beispiel"), (BERND, "B. Beispiel")],
            entries_by_person_day={},
            absence_by_person_day={},
            working_day_by_person_day={},
        )
        assert len(rows) == 2
        assert all(len(row.cells) == 7 for row in rows)

    def test_the_given_order_is_preserved(self):
        """A sheet on a wall is read by name; re-sorting by workload would move rows week to
        week."""
        rows = build_rows(
            days=[MONDAY],
            people=[(BERND, "B. Beispiel"), (ANNA, "A. Beispiel")],
            entries_by_person_day={},
            absence_by_person_day={},
            working_day_by_person_day={},
        )
        assert [row.name for row in rows] == ["B. Beispiel", "A. Beispiel"]

    def test_entries_absence_and_calendar_land_in_the_right_cell(self):
        rows = build_rows(
            days=[MONDAY, TUESDAY],
            people=[(ANNA, "A. Beispiel")],
            entries_by_person_day={(ANNA, TUESDAY): [DayEntry("WP-1", "A", 60.0)]},
            absence_by_person_day={(ANNA, MONDAY): (100.0, 100.0)},
            working_day_by_person_day={(ANNA, MONDAY): True, (ANNA, TUESDAY): True},
        )
        monday_cell, tuesday_cell = rows[0].cells
        assert monday_cell.absence_percent == 100.0
        assert monday_cell.provisional_percent == 100.0
        assert monday_cell.entries == []
        assert tuesday_cell.entries[0].work_package_name == "WP-1"
        assert tuesday_cell.absence_percent == 0.0

    def test_a_missing_calendar_entry_defaults_to_a_working_day(self):
        """Defaulting to closed would blank out a whole sheet on any gap in the calendar
        data, which reads as "nothing planned" for everybody."""
        rows = build_rows(
            days=[MONDAY],
            people=[(ANNA, "A. Beispiel")],
            entries_by_person_day={},
            absence_by_person_day={},
            working_day_by_person_day={},
        )
        assert rows[0].cells[0].is_working_day is True

    def test_a_person_with_nothing_is_reported_as_empty_not_dropped(self):
        """Somebody with nothing planned all week is exactly what a foreman needs to see."""
        rows = build_rows(
            days=week_days(MONDAY),
            people=[(ANNA, "A. Beispiel")],
            entries_by_person_day={},
            absence_by_person_day={},
            working_day_by_person_day={},
        )
        assert len(rows) == 1
        assert rows[0].has_anything is False

    def test_a_person_with_only_an_absence_counts_as_having_something(self):
        rows = build_rows(
            days=[MONDAY],
            people=[(ANNA, "A. Beispiel")],
            entries_by_person_day={},
            absence_by_person_day={(ANNA, MONDAY): (100.0, 0.0)},
            working_day_by_person_day={},
        )
        assert rows[0].has_anything is True
