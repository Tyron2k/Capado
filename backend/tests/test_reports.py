"""Tests for the Excel report writers.

The assertions read back the produced workbook with openpyxl and check the TYPE in each cell, not
just the value. That is the point: the failure that makes an export useless is writing numbers as
text, and it is invisible in every other kind of test — the file opens, the values look right, and
the recipient's SUM returns 0 with no error.

No database. The workbook helpers are exercised directly.
"""

from __future__ import annotations

import io
from datetime import date, datetime

from openpyxl import load_workbook

from app.services.reports.workbook import (
    Column,
    autosize,
    filename_for,
    generated_subtitle,
    new_workbook,
    save,
    write_header,
    write_row,
    write_title,
)

COLUMNS = [
    Column("Person"),
    Column("Woche", "DD.MM.YYYY"),
    Column("Stunden", "0.0"),
    Column("Tage", "0"),
]


def _roundtrip(build) -> object:
    """Build a workbook with ``build(ws, columns)`` and read it back."""
    workbook = new_workbook()
    sheet = workbook.create_sheet("Test")
    build(sheet)
    return load_workbook(io.BytesIO(save(workbook)))["Test"]


class TestCellTypes:
    def test_numbers_stay_numbers(self):
        """The whole reason this test file exists. A numeric string looks identical in the
        cell and silently breaks SUM and every pivot table."""

        def build(sheet):
            row = write_header(sheet, COLUMNS, 1)
            write_row(sheet, COLUMNS, ["A. Beispiel", date(2026, 8, 24), 37.5, 5], row)

        sheet = _roundtrip(build)
        assert isinstance(sheet.cell(row=2, column=3).value, float)
        assert isinstance(sheet.cell(row=2, column=4).value, int)

    def test_dates_stay_dates(self):
        """A date written as text cannot be sorted chronologically, and Excel sorts it
        alphabetically without complaining."""

        def build(sheet):
            row = write_header(sheet, COLUMNS, 1)
            write_row(sheet, COLUMNS, ["A. Beispiel", date(2026, 8, 24), 1.0, 1], row)

        sheet = _roundtrip(build)
        value = sheet.cell(row=2, column=2).value
        assert isinstance(value, datetime | date)

    def test_none_leaves_the_cell_empty_not_the_text_none(self):
        """str(None) in a cell is the classic version of this bug: the column then contains
        the word "None" and stops being numeric for the whole sheet."""

        def build(sheet):
            row = write_header(sheet, COLUMNS, 1)
            write_row(sheet, COLUMNS, ["A. Beispiel", None, None, None], row)

        sheet = _roundtrip(build)
        assert sheet.cell(row=2, column=2).value is None
        assert sheet.cell(row=2, column=3).value is None

    def test_the_number_format_is_applied_to_the_cell(self):
        """Formatting belongs on the cell, not in the string. A pre-formatted "37,5" is
        text."""

        def build(sheet):
            row = write_header(sheet, COLUMNS, 1)
            write_row(sheet, COLUMNS, ["A", date(2026, 8, 24), 37.5, 5], row)

        sheet = _roundtrip(build)
        assert sheet.cell(row=2, column=3).number_format == "0.0"
        assert sheet.cell(row=2, column=2).number_format == "DD.MM.YYYY"

    def test_a_column_without_a_format_is_left_alone(self):
        def build(sheet):
            row = write_header(sheet, COLUMNS, 1)
            write_row(sheet, COLUMNS, ["A", date(2026, 8, 24), 1.0, 1], row)

        sheet = _roundtrip(build)
        assert sheet.cell(row=2, column=1).number_format == "General"


class TestLayout:
    def test_the_header_row_is_frozen(self):
        """A report long enough to scroll without a frozen header is a report where somebody
        misreads a column rather than scrolling back."""

        def build(sheet):
            write_header(sheet, COLUMNS, 3)

        assert _roundtrip(build).freeze_panes == "A4"

    def test_the_title_block_reserves_a_blank_row(self):
        def build(sheet):
            next_row = write_title(sheet, "Titel", "Untertitel")
            assert next_row == 4

        sheet = _roundtrip(build)
        assert sheet.cell(row=1, column=1).value == "Titel"
        assert sheet.cell(row=2, column=1).value == "Untertitel"
        assert sheet.cell(row=3, column=1).value is None

    def test_autosize_widens_for_the_longest_value_not_the_header(self):
        """The header is usually the shortest string in the column."""

        def build(sheet):
            row = write_header(sheet, COLUMNS, 1)
            write_row(
                sheet,
                COLUMNS,
                ["Ein sehr langer Personenname zum Testen", date(2026, 8, 24), 1.0, 1],
                row,
            )
            autosize(sheet, COLUMNS, 1)

        sheet = _roundtrip(build)
        assert sheet.column_dimensions["A"].width > len("Person") + 2

    def test_autosize_respects_the_upper_bound(self):
        """An unbounded width turns one long note into a column nobody can scroll past."""

        def build(sheet):
            row = write_header(sheet, COLUMNS, 1)
            write_row(sheet, COLUMNS, ["x" * 500, None, None, None], row)
            autosize(sheet, COLUMNS, 1)

        assert _roundtrip(build).column_dimensions["A"].width <= 50

    def test_the_default_sheet_is_removed(self):
        """An empty stray sheet named "Sheet" reads as something having gone wrong."""
        workbook = new_workbook()
        workbook.create_sheet("Echt")
        assert load_workbook(io.BytesIO(save(workbook))).sheetnames == ["Echt"]


class TestNaming:
    def test_the_filename_starts_with_an_iso_date(self):
        """So a folder of these sorts by date in every file manager, which a 26.08.2026
        prefix would not."""
        name = filename_for("auslastung", date(2026, 8, 26))
        assert name.startswith("2026-08-26")
        assert name.endswith(".xlsx")
        assert "auslastung" in name

    def test_the_subtitle_names_the_coverage_and_the_moment(self):
        """A spreadsheet circulating by email without both gets quoted six weeks later as if
        it were current."""
        subtitle = generated_subtitle("KW 35 bis KW 40", datetime(2026, 8, 26, 14, 30))
        assert "KW 35 bis KW 40" in subtitle
        assert "26.08.2026" in subtitle
        assert "14:30" in subtitle
