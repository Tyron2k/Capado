"""Bound admin imports before parsing can exhaust the backend."""

import io

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook

from app.routers.import_export import _parse_csv, _parse_upload, _parse_xlsx


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
async def test_upload_reads_only_one_byte_beyond_size_limit(
    monkeypatch: pytest.MonkeyPatch, extension: str
) -> None:
    """An oversized upload must be rejected before either parser runs."""
    monkeypatch.setattr("app.routers.import_export._MAX_IMPORT_BYTES", 5)
    upload = UploadFile(file=io.BytesIO(b"123456789"), filename=f"import.{extension}")

    with pytest.raises(HTTPException) as exc:
        await _parse_upload(upload)

    assert exc.value.status_code == 413
    assert upload.file.tell() == 6


def test_csv_accepts_limit_and_rejects_next_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row limit includes the header and does not silently truncate data."""
    monkeypatch.setattr("app.routers.import_export._MAX_IMPORT_ROWS", 3)
    content = b"Name;Group\nA;One\nB;Two\n"

    assert len(_parse_csv(content)) == 3
    with pytest.raises(HTTPException) as exc:
        _parse_csv(content + b"C;Three\n")

    assert exc.value.status_code == 413


def test_xlsx_accepts_limit_and_rejects_next_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Excel reader also stops at the first disallowed row."""
    monkeypatch.setattr("app.routers.import_export._MAX_IMPORT_ROWS", 3)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("Name", "Group"))
    sheet.append(("A", "One"))
    sheet.append(("B", "Two"))
    within_limit = io.BytesIO()
    workbook.save(within_limit)

    assert len(_parse_xlsx(within_limit.getvalue())) == 3

    sheet.append(("C", "Three"))
    over_limit = io.BytesIO()
    workbook.save(over_limit)
    with pytest.raises(HTTPException) as exc:
        _parse_xlsx(over_limit.getvalue())

    assert exc.value.status_code == 413


async def test_small_csv_upload_still_parses() -> None:
    """A normal upload follows the same path as before the limits were added."""
    upload = UploadFile(file=io.BytesIO(b"Name;Group\nA;One\n"), filename="import.csv")

    assert await _parse_upload(upload) == [("Name", "Group"), ("A", "One")]
