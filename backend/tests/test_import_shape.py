"""Tests for recognising which exported file somebody is trying to import.

The case that motivated this: the skill-matrix Excel export cannot be re-imported — its header is on
row 1, not row 0, and group separator rows sit between the data. The old importer answered "Header
must have at least: Name, Group", which is true, useless, and points the reader at their own edits
rather than at the file they picked.

So the tests pin the distinction that makes the message actionable: our own report (MATRIX) must be
told apart from a file nobody recognises (UNKNOWN), because only the former can say "use the flat
export instead".

All fixtures are inline and fictional.
"""

from __future__ import annotations

from app.services.import_export.shape import (
    SHAPE_REJECTION_MESSAGES,
    ImportShape,
    detect_import_shape,
)


def test_flat_export_is_recognised() -> None:
    rows = [
        ("Name", "Group", "Skill", "Attribute"),
        ("Paint booth 01", "Paint shop", "Painting", "Type Alpha"),
    ]

    assert detect_import_shape(rows) is ImportShape.FLAT


def test_flat_header_without_skill_columns_is_still_flat() -> None:
    """Skill and Attribute are optional — Name and Group are the contract."""
    assert (
        detect_import_shape([("Name", "Group"), ("Track 42", "Tracks")])
        is ImportShape.FLAT
    )


def test_header_matching_is_case_and_whitespace_insensitive() -> None:
    """Excel adds trailing spaces and people retype headers in their own casing."""
    rows = [(" NAME ", "group", "Skill"), ("Track 42", "Tracks", "Welding")]

    assert detect_import_shape(rows) is ImportShape.FLAT


def test_skill_matrix_export_is_recognised_as_such() -> None:
    """Row 0 holds merged skill names, row 1 the real header — exactly what the exporter writes."""
    rows = [
        (None, None, "Painting", None, "Welding"),
        ("Name", "Group", "Type Alpha", "Type Beta", "Type Gamma"),
        ("Paint booth 01", "Paint shop", "X", None, None),
    ]

    assert detect_import_shape(rows) is ImportShape.MATRIX


def test_matrix_rejection_names_the_way_out() -> None:
    """The message has to say what to do, or it is the old message with more words."""
    message = SHAPE_REJECTION_MESSAGES[ImportShape.MATRIX]

    assert "flat" in message.lower()
    assert "csv" in message.lower()


def test_german_group_header_is_accepted() -> None:
    """The in-app help documented "Gruppe" for a long time, and the old importer accepted it.

    It read any two-column header positionally, so hand-built German files exist and worked.
    Refusing them now would be a regression that looks like this check being broken — and the person
    affected followed our own documentation.
    """
    rows = [
        ("Name", "Gruppe", "Skill", "Attribut"),
        ("Track 42", "Tracks", "Welding", "Alpha"),
    ]

    assert detect_import_shape(rows) is ImportShape.FLAT


def test_matrix_with_a_german_second_header_row_is_still_a_matrix() -> None:
    """A German-localised matrix export must get the actionable message, not the generic one."""
    rows = [
        (None, None, "Lackieren"),
        ("Name", "Gruppe", "Typ Alpha"),
        ("Kabine 01", "Lackiererei", "X"),
    ]

    assert detect_import_shape(rows) is ImportShape.MATRIX


def test_swapped_name_and_group_is_refused_rather_than_guessed() -> None:
    """Columns are read positionally.

    Accepting a swapped header would import every group name as a resource name and every resource
    name as a group — silently, and as a bulk write. Refusing is the safer failure.
    """
    rows = [("Group", "Name"), ("Paint shop", "Paint booth 01")]

    assert detect_import_shape(rows) is ImportShape.UNKNOWN


def test_unrelated_spreadsheet_is_unknown_not_matrix() -> None:
    rows = [("Datum", "Betrag", "Konto"), ("2026-01-01", "42", "1000")]

    assert detect_import_shape(rows) is ImportShape.UNKNOWN


def test_empty_input_is_unknown() -> None:
    assert detect_import_shape([]) is ImportShape.UNKNOWN


def test_rows_that_are_not_sequences_do_not_raise() -> None:
    """A malformed parse must produce a verdict, not a traceback in the request handler."""
    assert detect_import_shape([None, "Name;Group"]) is ImportShape.UNKNOWN  # type: ignore[list-item]


def test_a_single_matrix_looking_row_without_a_second_row_is_unknown() -> None:
    """Nothing to compare against, so nothing may be claimed."""
    assert detect_import_shape([(None, None, "Painting")]) is ImportShape.UNKNOWN
