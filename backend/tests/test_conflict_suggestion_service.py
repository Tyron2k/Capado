"""Tests for :mod:`app.services.conflict_suggestion_service`.

Covers the resolution suggestions for personal and infrastructure conflicts:

- reduce_allocation respects the resource's actual availability (part-time
  ceiling), not a blanket 100%.
- No reduce_allocation when available_percent is 0 (full absence day).
- No reduce_allocation when the assignment is at or below 20%.
- swap_resource uses the minimum headroom across the entire period (not average).
- swap_resource skips non-working days rather than treating them as zero.
- Skill matching gates swap candidates.
- Fallback to assigned resource's skills when work package has no requirements.
- shift_forward / shift_backward respect the 30-day bound.
- Infrastructure path is distinct from personal path.

No database: the service is built through :meth:`ConflictSuggestionService.from_data`,
a test seam modeled after ``WorkingTimeService.from_data``.
All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.models.absence import Absence, AbsenceReason
from app.models.assignment import Assignment
from app.models.calendar import WorkWeekProfile
from app.models.conflict import Conflict, ConflictAssignment, ConflictCause
from app.models.resource import (
    InfrastructureResource,
    PersonalResource,
    ResourceType,
)
from app.services.conflict_suggestion_service import (
    ConflictSuggestionService,
    ResolutionSuggestion,
    _min_headroom_percent,
)
from app.services.working_time_service import (
    NORMATIVE_DAY_MINUTES,
    WorkingTimeService,
    minutes_to_percent,
    percent_to_minutes,
)

# 2026-06-01 is a Monday; the week runs Mon 1st through Sun 7th.
MONDAY = date(2026, 6, 1)
TUESDAY = date(2026, 6, 2)
WEDNESDAY = date(2026, 6, 3)
THURSDAY = date(2026, 6, 4)
FRIDAY = date(2026, 6, 5)
SATURDAY = date(2026, 6, 6)
SUNDAY = date(2026, 6, 7)

RESOURCE_ID = UUID("11111111-1111-1111-1111-111111111111")
CANDIDATE_ID = UUID("22222222-2222-2222-2222-222222222222")
SITE_ID = UUID("33333333-3333-3333-3333-333333333333")

SKILL_A = UUID("aaaa0001-0001-0001-0001-000000000001")
SKILL_B = UUID("aaaa0002-0002-0002-0002-000000000002")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_time_profile() -> WorkWeekProfile:
    """Monday to Friday eight hours, weekend free."""
    return WorkWeekProfile(id=uuid4(), name="Standard 5-Tage 8 h", is_default=True)


def _part_time_profile() -> WorkWeekProfile:
    """Thirty hours: Monday to Thursday 7.5 h, Friday off."""
    return WorkWeekProfile(
        id=uuid4(),
        name="Teilzeit 30 h Mo-Do",
        monday_minutes=450,
        tuesday_minutes=450,
        wednesday_minutes=450,
        thursday_minutes=450,
        friday_minutes=0,
        saturday_minutes=0,
        sunday_minutes=0,
    )


def _working_time(
    *,
    resource_ids: list[UUID] | None = None,
    profile: WorkWeekProfile | None = None,
    absences: dict[UUID, list[Absence]] | None = None,
) -> WorkingTimeService:
    """Build a WorkingTimeService via from_data for test resources."""
    profile = profile or _full_time_profile()
    rids = resource_ids or [RESOURCE_ID, CANDIDATE_ID]
    sites = dict.fromkeys(rids, SITE_ID)
    return WorkingTimeService.from_data(
        default_profile=profile,
        profiles={profile.id: profile},
        sites=sites,
        holidays={},
        absences=absences or {},
        windows={},
    )


def _personal_assignment(
    *,
    resource_id: UUID = RESOURCE_ID,
    start: date = MONDAY,
    end: date = FRIDAY,
    percent: float = 100.0,
    wp_id: UUID | None = None,
    id: UUID | None = None,
) -> Assignment:
    return Assignment(
        id=id or uuid4(),
        resource_id=resource_id,
        resource_type=ResourceType.personal,
        work_package_id=wp_id or uuid4(),
        start_date=start,
        end_date=end,
        allocation_percent=percent,
    )


def _infra_assignment(
    *,
    resource_id: UUID = RESOURCE_ID,
    start: datetime | None = None,
    end: datetime | None = None,
    wp_id: UUID | None = None,
    id: UUID | None = None,
) -> Assignment:
    return Assignment(
        id=id or uuid4(),
        resource_id=resource_id,
        resource_type=ResourceType.infrastructure,
        work_package_id=wp_id or uuid4(),
        start_at=start or datetime(2026, 6, 1, 8, 0),
        end_at=end or datetime(2026, 6, 5, 17, 0),
    )


def _conflict(
    *,
    resource_id: UUID = RESOURCE_ID,
    resource_type: ResourceType = ResourceType.personal,
    start: date = MONDAY,
    end: date = FRIDAY,
    total_assigned_percent: float = 120.0,
    available_percent: float = 100.0,
    id: UUID | None = None,
) -> Conflict:
    return Conflict(
        id=id or uuid4(),
        resource_id=resource_id,
        resource_type=resource_type,
        cause=ConflictCause.over_allocation,
        start_date=start,
        end_date=end,
        total_assigned_percent=total_assigned_percent,
        available_percent=available_percent,
    )


def _absence(
    start: date,
    end: date,
    percent: float = 100.0,
    resource_id: UUID = RESOURCE_ID,
) -> Absence:
    return Absence(
        id=uuid4(),
        resource_id=resource_id,
        resource_type=ResourceType.personal,
        reason=AbsenceReason.planned,
        start_date=start,
        end_date=end,
        allocation_percent=percent,
    )


def _personal_resource(
    id: UUID = RESOURCE_ID,
    name: str = "Max Mustermann",
) -> PersonalResource:
    return PersonalResource(
        id=id,
        name=name,
        group_id=uuid4(),
        site_id=SITE_ID,
        is_active=True,
    )


def _infra_resource(
    id: UUID = RESOURCE_ID,
    name: str = "Kran 1",
) -> InfrastructureResource:
    return InfrastructureResource(
        id=id,
        name=name,
        group_id=uuid4(),
        site_id=SITE_ID,
        is_active=True,
    )


async def _get_suggestions(
    *,
    conflict: Conflict,
    assignments: list[Assignment],
    working_time: WorkingTimeService | None = None,
    personal_candidates: list[PersonalResource] | None = None,
    infra_candidates: list[InfrastructureResource] | None = None,
    candidate_skills: dict[UUID, set[UUID]] | None = None,
    wp_requirements: dict[UUID, set[UUID]] | None = None,
    resource_skills: dict[UUID, set[UUID]] | None = None,
    candidate_assignments: list[Assignment] | None = None,
    wp_names: dict[UUID, str] | None = None,
) -> list[ResolutionSuggestion]:
    """Build a service via from_data and call get_suggestions."""
    service = ConflictSuggestionService.from_data(
        conflict=conflict,
        assignments=assignments,
        working_time=working_time,
        personal_candidates=personal_candidates or [],
        infra_candidates=infra_candidates or [],
        candidate_skills=candidate_skills or {},
        wp_requirements=wp_requirements or {},
        resource_skills=resource_skills or {},
        candidate_assignments=candidate_assignments or [],
        wp_names=wp_names or {},
    )
    return await service.get_suggestions(conflict.id)


# ---------------------------------------------------------------------------
# reduce_allocation — part-time ceiling
# ---------------------------------------------------------------------------


class TestReduceAllocationPartTimeCeiling:
    """reduce_allocation must respect available_percent, not 100."""

    async def test_ceiling_matches_part_time_availability(self) -> None:
        """A part-time resource with available_percent=93.75 never gets a
        suggestion above that value.

        450 min / 480 min normative = 93.75%.
        """
        conflict = _conflict(available_percent=93.75)
        # Two assignments totaling >93.75 to trigger the conflict
        a1 = _personal_assignment(percent=60.0)
        a2 = _personal_assignment(percent=50.0)

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[a1, a2],
        )

        reduce = [s for s in results if s.type == "reduce_allocation"]
        assert len(reduce) == 2
        for s in reduce:
            assert s.new_allocation_percent is not None
            assert s.new_allocation_percent <= 93.75

    async def test_reduce_suggests_max_allowed_respecting_others(self) -> None:
        """Reducing one assignment: max_allowed = available - others."""
        conflict = _conflict(available_percent=93.75)
        # a1=60%, a2=50%; for a1: max_allowed = 93.75 - 50 = 43.75 → 43
        a1 = _personal_assignment(percent=60.0)
        a2 = _personal_assignment(percent=50.0)

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[a1, a2],
        )

        reduce_a1 = [
            s
            for s in results
            if s.type == "reduce_allocation" and s.assignment_id == a1.id
        ]
        assert len(reduce_a1) == 1
        assert (
            reduce_a1[0].new_allocation_percent == 44.0
        )  # max(93.75 - 50, 10) → 43.75 → round → 44


class TestReduceAllocationZeroAvailability:
    """No reduce_allocation when available_percent is 0 (absence day)."""

    async def test_no_suggestion_when_fully_absent(self) -> None:
        """A day fully covered by absence has no capacity to reduce into."""
        conflict = _conflict(available_percent=0.0)
        a = _personal_assignment(percent=80.0)

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[a],
        )

        reduce = [s for s in results if s.type == "reduce_allocation"]
        assert reduce == []


class TestReduceAllocationLowPercent:
    """No reduce_allocation when assignment is at or below 20%."""

    async def test_no_suggestion_at_twenty_percent(self) -> None:
        conflict = _conflict(available_percent=100.0)
        a = _personal_assignment(percent=20.0)

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[a],
        )

        reduce = [s for s in results if s.type == "reduce_allocation"]
        assert reduce == []

    async def test_no_suggestion_below_twenty_percent(self) -> None:
        conflict = _conflict(available_percent=100.0)
        a = _personal_assignment(percent=15.0)

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[a],
        )

        reduce = [s for s in results if s.type == "reduce_allocation"]
        assert reduce == []


# ---------------------------------------------------------------------------
# swap_resource — minimum headroom rule
# ---------------------------------------------------------------------------


class TestSwapResourceMinimumHeadroom:
    """swap_resource rejects candidates without headroom on ALL days."""

    async def test_candidate_rejected_when_headroom_insufficient_on_one_day(
        self,
    ) -> None:
        """A candidate with room on 4 of 5 days (Mon-Thu free, Fri booked)
        cannot take a 5-day assignment."""
        profile = _full_time_profile()
        # Candidate has an existing assignment only on Friday at 80%
        candidate_existing = _personal_assignment(
            resource_id=CANDIDATE_ID, start=FRIDAY, end=FRIDAY, percent=80.0
        )
        wt = _working_time(resource_ids=[RESOURCE_ID, CANDIDATE_ID], profile=profile)
        conflict = _conflict(start=MONDAY, end=FRIDAY, available_percent=100.0)
        assignment = _personal_assignment(percent=50.0)

        candidate = _personal_resource(id=CANDIDATE_ID, name="Anna Stein")

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
            working_time=wt,
            personal_candidates=[candidate],
            candidate_assignments=[candidate_existing],
        )

        swap = [s for s in results if s.type == "swap_resource"]
        # Candidate has only 20% headroom on Friday (100 - 80) < 50% needed
        assert swap == []

    async def test_candidate_accepted_when_headroom_sufficient_all_days(self) -> None:
        """A candidate with enough headroom every working day is accepted."""
        profile = _full_time_profile()
        # Candidate has an existing assignment Mon-Fri at 30%
        candidate_existing = _personal_assignment(
            resource_id=CANDIDATE_ID, start=MONDAY, end=FRIDAY, percent=30.0
        )
        wt = _working_time(resource_ids=[RESOURCE_ID, CANDIDATE_ID], profile=profile)
        conflict = _conflict(start=MONDAY, end=FRIDAY, available_percent=100.0)
        assignment = _personal_assignment(percent=50.0)  # needs 50%

        candidate = _personal_resource(id=CANDIDATE_ID, name="Anna Stein")

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
            working_time=wt,
            personal_candidates=[candidate],
            candidate_assignments=[candidate_existing],
        )

        swap = [s for s in results if s.type == "swap_resource"]
        # Headroom = 100 - 30 = 70% every day, >= 50% needed
        assert len(swap) == 1
        assert swap[0].target_resource_id == CANDIDATE_ID


class TestSwapResourceSkipsNonWorkingDays:
    """Non-working days are skipped, not counted as zero headroom."""

    async def test_weekend_does_not_block_candidate(self) -> None:
        """A conflict period spanning Saturday/Sunday does not block a candidate
        who has headroom on all working days."""
        profile = _full_time_profile()
        wt = _working_time(resource_ids=[RESOURCE_ID, CANDIDATE_ID], profile=profile)
        # Conflict spans Mon–Sun, including the weekend
        conflict = _conflict(start=MONDAY, end=SUNDAY, available_percent=100.0)
        assignment = _personal_assignment(percent=50.0, start=MONDAY, end=SUNDAY)

        candidate = _personal_resource(id=CANDIDATE_ID, name="Anna Stein")

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
            working_time=wt,
            personal_candidates=[candidate],
            candidate_assignments=[],
        )

        swap = [s for s in results if s.type == "swap_resource"]
        # Candidate has 100% headroom on Mon-Fri, weekend is skipped
        assert len(swap) == 1
        assert swap[0].target_resource_id == CANDIDATE_ID


# ---------------------------------------------------------------------------
# swap_resource — skill matching
# ---------------------------------------------------------------------------


class TestSwapResourceSkillMatching:
    """Skill matching gates candidates."""

    async def test_candidate_lacking_required_skill_is_rejected(self) -> None:
        """A candidate without a required skill is never suggested."""
        profile = _full_time_profile()
        wt = _working_time(resource_ids=[RESOURCE_ID, CANDIDATE_ID], profile=profile)
        conflict = _conflict(start=MONDAY, end=FRIDAY, available_percent=100.0)
        wp_id = uuid4()
        assignment = _personal_assignment(percent=50.0, wp_id=wp_id)

        candidate = _personal_resource(id=CANDIDATE_ID, name="Anna Stein")

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
            working_time=wt,
            personal_candidates=[candidate],
            candidate_assignments=[],
            # Work package requires SKILL_A and SKILL_B
            wp_requirements={wp_id: {SKILL_A, SKILL_B}},
            # Candidate only has SKILL_A
            candidate_skills={CANDIDATE_ID: {SKILL_A}},
        )

        swap = [s for s in results if s.type == "swap_resource"]
        assert swap == []

    async def test_candidate_with_all_required_skills_is_accepted(self) -> None:
        """A candidate meeting all skill requirements is suggested."""
        profile = _full_time_profile()
        wt = _working_time(resource_ids=[RESOURCE_ID, CANDIDATE_ID], profile=profile)
        conflict = _conflict(start=MONDAY, end=FRIDAY, available_percent=100.0)
        wp_id = uuid4()
        assignment = _personal_assignment(percent=50.0, wp_id=wp_id)

        candidate = _personal_resource(id=CANDIDATE_ID, name="Anna Stein")

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
            working_time=wt,
            personal_candidates=[candidate],
            candidate_assignments=[],
            wp_requirements={wp_id: {SKILL_A, SKILL_B}},
            candidate_skills={CANDIDATE_ID: {SKILL_A, SKILL_B}},
        )

        swap = [s for s in results if s.type == "swap_resource"]
        assert len(swap) == 1
        assert swap[0].target_resource_id == CANDIDATE_ID


class TestSwapResourceFallbackToResourceSkills:
    """When a work package has no requirements, use the assigned resource's skills."""

    async def test_fallback_uses_currently_assigned_resource_skills(self) -> None:
        """A candidate must match the assigned resource's skills when the work
        package defines no requirements."""
        profile = _full_time_profile()
        wt = _working_time(resource_ids=[RESOURCE_ID, CANDIDATE_ID], profile=profile)
        conflict = _conflict(start=MONDAY, end=FRIDAY, available_percent=100.0)
        wp_id = uuid4()
        assignment = _personal_assignment(
            percent=50.0, wp_id=wp_id, resource_id=RESOURCE_ID
        )

        candidate = _personal_resource(id=CANDIDATE_ID, name="Anna Stein")

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
            working_time=wt,
            personal_candidates=[candidate],
            candidate_assignments=[],
            # No wp_requirements for this wp_id → triggers fallback
            wp_requirements={},
            # Assigned resource (RESOURCE_ID) has SKILL_A
            resource_skills={RESOURCE_ID: {SKILL_A}},
            # Candidate lacks SKILL_A
            candidate_skills={CANDIDATE_ID: set()},
        )

        swap = [s for s in results if s.type == "swap_resource"]
        assert swap == []

    async def test_fallback_candidate_with_matching_skills_accepted(self) -> None:
        """When falling back, a candidate with the same skills is accepted."""
        profile = _full_time_profile()
        wt = _working_time(resource_ids=[RESOURCE_ID, CANDIDATE_ID], profile=profile)
        conflict = _conflict(start=MONDAY, end=FRIDAY, available_percent=100.0)
        wp_id = uuid4()
        assignment = _personal_assignment(
            percent=50.0, wp_id=wp_id, resource_id=RESOURCE_ID
        )

        candidate = _personal_resource(id=CANDIDATE_ID, name="Anna Stein")

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
            working_time=wt,
            personal_candidates=[candidate],
            candidate_assignments=[],
            wp_requirements={},
            resource_skills={RESOURCE_ID: {SKILL_A}},
            candidate_skills={CANDIDATE_ID: {SKILL_A}},
        )

        swap = [s for s in results if s.type == "swap_resource"]
        assert len(swap) == 1
        assert swap[0].target_resource_id == CANDIDATE_ID


