"""Tests for :mod:`app.services.qualification`.

Every rule here is a refusal, and each one could plausibly have been written the other way.
The tests exist to pin which direction was chosen and why, because all four wrong choices
fail silently: they let somebody be planned for work they are not qualified for, and nothing
in the system objects.

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date

from app.services.qualification import (
    HeldQualification,
    covers,
    expires_within,
    meets_level,
    satisfies,
)

MARCH = date(2026, 3, 1)
JUNE = date(2026, 6, 1)
JUNE_END = date(2026, 6, 30)
JULY = date(2026, 7, 1)


class TestCovers:
    """Validity against the WORK, not against today."""

    def test_an_unbounded_qualification_covers_anything(self):
        """A trade learned once does not expire; requiring dates would force operators
        to invent them."""
        assert covers(HeldQualification(), JUNE, JULY) is True

    def test_a_qualification_expiring_after_the_work_covers_it(self):
        held = HeldQualification(valid_until=date(2026, 12, 31))
        assert covers(held, JUNE, JUNE_END) is True

    def test_a_qualification_expiring_before_the_work_does_not(self):
        """The case the whole feature exists for: a certificate lapsing in March does
        not cover a job planned for June, and asking "is it valid today" would say yes.
        """
        held = HeldQualification(valid_until=MARCH)
        assert covers(held, JUNE, JUNE_END) is False

    def test_a_qualification_lapsing_mid_job_fails_the_whole_job(self):
        """Not half of it. The point of an expiry date is that work after it is not
        covered, and a person cannot be half-allowed to weld."""
        held = HeldQualification(valid_until=date(2026, 6, 15))
        assert covers(held, JUNE, JUNE_END) is False

    def test_a_qualification_starting_after_the_work_does_not_cover_it(self):
        held = HeldQualification(valid_from=JULY)
        assert covers(held, JUNE, JUNE_END) is False

    def test_a_qualification_starting_exactly_on_the_first_day_covers_it(self):
        """The bounds are inclusive: a certificate issued on the start date is valid
        that day."""
        held = HeldQualification(valid_from=JUNE, valid_until=JUNE_END)
        assert covers(held, JUNE, JUNE_END) is True

    def test_an_unknown_span_is_treated_as_covered(self):
        """Refusing on missing information would turn every assignment whose dates
        cannot be resolved into a skill mismatch — a different problem, reported in the
        wrong place."""
        held = HeldQualification(valid_until=MARCH)
        assert covers(held, None, None) is True


class TestMeetsLevel:
    """An unrecorded level is not evidence of being good enough."""

    def test_no_minimum_is_always_met(self):
        assert meets_level(HeldQualification(), None) is True

    def test_a_sufficient_level_is_met(self):
        assert meets_level(HeldQualification(level=4), 3) is True

    def test_an_exact_level_is_met(self):
        assert meets_level(HeldQualification(level=3), 3) is True

    def test_an_insufficient_level_is_not_met(self):
        assert meets_level(HeldQualification(level=2), 3) is False

    def test_an_unrecorded_level_does_not_meet_a_minimum(self):
        """NULL means nobody assessed it. Reading it in the resource's favour would be
        the wrong direction for a check that exists to keep unqualified people off a
        task."""
        assert meets_level(HeldQualification(level=None), 3) is False

    def test_level_one_and_no_level_are_different_statements(self):
        """The first was assessed as lowest; the second was not assessed."""
        assert meets_level(HeldQualification(level=1), 1) is True
        assert meets_level(HeldQualification(level=None), 1) is False


class TestSatisfies:
    """Both conditions together."""

    def test_valid_and_high_enough_passes(self):
        held = HeldQualification(valid_until=date(2026, 12, 31), level=4)
        assert satisfies(held, 3, JUNE, JUNE_END) is True

    def test_high_enough_but_expired_fails(self):
        held = HeldQualification(valid_until=MARCH, level=5)
        assert satisfies(held, 3, JUNE, JUNE_END) is False

    def test_valid_but_too_low_fails(self):
        held = HeldQualification(valid_until=date(2026, 12, 31), level=2)
        assert satisfies(held, 3, JUNE, JUNE_END) is False

    def test_an_unqualified_requirement_passes_a_bare_qualification(self):
        assert satisfies(HeldQualification(), None, JUNE, JUNE_END) is True


class TestExpiresWithin:
    """The warning before the expiry bites."""

    def test_an_unbounded_qualification_never_expires(self):
        assert expires_within(HeldQualification(), JUNE, 90) is False

    def test_a_qualification_lapsing_inside_the_window_is_reported(self):
        held = HeldQualification(valid_until=date(2026, 6, 20))
        assert expires_within(held, JUNE, 30) is True

    def test_a_qualification_lapsing_outside_the_window_is_not(self):
        held = HeldQualification(valid_until=date(2026, 9, 1))
        assert expires_within(held, JUNE, 30) is False

    def test_an_already_expired_qualification_counts_as_expiring(self):
        """A "needs attention" list that silently drops the ones already past is worse
        than one that includes them."""
        held = HeldQualification(valid_until=MARCH)
        assert expires_within(held, JUNE, 30) is True

    def test_the_boundary_day_is_included(self):
        held = HeldQualification(valid_until=date(2026, 7, 1))
        assert expires_within(held, JUNE, 30) is True
