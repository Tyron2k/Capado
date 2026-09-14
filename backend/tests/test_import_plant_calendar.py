"""Tests for :func:`app.scripts.import_plant_calendar.parse_plant_calendar`.

The input is a hand-maintained spreadsheet export spanning decades, so the parser
has to be forgiving in specific ways and strict in one: the year always comes
from the column header, never from the cell, so a typo in a cell cannot silently
move a holiday into another year.

No database and no file system: rows are passed in directly. All data is inline
and clearly fictional apart from the shape, which mirrors a real export.
"""

from __future__ import annotations

from datetime import date

from app.scripts.import_plant_calendar import ParsedHoliday, parse_plant_calendar

HEADER = ["2026", "2027", "2028", ""]


class TestParsePlantCalendar:
    """Matrix of year columns by holiday rows."""

    def test_empty_input(self):
        """No rows means no entries, not an error."""
        assert parse_plant_calendar([]) == []

    def test_header_only(self):
        """A header without holiday rows yields nothing."""
        assert parse_plant_calendar([HEADER]) == []

    def test_one_holiday_across_three_years(self):
        """Each column produces one entry, dated from its own header."""
        rows = [HEADER, ["1/1/26", "1/1/27", "1/1/28", "Neujahr"]]
        assert parse_plant_calendar(rows) == [
            ParsedHoliday(day=date(2026, 1, 1), name="Neujahr"),
            ParsedHoliday(day=date(2027, 1, 1), name="Neujahr"),
            ParsedHoliday(day=date(2028, 1, 1), name="Neujahr"),
        ]

    def test_year_comes_from_the_column_not_the_cell(self):
        """A wrong year in a cell must not move the holiday.

        This is the one place the parser is deliberately strict: the cell's own
        year field is ignored entirely.
        """
        rows = [HEADER, ["3/5/99", "", "", "Rosenmontag"]]
        assert parse_plant_calendar(rows) == [
            ParsedHoliday(day=date(2026, 3, 5), name="Rosenmontag")
        ]

    def test_empty_cells_are_normal(self):
        """A bridge day exists only in some years."""
        rows = [HEADER, ["1/2/26", "", "1/2/28", "Brückentag"]]
        assert [entry.day for entry in parse_plant_calendar(rows)] == [
            date(2026, 1, 2),
            date(2028, 1, 2),
        ]

    def test_malformed_cell_is_skipped_not_fatal(self):
        """One bad cell must not cost the whole import."""
        rows = [HEADER, ["not-a-date", "1/1/27", "2/30/28", "Neujahr"]]
        assert parse_plant_calendar(rows) == [
            ParsedHoliday(day=date(2027, 1, 1), name="Neujahr")
        ]

    def test_row_without_a_name_is_ignored(self):
        """A spacer row carries no holiday."""
        rows = [HEADER, ["", "", "", ""], ["1/1/26", "", "", "Neujahr"]]
        assert parse_plant_calendar(rows) == [
            ParsedHoliday(day=date(2026, 1, 1), name="Neujahr")
        ]

    def test_name_is_taken_from_the_last_non_empty_field(self):
        """Exports carry trailing empty columns after the name."""
        rows = [
            ["2026", "", "", ""],
            ["1/1/26", "", "Neujahr", ""],
        ]
        assert parse_plant_calendar(rows) == [
            ParsedHoliday(day=date(2026, 1, 1), name="Neujahr")
        ]

    def test_non_year_columns_are_not_read_as_dates(self):
        """Only columns whose header is a four-digit year are data columns."""
        rows = [
            ["2026", "Kommentar", ""],
            ["1/1/26", "5/5/26", "Neujahr"],
        ]
        assert parse_plant_calendar(rows) == [
            ParsedHoliday(day=date(2026, 1, 1), name="Neujahr")
        ]

    def test_duplicate_date_and_name_is_collapsed(self):
        """The same holiday listed twice is one entry, matching the unique key."""
        rows = [
            HEADER,
            ["1/1/26", "", "", "Neujahr"],
            ["1/1/26", "", "", "Neujahr"],
        ]
        assert parse_plant_calendar(rows) == [
            ParsedHoliday(day=date(2026, 1, 1), name="Neujahr")
        ]

    def test_two_holidays_on_one_date_are_both_returned(self):
        """Parsing does not decide which wins; the unique key does, on insert."""
        rows = [
            HEADER,
            ["10/3/26", "", "", "Tag der deutschen Einheit"],
            ["10/3/26", "", "", "Betriebsruhe"],
        ]
        entries = parse_plant_calendar(rows)
        assert len(entries) == 2
        assert {entry.name for entry in entries} == {
            "Tag der deutschen Einheit",
            "Betriebsruhe",
        }

    def test_result_is_sorted_by_date(self):
        """Stable output regardless of row order in the export."""
        rows = [
            HEADER,
            ["12/24/26", "", "", "Heiligabend"],
            ["1/1/26", "", "", "Neujahr"],
            ["5/1/26", "", "", "Maifeiertag"],
        ]
        days = [entry.day for entry in parse_plant_calendar(rows)]
        assert days == sorted(days)