# ---------------------------------------------------------------------------
# shift_forward / shift_backward — 30-day bound
# ---------------------------------------------------------------------------


class TestShiftBounds:
    """Shift suggestions are bounded to 30 days."""

    async def test_shift_forward_within_30_days_emitted(self) -> None:
        """An assignment starting 10 days before conflict end gets a shift suggestion."""
        conflict_end = MONDAY + timedelta(days=9)
        conflict = _conflict(start=MONDAY, end=conflict_end, available_percent=100.0)
        # Assignment starts on MONDAY
        assignment = _personal_assignment(
            start=MONDAY, end=MONDAY + timedelta(days=14), percent=60.0
        )

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
        )

        fwd = [s for s in results if s.type == "shift_forward"]
        assert len(fwd) == 1
        assert fwd[0].shift_days is not None
        assert 0 < fwd[0].shift_days <= 30

    async def test_shift_forward_beyond_30_days_not_emitted(self) -> None:
        """If shifting past the conflict end would exceed 30 days, no suggestion."""
        # Conflict ends 40 days after the assignment starts
        conflict_end = MONDAY + timedelta(days=40)
        conflict = _conflict(start=MONDAY, end=conflict_end, available_percent=100.0)
        assignment = _personal_assignment(
            start=MONDAY, end=MONDAY + timedelta(days=5), percent=60.0
        )

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
        )

        fwd = [s for s in results if s.type == "shift_forward"]
        assert fwd == []

    async def test_shift_backward_within_30_days_emitted(self) -> None:
        """An assignment ending a few days after conflict start gets a backward suggestion."""
        # Conflict starts at MONDAY, assignment must end before MONDAY
        conflict = _conflict(start=MONDAY, end=FRIDAY, available_percent=100.0)
        # Assignment: Wed–next Mon (5 days). Shifted backward end = Sun (day before Mon)
        assignment = _personal_assignment(
            start=WEDNESDAY, end=WEDNESDAY + timedelta(days=4), percent=60.0
        )

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
        )

        bwd = [s for s in results if s.type == "shift_backward"]
        assert len(bwd) == 1
        assert bwd[0].shift_days is not None
        assert bwd[0].shift_days < 0
        assert abs(bwd[0].shift_days) <= 30

    async def test_shift_backward_beyond_30_days_not_emitted(self) -> None:
        """If the backward shift exceeds 30 days, no suggestion."""
        # Assignment is a long one (40 days); to shift it entirely before
        # the conflict start would require > 30 days of backward movement.
        conflict = _conflict(start=MONDAY, end=FRIDAY, available_percent=100.0)
        # Assignment starts on MONDAY and is 40 days long.
        # new_end = conflict.start - 1 = SUNDAY before
        # new_start = new_end - 40 = 40 days before SUNDAY
        # shift = assignment.start - new_start = MONDAY - (SUNDAY - 40) = 41 days
        assignment = _personal_assignment(
            start=MONDAY, end=MONDAY + timedelta(days=40), percent=60.0
        )

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
        )

        bwd = [s for s in results if s.type == "shift_backward"]
        assert bwd == []


