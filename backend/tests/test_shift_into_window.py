"""Tests for the shift-into-window suggestion.

This closes the last asymmetry in the suggestion service: three conflict causes had an
automatic fix and the window violation had none. It also corrects something worse than a
gap — for that cause the service was offering whole-day shifts, which cannot fix it,
because moving a booking three days forward leaves its clock time unchanged.

The arithmetic is a pure function over already-resolved spans, so no database and no
calendar fixture. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import datetime

from app.services.conflict_suggestion_service import shift_into_span


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 1, hour, minute)


TWO_SHIFT = [(_at(6), _at(22))]
SPLIT_SHIFT = [(_at(6), _at(13)), (_at(14), _at(22))]
DAY_SHIFT = [(_at(6), _at(14))]
NIGHT_ONLY = [(_at(22), datetime(2026, 6, 2, 6))]


class TestShiftIntoSpan:
    """Where a wrongly placed booking should go."""

    def test_a_booking_before_opening_moves_to_the_start(self):
        """The case that motivated the whole feature: 03:00 against a day shift."""
        result = shift_into_span(_at(3), _at(6), DAY_SHIFT)
        assert result == _at(6)

    def test_a_booking_after_closing_moves_back_into_the_window(self):
        result = shift_into_span(_at(20), _at(22), DAY_SHIFT)
        assert result == _at(12)

    def test_a_booking_already_inside_gets_no_suggestion(self):
        """Zero-shift suggestions would look like a fix for a different conflict."""
        assert shift_into_span(_at(8), _at(12), DAY_SHIFT) is None

    def test_a_booking_exactly_filling_the_window_gets_no_suggestion(self):
        assert shift_into_span(_at(6), _at(14), DAY_SHIFT) is None

    def test_the_nearest_span_wins_not_the_earliest(self):
        """The nearest placement wins, including the end of an earlier span."""
        result = shift_into_span(_at(13), _at(19), SPLIT_SHIFT)
        assert result == _at(14)

    def test_a_booking_longer_than_every_span_gets_no_suggestion(self):
        """Inventing a shift that does not resolve the violation is worse than none."""
        assert shift_into_span(_at(2), _at(14), DAY_SHIFT) is None

    def test_no_windows_means_no_suggestion(self):
        assert shift_into_span(_at(3), _at(5), []) is None

    def test_a_booking_crossing_midnight_can_be_moved_into_a_night_window(self):
        result = shift_into_span(_at(20), datetime(2026, 6, 2, 0), NIGHT_ONLY)
        assert result == _at(22)

    def test_an_inverted_range_is_refused(self):
        assert shift_into_span(_at(10), _at(8), DAY_SHIFT) is None

    def test_a_zero_length_booking_is_refused(self):
        assert shift_into_span(_at(10), _at(10), DAY_SHIFT) is None

    def test_a_merged_two_shift_span_accepts_a_long_booking(self):
        """Where shifts touch, the merged span holds work spanning both."""
        result = shift_into_span(_at(3), _at(15), TWO_SHIFT)
        assert result == _at(6)

    def test_a_gap_between_shifts_is_not_bookable_across(self):
        """A booking longer than either half of a split shift does not fit.

        The gap is real: a resource down between 13:00 and 14:00 cannot host work
        that runs through it, and merging across the gap would report time that does
        not exist."""
        assert shift_into_span(_at(3), _at(13), SPLIT_SHIFT) is None

    def test_minutes_are_preserved_not_rounded(self):
        """Shift edges are not always on the hour, and 07:30 is a real opening."""
        result = shift_into_span(_at(3), _at(4), [(_at(7, 30), _at(15))])
        assert result == _at(7, 30)
