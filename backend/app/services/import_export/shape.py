"""Recognise WHICH exported file somebody is trying to import.

The trap this exists for: the Excel export of personnel and infrastructure is a SKILL MATRIX — a
report with a two-row merged header, group separator rows and an autofilter. It is not re-importable,
and never was. The importer reads row 0 as the header, finds merged skill names there, and answered
"Header must have at least: Name, Group." Correct, useless, and it points the reader at their own
edits rather than at the file they picked.

So the shapes are told apart explicitly, and each verdict carries a message that names the fix. The
detection deliberately looks at STRUCTURE rather than at a marker cell: an exported file that somebody
has edited in Excel is still the file they exported, and a marker is the first thing a round-trip
through Excel loses.
"""

from __future__ import annotations

from enum import StrEnum


class ImportShape(StrEnum):
    """What an uploaded table appears to be."""

    FLAT = "flat"
    """Name, Group[, Skill, Attribute] in row 0 — the re-importable form."""

    MATRIX = "matrix"
    """The skill-matrix export: attributes as columns, header on row 1, not re-importable."""

    UNKNOWN = "unknown"
    """Neither — wrong file, wrong sheet, or a header nobody recognises."""


def _cells(row: object) -> list[str]:
    """Normalise a row to trimmed lowercase strings, tolerating None and non-strings."""
    if not isinstance(row, (tuple, list)):
        return []
    return [("" if c is None else str(c)).strip().lower() for c in row]


#: Accepted spellings of the second column.
#:
#: The exporter writes "Group", but the in-app help documented "Gruppe" for a long time, and the old
#: importer accepted ANY two-column header because it read positionally — so hand-built German files
#: exist and worked. Refusing them now would be a regression that looks like this check being broken,
#: and the person affected followed our own documentation. The first column is "Name" in both.
_GROUP_HEADERS = frozenset({"group", "gruppe"})


def _looks_like_flat_header(row: object) -> bool:
    """True when the first two cells are Name and Group, in that order.

    Order matters: the importer reads columns positionally, so a file with the two swapped would
    import every group name as a resource name. Accepting it would be worse than refusing it.
    """
    cells = _cells(row)
    return len(cells) >= 2 and cells[0] == "name" and cells[1] in _GROUP_HEADERS


def detect_import_shape(rows: list[tuple]) -> ImportShape:
    """Classify an uploaded table.

    Args:
        rows: Parsed rows including the header, as the upload parser produced them.

    Returns:
        The recognised shape. UNKNOWN when nothing matches — the caller decides how loudly to fail.

    """
    if not rows:
        return ImportShape.UNKNOWN

    if _looks_like_flat_header(rows[0]):
        return ImportShape.FLAT

    # The matrix puts merged skill names on row 0 and the real header on row 1. Checking row 1 for
    # the flat signature is what distinguishes "this is our own report" from "this is nonsense",
    # and that distinction is the entire point: only the former has an actionable message.
    if len(rows) >= 2 and _looks_like_flat_header(rows[1]):
        return ImportShape.MATRIX

    return ImportShape.UNKNOWN


#: Explanations, in the language the rest of the API answers in (English; the UI translates).
SHAPE_REJECTION_MESSAGES: dict[ImportShape, str] = {
    ImportShape.MATRIX: (
        "This looks like the skill-matrix Excel export, which cannot be imported: its header spans "
        "two rows and it contains group separator rows. Export again as 'Excel (flat)' or CSV — "
        "those are the re-importable formats — and edit that file instead."
    ),
    ImportShape.UNKNOWN: (
        "Unrecognised file. The first row must be the header and must start with the columns "
        "'Name' and 'Group', optionally followed by 'Skill' and 'Attribute'. Export the current "
        "data as 'Excel (flat)' or CSV to get a file in the expected shape."
    ),
}