# ---------------------------------------------------------------------------
# Infrastructure path
# ---------------------------------------------------------------------------


class TestInfrastructurePath:
    """Infrastructure conflicts use the _suggest_for_infrastructure path."""

    async def test_infra_shift_forward_emitted(self) -> None:
        """An infrastructure assignment gets a shift_forward suggestion."""
        conflict_end = date(2026, 6, 3)
        conflict = _conflict(
            resource_type=ResourceType.infrastructure,
            start=MONDAY,
            end=conflict_end,
            available_percent=100.0,
        )
        assignment = _infra_assignment(
            start=datetime(2026, 6, 1, 8, 0),
            end=datetime(2026, 6, 5, 17, 0),
        )

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
        )

        fwd = [s for s in results if s.type == "shift_forward"]
        assert len(fwd) == 1
        # Shift from June 1 to June 4 (day after conflict end) = 3 days
        assert fwd[0].shift_days == 3

    async def test_infra_swap_no_overlap(self) -> None:
        """An infrastructure swap is suggested when a candidate has no overlapping booking."""
        conflict = _conflict(
            resource_type=ResourceType.infrastructure,
            start=MONDAY,
            end=FRIDAY,
            available_percent=100.0,
        )
        assignment = _infra_assignment(
            start=datetime(2026, 6, 1, 8, 0),
            end=datetime(2026, 6, 5, 17, 0),
        )
        candidate = _infra_resource(id=CANDIDATE_ID, name="Kran 2")

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
            infra_candidates=[candidate],
            candidate_assignments=[],
        )

        swap = [s for s in results if s.type == "swap_resource"]
        assert len(swap) == 1
        assert swap[0].target_resource_id == CANDIDATE_ID

    async def test_infra_swap_rejected_when_overlapping(self) -> None:
        """An infrastructure candidate with an overlapping booking is rejected."""
        conflict = _conflict(
            resource_type=ResourceType.infrastructure,
            start=MONDAY,
            end=FRIDAY,
            available_percent=100.0,
        )
        assignment = _infra_assignment(
            start=datetime(2026, 6, 1, 8, 0),
            end=datetime(2026, 6, 5, 17, 0),
        )
        candidate = _infra_resource(id=CANDIDATE_ID, name="Kran 2")
        # Candidate already has an overlapping booking
        overlap = _infra_assignment(
            resource_id=CANDIDATE_ID,
            start=datetime(2026, 6, 3, 8, 0),
            end=datetime(2026, 6, 4, 17, 0),
        )

        results = await _get_suggestions(
            conflict=conflict,
            assignments=[assignment],
            infra_candidates=[candidate],
            candidate_assignments=[overlap],
        )

        swap = [s for s in results if s.type == "swap_resource"]
        assert swap == []


