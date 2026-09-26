"""Tests for :meth:`ConflictService.refresh_conflicts` orchestration.

The arithmetic (available minutes, demand gating) is tested in
``test_working_time_service.py`` and ``test_conflict_window_violations.py``.
This file covers the wiring that ``refresh_conflicts`` performs on top: the
boundary sweep, span formation, grouping of consecutive conflict days into
periods, cause discriminator, and persistence.

No database: uses :meth:`ConflictService.from_data`, a test seam modeled after
``WorkingTimeService.from_data``. All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date, timedelta
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
from app.services.conflict_service import ConflictService
from app.services.time_zone import local_wall_time_to_utc, planning_zone
from app.services.working_time_service import (
    NORMATIVE_DAY_MINUTES,
    WorkingTimeService,
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
SITE_ID = UUID("22222222-2222-2222-2222-222222222222")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_time_profile() -> WorkWeekProfile:
    return WorkWeekProfile(id=uuid4(), name="Standard 5-Tage 8 h", is_default=True)


def _part_time_profile() -> WorkWeekProfile:
    """30 h / week: Mon–Thu 450 min, Fri off."""
    return WorkWeekProfile(
        id=uuid4(),
        name="Teilzeit 30 h",
        monday_minutes=450,
        tuesday_minutes=450,
        wednesday_minutes=450,
        thursday_minutes=450,
        friday_minutes=0,
        saturday_minutes=0,
        sunday_minutes=0,
    )


def _personal_assignment(
    *,
    resource_id: UUID = RESOURCE_ID,
    start: date,
    end: date,
    percent: float = 100.0,
    id: UUID | None = None,
) -> Assignment:
    return Assignment(
        id=id or uuid4(),
        resource_id=resource_id,
        resource_type=ResourceType.personal,
        work_package_id=uuid4(),
        start_date=start,
        end_date=end,
        allocation_percent=percent,
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


class _FakeSession:
    """Async session double for ConflictService orchestration tests.

    Serves preloaded resources, assignments, and records added/flushed objects.
    Tracks commits and deletions.
    """

    def __init__(
        self,
        *,
        resources: dict[UUID, PersonalResource | InfrastructureResource] | None = None,
        assignments: list[Assignment] | None = None,
    ) -> None:
        self._resources = resources or {}
        self._assignments = assignments or []
        self.added: list[Any] = []
        self.commits = 0
        self._deleted_resource_ids: set[UUID] = set()
        self._flush_counter = 0

    async def get(self, model: type, pk: UUID) -> Any:
        if model in (PersonalResource, InfrastructureResource):
            obj = self._resources.get(pk)
            if obj is not None and isinstance(obj, model):
                return obj
        return None

    async def execute(self, statement: Any) -> _FakeResult:
        """Route selects for assignments and conflicts."""
        # Determine what this query is about by inspecting the statement's
        # column descriptions (good-enough heuristic for the double).
        stmt_str = str(statement)
        if "assignments" in stmt_str and "resource_id" in stmt_str:
            # select(Assignment).where(Assignment.resource_id == ...)
            matching = [
                a
                for a in self._assignments
                if a.resource_id in self._active_resource_filter(statement)
            ]
            return _FakeResult(matching)
        if "conflicts" in stmt_str:
            # delete or select for conflict cleanup — return empty
            return _FakeResult([])
        return _FakeResult([])

    def _active_resource_filter(self, statement: Any) -> set[UUID]:
        """Extract resource_id filter from a select statement."""
        # Since we control inputs, just return all known resource ids
        return set(self._resources.keys())

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self._flush_counter += 1
        # Assign an id to any Conflict that was just added (simulates DB)
        for obj in self.added:
            if isinstance(obj, Conflict) and obj.id is None:
                obj.id = uuid4()

    async def commit(self) -> None:
        self.commits += 1


class _FakeResult:
    """Wraps a list to behave like SQLAlchemy's Result for .scalars().all()."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._items


def _working_time(
    *,
    profile: WorkWeekProfile | None = None,
    absences: list[Absence] | None = None,
) -> WorkingTimeService:
    """Build a WorkingTimeService via from_data for one fictional resource."""
    profile = profile or _full_time_profile()
    return WorkingTimeService.from_data(
        default_profile=profile,
        profiles={profile.id: profile},
        sites={RESOURCE_ID: SITE_ID},
        holidays={},
        absences={RESOURCE_ID: absences} if absences else {},
        windows={},
    )


