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

# A two-shift resource, 06:00–14:00 and 14:00–22:00, as covered_spans actually returns
# it: touching spans are MERGED there (start <= previous end), so the two shifts arrive
# as one continuous 06:00–22:00 span. Writing them as two tuples here would test a shape
# the service never produces.
TWO_SHIFT = [(360, 1320)]
# A resource with a gap between shifts stays two spans: 06:00–13:00 and 14:00–22:00.
SPLIT_SHIFT = [(360, 780), (840, 1320)]
DAY_SHIFT = [(360, 840)]
NIGHT_ONLY = [(1320, 1440)]


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 1, hour, minute)


class TestShiftIntoSpan:
    """Where a wrongly placed booking should go."""

    def test_a_booking_before_opening_moves_to_the_start(self):
        """The case that motivated the whole feature: 03:00 against a day shift."""
        result = shift_into_span(_at(3), _at(6), DAY_SHIFT)
        assert result == _at(6)

    def test_a_booking_after_closing_moves_back_into_the_window(self):
        result = shift_into_span(_at(20), _at(22), DAY_SHIFT)
        assert result == _at(6)

    def test_a_booking_already_inside_gets_no_suggestion(self):
        """Zero-shift suggestions would look like a fix for a different conflict."""
        assert shift_into_span(_at(8), _at(12), DAY_SHIFT) is None

    def test_a_booking_exactly_filling_the_window_gets_no_suggestion(self):
        assert shift_into_span(_at(6), _at(14), DAY_SHIFT) is None

    def test_the_nearest_span_wins_not_the_earliest(self):
        """Smallest change that fixes the problem.

        A booking at 13:00 that does not fit before 14:00 belongs in the afternoon
        shift, not pushed back to 06:00 just because that span comes first.
        """
        result = shift_into_span(_at(13), _at(19), SPLIT_SHIFT)
        assert result == _at(14)

    def test_a_booking_longer_than_every_span_gets_no_suggestion(self):
        """Inventing a shift that does not resolve the violation is worse than none."""
        assert shift_into_span(_at(2), _at(14), DAY_SHIFT) is None

    def test_no_windows_means_no_suggestion(self):
        assert shift_into_span(_at(3), _at(5), []) is None

    def test_a_booking_crossing_midnight_is_left_alone(self):
        """Spans belong to the day a shift STARTS on.

        Relocating a wrapping booking would have to re-derive its tail against the
        next day's spans, which is a different calculation — guessing would produce a
        suggestion that does not actually fix anything.
        """
        result = shift_into_span(
            datetime(2026, 6, 1, 23, 0), datetime(2026, 6, 2, 2, 0), NIGHT_ONLY
        )
        assert result is None

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
        result = shift_into_span(_at(3), _at(4), [(450, 900)])
        assert result == _at(7, 30)
