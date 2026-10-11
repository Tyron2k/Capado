"""Typed XLSX output without interpreting application text as formulas."""

from datetime import date, datetime

from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet


def write_cell(
    sheet: Worksheet,
    row: int,
    column: int,
    value: str | int | float | bool | date | datetime | None,
) -> Cell:
    """Write the original value, explicitly keeping strings as Excel text.

    openpyxl otherwise infers formulas from leading ``=`` and error cells
    from strings such as ``#N/A``. Changing the cell type preserves the
    original text without prefixes, including in data-only XLSX imports.
    Numbers, dates, booleans and empty values retain their usual types.
    """
    cell = sheet.cell(row=row, column=column, value=value)
    if isinstance(value, str):
        cell.data_type = "s"
    return cell