def _service(
    *,
    resource: PersonalResource | InfrastructureResource | None = None,
    assignments: list[Assignment] | None = None,
    working_time: WorkingTimeService | None = None,
    profile: WorkWeekProfile | None = None,
    absences: list[Absence] | None = None,
) -> tuple[ConflictService, _FakeSession]:
    """Build a ConflictService with from_data and a matching FakeSession."""
    if resource is None:
        resource = PersonalResource(
            id=RESOURCE_ID,
            name="Max Mustermann",
            group_id=uuid4(),
            site_id=SITE_ID,
        )
    assignments = assignments or []
    session = _FakeSession(
        resources={resource.id: resource},
        assignments=assignments,
    )
    wt = working_time or _working_time(profile=profile, absences=absences)
    svc = ConflictService.from_data(
        session=session,
        working_time=wt,
        resources={resource.id: resource},
        assignments={resource.id: assignments},
    )
    return svc, session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSingleAssignmentWithinCapacity:
    """A single assignment within capacity produces no conflict."""

    async def test_hypothetical_periods_do_not_persist(self) -> None:
        existing = _personal_assignment(start=MONDAY, end=FRIDAY, percent=50.0)
        proposed = _personal_assignment(start=MONDAY, end=FRIDAY, percent=60.0)
        svc, session = _service(assignments=[existing])

        before = await svc.calculate_periods(RESOURCE_ID)
        after = await svc.calculate_periods(
            RESOURCE_ID, assignments=[existing, proposed]
        )

        assert before == []
        assert len(after) == 1
        assert after[0].total_assigned_percent == pytest.approx(110.0)
        assert session.commits == 0
        assert session.added == []

    async def test_one_assignment_at_fifty_percent(self) -> None:
        a = _personal_assignment(start=MONDAY, end=FRIDAY, percent=50.0)
        svc, session = _service(assignments=[a])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert conflicts == []
        assert session.commits == 1

    async def test_one_assignment_at_hundred_percent(self) -> None:
        """100% on a full-time resource is exactly at capacity, not over."""
        a = _personal_assignment(start=MONDAY, end=FRIDAY, percent=100.0)
        svc, session = _service(assignments=[a])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert conflicts == []


class TestOverlappingAssignmentsProduceConflict:
    """Two overlapping assignments summing past available produce a conflict."""

    async def test_two_at_sixty_percent_overlap(self) -> None:
        a1 = _personal_assignment(start=MONDAY, end=WEDNESDAY, percent=60.0)
        a2 = _personal_assignment(start=MONDAY, end=WEDNESDAY, percent=60.0)
        svc, session = _service(assignments=[a1, a2])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.start_date == MONDAY
        assert c.end_date == WEDNESDAY
        assert c.cause == ConflictCause.over_allocation

    async def test_partial_overlap(self) -> None:
        """Only the overlapping days conflict, not the whole range."""
        a1 = _personal_assignment(start=MONDAY, end=WEDNESDAY, percent=60.0)
        a2 = _personal_assignment(start=WEDNESDAY, end=FRIDAY, percent=60.0)
        svc, session = _service(assignments=[a1, a2])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert len(conflicts) == 1
        c = conflicts[0]
        # Only Wednesday is the overlap day
        assert c.start_date == WEDNESDAY
        assert c.end_date == WEDNESDAY


class TestConsecutiveDaysMergeIntoPeriod:
    """Consecutive conflict days merge into one period; gaps split them."""

    async def test_consecutive_days_one_period(self) -> None:
        """Mon–Fri all conflicting → one period."""
        a1 = _personal_assignment(start=MONDAY, end=FRIDAY, percent=60.0)
        a2 = _personal_assignment(start=MONDAY, end=FRIDAY, percent=60.0)
        svc, _ = _service(assignments=[a1, a2])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert len(conflicts) == 1
        assert conflicts[0].start_date == MONDAY
        assert conflicts[0].end_date == FRIDAY

    async def test_gap_splits_into_two_periods(self) -> None:
        """Conflict Mon, gap Tue, conflict Wed → two periods."""
        # Only Monday conflicts (both active)
        a1 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0)
        a2 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0)
        # Only Wednesday conflicts (both active)
        a3 = _personal_assignment(start=WEDNESDAY, end=WEDNESDAY, percent=60.0)
        a4 = _personal_assignment(start=WEDNESDAY, end=WEDNESDAY, percent=60.0)
        svc, _ = _service(assignments=[a1, a2, a3, a4])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        # Same assignment ids → merge across gap (documented rule).
        # Different assignment ids → split.
        assert len(conflicts) == 2
        dates = sorted((c.start_date, c.end_date) for c in conflicts)
        assert dates == [(MONDAY, MONDAY), (WEDNESDAY, WEDNESDAY)]


