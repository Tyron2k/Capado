"""Tests for :func:`app.services.unmet_requirements_service.compute_coverage`.

The rule this pins down is a domain rule, not an implementation detail: sixteen
hours of work are **not** interchangeable with two people for eight hours. Where a
job needs two people present at once — a blasting cabin staffed by two, a lift
taking two operators — spreading four people thinly covers nothing.

Before this function existed, coverage was always a sum of allocations, so four
people at 25% satisfied a requirement for two and the plan looked staffed while
the work could not happen.

No database. All data is inline and clearly fictional.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.models.work_package_requirement import RequirementMode
from app.services.unmet_requirements_service import compute_coverage

ALICE = UUID("aaaaaaaa-0000-0000-0000-000000000001")
BOB = UUID("bbbbbbbb-0000-0000-0000-000000000002")
CARL = UUID("cccccccc-0000-0000-0000-000000000003")
DORA = UUID("dddddddd-0000-0000-0000-000000000004")


class TestHeadcountMode:
    """A body counts once, and only when it is actually there."""

    def test_no_allocations_cover_nothing(self):
        """An unstaffed requirement is uncovered."""
        assert compute_coverage(RequirementMode.headcount, 100.0, []) == 0.0

    def test_two_full_people_cover_two(self):
        """The ordinary case."""
        allocations = [(ALICE, 100.0), (BOB, 100.0)]
        assert compute_coverage(RequirementMode.headcount, 100.0, allocations) == 2.0

    def test_four_quarter_people_cover_nothing(self):
        """The rule, stated directly.

        Four people at 25% sum to one FTE but nobody is present for the work, so
        a two-person requirement is covered zero — not one, and certainly not two.
        """
        allocations = [
            (ALICE, 25.0),
            (BOB, 25.0),
            (CARL, 25.0),
            (DORA, 25.0),
        ]
        assert compute_coverage(RequirementMode.headcount, 100.0, allocations) == 0.0

    def test_two_half_people_do_not_cover_one(self):
        """Two halves are not one body when full presence is required."""
        allocations = [(ALICE, 50.0), (BOB, 50.0)]
        assert compute_coverage(RequirementMode.headcount, 100.0, allocations) == 0.0

    def test_lowered_threshold_admits_partial_presence(self):
        """Where partial presence genuinely counts, the threshold says so."""
        allocations = [(ALICE, 50.0), (BOB, 50.0)]
        assert compute_coverage(RequirementMode.headcount, 50.0, allocations) == 2.0

    def test_allocation_just_below_the_threshold_does_not_count(self):
        """The threshold is inclusive of its own value and nothing under it."""
        allocations = [(ALICE, 49.9)]
        assert compute_coverage(RequirementMode.headcount, 50.0, allocations) == 0.0

    def test_one_person_counts_once_across_several_assignments(self):
        """Splitting the paperwork does not clone the person.

        Two assignments of the same resource on one work package are one body,
        which is what stops a requirement being satisfied by re-booking one
        person twice.
        """
        allocations = [(ALICE, 60.0), (ALICE, 40.0)]
        assert compute_coverage(RequirementMode.headcount, 50.0, allocations) == 1.0

    def test_over_full_allocation_still_counts_once(self):
        """A body is a body; over-allocation is a conflict, not extra coverage."""
        allocations = [(ALICE, 100.0), (ALICE, 100.0)]
        assert compute_coverage(RequirementMode.headcount, 100.0, allocations) == 1.0


class TestEffortMode:
    """Allocations sum, for work that genuinely parallelises."""

    def test_four_quarter_people_cover_one_fte(self):
        """The reading headcount mode rejects is exactly what this mode means."""
        allocations = [
            (ALICE, 25.0),
            (BOB, 25.0),
            (CARL, 25.0),
            (DORA, 25.0),
        ]
        assert compute_coverage(RequirementMode.effort_fte, 100.0, allocations) == 1.0

    def test_two_half_people_cover_one(self):
        """Two halves are one FTE."""
        allocations = [(ALICE, 50.0), (BOB, 50.0)]
        assert compute_coverage(RequirementMode.effort_fte, 100.0, allocations) == 1.0

    def test_threshold_is_ignored(self):
        """min_allocation_percent has no meaning when effort is divisible."""
        allocations = [(ALICE, 10.0)]
        assert compute_coverage(RequirementMode.effort_fte, 100.0, allocations) == 0.1

    def test_same_resource_sums_across_assignments(self):
        """In effort mode the unit is time, so two assignments add up."""
        allocations = [(ALICE, 60.0), (ALICE, 40.0)]
        assert compute_coverage(RequirementMode.effort_fte, 100.0, allocations) == 1.0


class TestModesDisagree:
    """The two modes must not be silently interchangeable."""

    def test_same_input_gives_different_coverage(self):
        """This difference is the entire point of the mode field."""
        allocations = [(uuid4(), 50.0), (uuid4(), 50.0)]
        headcount = compute_coverage(RequirementMode.headcount, 100.0, allocations)
        effort = compute_coverage(RequirementMode.effort_fte, 100.0, allocations)
        assert headcount == 0.0
        assert effort == 1.0
        assert headcount != effort

    def test_headcount_is_never_more_optimistic_than_effort(self):
        """Headcount is the safe default: it cannot hide a gap effort would show.

        With the threshold at 100% a counted body contributes exactly the 1.0 it
        contributes in effort mode, and an uncounted one contributes less than the
        fraction effort would credit it with.
        """
        allocations = [(ALICE, 100.0), (BOB, 30.0), (CARL, 100.0)]
        headcount = compute_coverage(RequirementMode.headcount, 100.0, allocations)
        effort = compute_coverage(RequirementMode.effort_fte, 100.0, allocations)
        assert headcount <= effort
