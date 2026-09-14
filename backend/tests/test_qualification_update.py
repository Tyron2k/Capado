"""Tests for :mod:`app.services.qualification_update_service`.

The point of interest is the distinction between "not mentioned" and "set to null". Almost
every partial-update convention collapses those two, and collapsing them here would make an
expiry date impossible to remove once entered — a renewed certificate could never be
recorded as no longer expiring.

The other point is that validation runs against the RESULTING row, not the payload. A caller
who moves only one bound can still invert the window against the stored other one.

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.exceptions import InputValidationError
from app.services.qualification_update_service import (
    UNSET,
    QualificationUpdate,
    apply_bounds,
)


class FakeAssignment:
    """Stand-in for a stored qualification row."""

    def __init__(
        self,
        valid_from: date | None = None,
        valid_until: date | None = None,
        level: int | None = None,
    ) -> None:
        self.valid_from = valid_from
        self.valid_until = valid_until
        self.level = level


class TestOmittedVersusCleared:
    """The distinction the whole module exists for."""

    def test_an_omitted_field_is_left_alone(self):
        row = FakeAssignment(valid_until=date(2026, 12, 31), level=3)
        apply_bounds(row, QualificationUpdate(valid_from=date(2026, 1, 1)))
        assert row.valid_from == date(2026, 1, 1)
        assert row.valid_until == date(2026, 12, 31)
        assert row.level == 3

    def test_an_explicit_null_clears_the_expiry(self):
        """A renewed certificate that no longer expires. If this were read as "leave
        alone", the stale expiry date would silently stay and keep failing the check."""
        row = FakeAssignment(valid_until=date(2026, 3, 1))
        apply_bounds(row, QualificationUpdate(valid_until=None))
        assert row.valid_until is None

    def test_an_explicit_null_clears_the_level(self):
        row = FakeAssignment(level=4)
        apply_bounds(row, QualificationUpdate(level=None))
        assert row.level is None

    def test_an_empty_update_changes_nothing(self):
        row = FakeAssignment(
            valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31), level=2
        )
        apply_bounds(row, QualificationUpdate())
        assert row.valid_from == date(2026, 1, 1)
        assert row.valid_until == date(2026, 12, 31)
        assert row.level == 2

    def test_unset_is_not_none(self):
        """The sentinel has to be distinguishable, or the whole scheme collapses."""
        assert UNSET is not None


class TestValidationAgainstTheResult:
    """Not against the payload."""

    def test_a_new_start_after_the_stored_end_is_refused(self):
        """Only valid_from is sent, and on its own it is unremarkable. It inverts the
        window against what is already stored, which checking the payload alone would
        miss — and the database would then reject it with an error nobody can act on."""
        row = FakeAssignment(valid_until=date(2026, 3, 1))
        with pytest.raises(InputValidationError, match="valid_from"):
            apply_bounds(row, QualificationUpdate(valid_from=date(2026, 6, 1)))

    def test_a_new_end_before_the_stored_start_is_refused(self):
        row = FakeAssignment(valid_from=date(2026, 6, 1))
        with pytest.raises(InputValidationError, match="no day at all"):
            apply_bounds(row, QualificationUpdate(valid_until=date(2026, 3, 1)))

    def test_clearing_the_other_bound_makes_an_inverted_window_legal_again(self):
        """Sending both in one call is the honest way to fix an inversion."""
        row = FakeAssignment(valid_until=date(2026, 3, 1))
        apply_bounds(
            row, QualificationUpdate(valid_from=date(2026, 6, 1), valid_until=None)
        )
        assert row.valid_from == date(2026, 6, 1)
        assert row.valid_until is None

    def test_equal_bounds_are_legal(self):
        """A one-day qualification is unusual but not an error."""
        row = FakeAssignment()
        apply_bounds(
            row,
            QualificationUpdate(
                valid_from=date(2026, 6, 1), valid_until=date(2026, 6, 1)
            ),
        )
        assert row.valid_from == row.valid_until

    @pytest.mark.parametrize("bad_level", [0, 6, -1, 99])
    def test_a_level_outside_the_range_is_refused(self, bad_level: int):
        row = FakeAssignment()
        with pytest.raises(InputValidationError, match="level must be between"):
            apply_bounds(row, QualificationUpdate(level=bad_level))

    @pytest.mark.parametrize("good_level", [1, 2, 3, 4, 5])
    def test_every_level_in_range_is_accepted(self, good_level: int):
        row = FakeAssignment()
        apply_bounds(row, QualificationUpdate(level=good_level))
        assert row.level == good_level