class TestSameAssignmentsMergeAcrossGap:
    """Days sharing the same triggering assignments merge even across a gap."""

    async def test_same_cause_merges_despite_gap(self) -> None:
        """Mon and Wed conflict from the SAME pair of assignments → one period."""
        a1_id = uuid4()
        a2_id = uuid4()
        # Assignment 1 covers Mon and Wed but not Tue
        a1 = _personal_assignment(start=MONDAY, end=WEDNESDAY, percent=60.0, id=a1_id)
        # Assignment 2 also covers Mon and Wed but not Tue (same range, so
        # the sweep sees them both on Tue too — need a setup where Tue doesn't
        # conflict). Use three assignments: a1+a2 conflict on Mon, and a1+a2
        # conflict on Wed, but only a1 on Tue.
        # Cleaner: a1 covers Mon+Wed only, a2 covers Mon+Wed only.
        # Assignments are date ranges so we can't skip a day.
        # Instead: set allocation so Mon/Wed conflict but Tue doesn't.
        # Use the span-boundary mechanism: two non-overlapping pairs.
        a1 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0, id=a1_id)
        a2 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0, id=a2_id)
        # Same pair on Wednesday
        a3 = _personal_assignment(
            start=WEDNESDAY, end=WEDNESDAY, percent=60.0, id=a1_id
        )
        a4 = _personal_assignment(
            start=WEDNESDAY, end=WEDNESDAY, percent=60.0, id=a2_id
        )
        svc, _ = _service(assignments=[a1, a2, a3, a4])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        # Same assignment_ids on both days → merged into one period
        assert len(conflicts) == 1
        assert conflicts[0].start_date == MONDAY
        assert conflicts[0].end_date == WEDNESDAY


class TestPercentDerivedFromMinutes:
    """total_assigned_percent and available_percent are derived from minutes."""

    async def test_percents_reflect_minutes(self) -> None:
        """Two 60% assignments → 120% assigned against 100% available."""
        a1 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0)
        a2 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0)
        svc, _ = _service(assignments=[a1, a2])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert len(conflicts) == 1
        c = conflicts[0]
        # 120% of 480 = 576 min → minutes_to_percent(576) = 120.0
        assert c.total_assigned_percent == pytest.approx(120.0)
        # Full-time, no absence → 480 min → 100.0%
        assert c.available_percent == pytest.approx(100.0)


class TestCauseDiscriminator:
    """Cause is over_allocation for personal, booking_overlap for infra."""

    async def test_personal_cause(self) -> None:
        a1 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0)
        a2 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0)
        svc, _ = _service(assignments=[a1, a2])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert conflicts[0].cause == ConflictCause.over_allocation

    async def test_infrastructure_cause(self) -> None:
        from datetime import datetime

        infra_id = uuid4()
        resource = InfrastructureResource(
            id=infra_id, name="Halle A", group_id=uuid4(), site_id=SITE_ID
        )
        # Two overlapping infrastructure bookings (same day, same hours)
        a1 = Assignment(
            id=uuid4(),
            resource_id=infra_id,
            resource_type=ResourceType.infrastructure,
            work_package_id=uuid4(),
            start_at=local_wall_time_to_utc(datetime(2026, 6, 1, 8), planning_zone()),
            end_at=local_wall_time_to_utc(datetime(2026, 6, 1, 16), planning_zone()),
        )
        a2 = Assignment(
            id=uuid4(),
            resource_id=infra_id,
            resource_type=ResourceType.infrastructure,
            work_package_id=uuid4(),
            start_at=local_wall_time_to_utc(datetime(2026, 6, 1, 8), planning_zone()),
            end_at=local_wall_time_to_utc(datetime(2026, 6, 1, 16), planning_zone()),
        )
        wt = WorkingTimeService.from_data(
            default_profile=_full_time_profile(),
            profiles={},
            sites={infra_id: SITE_ID},
            holidays={},
            absences={},
            windows={},
        )
        session = _FakeSession(resources={infra_id: resource}, assignments=[a1, a2])
        svc = ConflictService.from_data(
            session=session,
            working_time=wt,
            resources={infra_id: resource},
            assignments={infra_id: [a1, a2]},
        )

        conflicts = await svc.refresh_conflicts(infra_id)

        assert len(conflicts) == 1
        assert conflicts[0].cause == ConflictCause.booking_overlap