# ---------------------------------------------------------------------------
# _min_headroom_percent unit tests (module-level helper)
# ---------------------------------------------------------------------------


class TestMinHeadroomPercent:
    """Direct unit tests for _min_headroom_percent."""

    def test_full_time_no_assignments_returns_hundred(self) -> None:
        """Full-time resource with no load has 100% headroom."""
        wt = _working_time(resource_ids=[CANDIDATE_ID])
        result = _min_headroom_percent(wt, CANDIDATE_ID, [], MONDAY, FRIDAY)
        assert result == 100.0

    def test_single_assignment_reduces_headroom(self) -> None:
        """A 60% assignment leaves 40% headroom."""
        wt = _working_time(resource_ids=[CANDIDATE_ID])
        a = _personal_assignment(
            resource_id=CANDIDATE_ID, start=MONDAY, end=FRIDAY, percent=60.0
        )
        result = _min_headroom_percent(wt, CANDIDATE_ID, [a], MONDAY, FRIDAY)
        assert result == pytest.approx(40.0, abs=0.1)

    def test_period_with_only_non_working_days_returns_zero(self) -> None:
        """If the entire period is non-working, headroom is 0 (cannot schedule)."""
        wt = _working_time(resource_ids=[CANDIDATE_ID])
        result = _min_headroom_percent(wt, CANDIDATE_ID, [], SATURDAY, SUNDAY)
        assert result == 0.0