class TestWeekendNoConflict:
    """A weekend inside an assignment range produces no conflict day."""

    async def test_assignment_spanning_weekend(self) -> None:
        """Mon–Sun at 60%×2 = 120%: only weekdays conflict."""
        a1 = _personal_assignment(start=MONDAY, end=SUNDAY, percent=60.0)
        a2 = _personal_assignment(start=MONDAY, end=SUNDAY, percent=60.0)
        svc, _ = _service(assignments=[a1, a2])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert len(conflicts) == 1
        c = conflicts[0]
        # Conflict covers Mon–Fri only (weekdays); Sat/Sun have 0 calendar
        # minutes, so demand is gated to 0 and they don't appear.
        assert c.start_date == MONDAY
        assert c.end_date == FRIDAY


class TestAbsenceDayConflicts:
    """An assignment on a day fully covered by an absence DOES conflict."""

    async def test_full_day_absence_causes_conflict(self) -> None:
        """Calendar 480, available 0, demand 480 → conflict."""
        absence = _absence(start=MONDAY, end=MONDAY, percent=100.0)
        a = _personal_assignment(start=MONDAY, end=MONDAY, percent=100.0)
        svc, _ = _service(assignments=[a], absences=[absence])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.start_date == MONDAY
        assert c.end_date == MONDAY
        # Available is 0% (0 minutes), assigned is 100% (480 minutes)
        assert c.available_percent == pytest.approx(0.0)
        assert c.total_assigned_percent == pytest.approx(100.0)


class TestPartTimeConflict:
    """A part-time resource booked at 100% conflicts."""

    async def test_part_time_at_hundred_percent(self) -> None:
        """450 min/day profile, 100% = 480 min demand → conflict."""
        profile = _part_time_profile()
        a = _personal_assignment(start=MONDAY, end=MONDAY, percent=100.0)
        svc, _ = _service(assignments=[a], profile=profile)

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert len(conflicts) == 1
        c = conflicts[0]
        # Available: 450/480 = 93.75%, Assigned: 480/480 = 100%
        assert c.available_percent == pytest.approx(450 / NORMATIVE_DAY_MINUTES * 100)
        assert c.total_assigned_percent == pytest.approx(100.0)


class TestExistingConflictsDeletedBeforeRecalculation:
    """Existing conflicts for the resource are deleted before recalculation."""

    async def test_delete_called_before_new_conflicts(self) -> None:
        """After refresh, only newly detected conflicts remain."""
        # First refresh creates a conflict
        a1 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0)
        a2 = _personal_assignment(start=MONDAY, end=MONDAY, percent=60.0)
        svc, session = _service(assignments=[a1, a2])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)
        assert len(conflicts) == 1

        # Second refresh with no overlap should produce no conflicts.
        # The service deletes old ones before recalculating.
        a3 = _personal_assignment(start=TUESDAY, end=TUESDAY, percent=50.0)
        session2 = _FakeSession(
            resources={
                RESOURCE_ID: PersonalResource(
                    id=RESOURCE_ID,
                    name="Max Mustermann",
                    group_id=uuid4(),
                    site_id=SITE_ID,
                )
            },
            assignments=[a3],
        )
        wt = _working_time()
        svc2 = ConflictService.from_data(
            session=session2,
            working_time=wt,
            resources={
                RESOURCE_ID: PersonalResource(
                    id=RESOURCE_ID,
                    name="Max Mustermann",
                    group_id=uuid4(),
                    site_id=SITE_ID,
                )
            },
            assignments={RESOURCE_ID: [a3]},
        )

        conflicts2 = await svc2.refresh_conflicts(RESOURCE_ID)
        assert conflicts2 == []
        assert session2.commits == 1


class TestNoAssignmentsNoConflicts:
    """A resource with no assignments produces no conflicts and still commits."""

    async def test_empty_assignments(self) -> None:
        svc, session = _service(assignments=[])

        conflicts = await svc.refresh_conflicts(RESOURCE_ID)

        assert conflicts == []
        assert session.commits == 1
