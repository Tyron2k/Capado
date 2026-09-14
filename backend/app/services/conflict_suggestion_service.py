"""Service for generating conflict resolution suggestions.

Analyzes a conflict and proposes concrete actions to resolve it:
- Shift assignment forward/backward by N days
- Reduce allocation percentage
- Swap to an available resource
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.assignment import Assignment
from app.models.conflict import Conflict, ConflictAssignment, ConflictCause
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.services.working_time_service import (
    WorkingTimeService,
    minutes_to_percent,
    percent_to_minutes,
)


@dataclass
class ResolutionSuggestion:
    """A single suggestion for resolving a conflict."""

    type: str
    """One of: shift_forward, shift_backward, reduce_allocation, swap_resource,
    shift_into_window."""

    assignment_id: UUID
    description: str
    # Type-specific payload
    shift_days: int | None = None
    new_allocation_percent: float | None = None
    target_resource_id: UUID | None = None
    target_resource_name: str | None = None
    new_start_at: datetime | None = None
    """For shift_into_window: an explicit timestamp rather than an offset.

    A window violation is fixed by landing at a specific clock time, and "shift by
    N minutes" would leave the caller to recompute whether the result actually fits.
    """


class ConflictSuggestionService:
    """Generate resolution suggestions for a conflict."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session and empty preload caches."""
        self.session = session
        self._preloaded = False
        self._wp_name_cache: dict[UUID, str] = {}
        self._preloaded_conflict: Conflict | None = None
        self._preloaded_assignments: list[Assignment] | None = None
        self._preloaded_working_time: WorkingTimeService | None = None
        self._preloaded_personal_candidates: list[PersonalResource] | None = None
        self._preloaded_infra_candidates: list[InfrastructureResource] | None = None
        self._preloaded_candidate_skills: dict[UUID, set[UUID]] | None = None
        self._preloaded_wp_requirements: dict[UUID, set[UUID]] | None = None
        self._preloaded_resource_skills: dict[UUID, set[UUID]] | None = None
        self._preloaded_candidate_assignments: list[Assignment] | None = None

    @classmethod
    def from_data(
        cls,
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
    ) -> "ConflictSuggestionService":
        """Build a service with data supplied directly, bypassing the database.

        A seam for tests, in the same shape as ``WorkingTimeService.from_data``
        and ``ConflictService.from_data``: it fills the preload caches that the
        loader methods consult, and the ORDINARY code path then runs unchanged.

        There is deliberately no second implementation of the suggestion logic.
        A parallel path would let tests pass against a copy while production
        drifted away from it, which is worse than having no tests — a missing
        test is a known gap, a test against a duplicate is a false negative
        hiding behind a green suite.
        """
        service = cls(session=None)
        service._preloaded = True
        service._preloaded_conflict = conflict
        service._preloaded_assignments = assignments
        service._preloaded_working_time = working_time
        service._preloaded_personal_candidates = personal_candidates or []
        service._preloaded_infra_candidates = infra_candidates or []
        service._preloaded_candidate_skills = candidate_skills or {}
        service._preloaded_wp_requirements = wp_requirements or {}
        service._preloaded_resource_skills = resource_skills or {}
        service._preloaded_candidate_assignments = candidate_assignments or []
        service._wp_name_cache = wp_names or {}
        return service

    # ------------------------------------------------------------------ loaders
    #
    # Each loader reads a preload cache when one is present and falls back to
    # SQL otherwise. This is the only place the two modes differ; everything
    # below them is shared.

    async def _load_conflict(self, conflict_id: UUID) -> Conflict | None:
        """The conflict under analysis."""
        if self._preloaded_conflict is not None:
            return self._preloaded_conflict
        return await self.session.get(Conflict, conflict_id)

    async def _load_involved_assignments(self, conflict_id: UUID) -> list[Assignment]:
        """Assignments linked to the conflict, batched to avoid an N+1."""
        if self._preloaded_assignments is not None:
            return self._preloaded_assignments

        ca_stmt = select(ConflictAssignment).where(
            ConflictAssignment.conflict_id == conflict_id
        )
        ca_result = await self.session.execute(ca_stmt)
        assignment_ids = [ca.assignment_id for ca in ca_result.scalars().all()]
        if not assignment_ids:
            return []

        assignments_stmt = select(Assignment).where(Assignment.id.in_(assignment_ids))
        assignments_result = await self.session.execute(assignments_stmt)
        return list(assignments_result.scalars().all())

    async def _load_personal_candidates(
        self, exclude_resource_id: UUID
    ) -> list[PersonalResource]:
        """Active personal resources other than the one already assigned."""
        if self._preloaded_personal_candidates is not None:
            return [
                c
                for c in self._preloaded_personal_candidates
                if c.id != exclude_resource_id
            ]
        stmt = select(PersonalResource).where(
            PersonalResource.is_active == True,  # noqa: E712
            PersonalResource.id != exclude_resource_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _load_infra_candidates(
        self, exclude_resource_id: UUID
    ) -> list[InfrastructureResource]:
        """Active infrastructure resources other than the one already booked."""
        if self._preloaded_infra_candidates is not None:
            return [
                c
                for c in self._preloaded_infra_candidates
                if c.id != exclude_resource_id
            ]
        stmt = select(InfrastructureResource).where(
            InfrastructureResource.is_active == True,  # noqa: E712
            InfrastructureResource.id != exclude_resource_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _load_candidate_skills(
        self, candidate_ids: list[UUID], resource_type: ResourceType
    ) -> dict[UUID, set[UUID]]:
        """Skill attributes per candidate, batched into one query."""
        if self._preloaded_candidate_skills is not None:
            return {
                cid: self._preloaded_candidate_skills.get(cid, set())
                for cid in candidate_ids
            }

        from app.models.skill import (
            InfrastructureResourceSkill,
            PersonalResourceSkill,
        )

        model: type[PersonalResourceSkill] | type[InfrastructureResourceSkill] = (
            PersonalResourceSkill
            if resource_type == ResourceType.personal
            else InfrastructureResourceSkill
        )
        stmt = select(model).where(model.resource_id.in_(candidate_ids))
        result = await self.session.execute(stmt)

        skills_by_resource: dict[UUID, set[UUID]] = {
            cid: set() for cid in candidate_ids
        }
        # Cast rather than annotate: scalars() genuinely returns Sequence[SQLModel] here,
        # because the select was built from a union of two model classes and the checker cannot
        # narrow it. Annotating it as the concrete union is a false statement that mypy rejects;
        # the cast says "I know more than the checker does" in the one place that is true, and
        # keeps the attribute reads below checked against a type that actually has them.
        rows = cast(
            "Sequence[PersonalResourceSkill | InfrastructureResourceSkill]",
            result.scalars().all(),
        )
        for sa in rows:
            skills_by_resource.setdefault(sa.resource_id, set()).add(
                sa.skill_attribute_id
            )
        return skills_by_resource

    async def _load_candidate_assignments_in_range(
        self, candidate_ids: list[UUID], start: date, end: date
    ) -> list[Assignment]:
        """Date-range assignments of candidates overlapping the conflict."""
        if self._preloaded_candidate_assignments is not None:
            return [
                a
                for a in self._preloaded_candidate_assignments
                if a.resource_id in set(candidate_ids)
                and a.start_date is not None
                and a.end_date is not None
                and a.start_date <= end
                and a.end_date >= start
            ]
        stmt = select(Assignment).where(
            Assignment.resource_id.in_(candidate_ids),
            Assignment.start_date <= end,
            Assignment.end_date >= start,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _load_overlapping_infra_assignments(
        self, candidate_ids: list[UUID], start_at: datetime, end_at: datetime
    ) -> set[UUID]:
        """Ids of candidates whose bookings overlap the given interval."""
        if self._preloaded_candidate_assignments is not None:
            return {
                a.resource_id
                for a in self._preloaded_candidate_assignments
                if a.resource_id in set(candidate_ids)
                and a.start_at is not None
                and a.end_at is not None
                and a.start_at < end_at
                and a.end_at > start_at
            }
        stmt = select(Assignment).where(
            Assignment.resource_id.in_(candidate_ids),
            Assignment.start_at < end_at,
            Assignment.end_at > start_at,
        )
        result = await self.session.execute(stmt)
        return {a.resource_id for a in result.scalars().all()}

    async def _prepared_working_time(
        self, resource_ids: list[UUID], start: date, end: date
    ) -> WorkingTimeService:
        """Working-time service covering the candidates and the conflict window."""
        if self._preloaded_working_time is not None:
            return self._preloaded_working_time
        working_time = WorkingTimeService(self.session)
        await working_time.prepare(resource_ids, start, end)
        return working_time

    async def get_suggestions(self, conflict_id: UUID) -> list[ResolutionSuggestion]:
        """Analyze a conflict and return resolution suggestions."""
        conflict = await self._load_conflict(conflict_id)
        if conflict is None:
            return []

        assignments = await self._load_involved_assignments(conflict_id)
        if not assignments:
            return []

        wp_ids = list({a.work_package_id for a in assignments})
        if not self._wp_name_cache:
            self._wp_name_cache = await self._batch_load_work_package_names(wp_ids)

        suggestions: list[ResolutionSuggestion] = []

        for assignment in assignments:
            if conflict.resource_type == ResourceType.personal:
                suggestions.extend(
                    await self._suggest_for_personal(assignment, conflict, assignments)
                )
            else:
                suggestions.extend(
                    await self._suggest_for_infrastructure(
                        assignment, conflict, assignments
                    )
                )

        return suggestions

    async def _batch_load_work_package_names(
        self, wp_ids: list[UUID]
    ) -> dict[UUID, str]:
        """Load work package names in a single batch query.

        In preloaded mode the names come from the seam, and a work package with
        no supplied name falls back to the em dash placeholder that
        :meth:`_get_work_package_name` uses — the display name is never what a
        suggestion is judged on.
        """
        if not wp_ids or self._preloaded:
            return self._wp_name_cache
        from app.models.project import WorkPackage

        stmt = select(WorkPackage).where(WorkPackage.id.in_(wp_ids))
        result = await self.session.execute(stmt)
        return {wp.id: wp.name for wp in result.scalars().all()}

    async def _suggest_for_personal(
        self,
        assignment: Assignment,
        conflict: Conflict,
        all_assignments: list[Assignment],
    ) -> list[ResolutionSuggestion]:
        """Generate suggestions for a personal resource conflict."""
        suggestions: list[ResolutionSuggestion] = []
        wp_name = await self._get_work_package_name(assignment.work_package_id)

        # 1. Reduce allocation to fit
        # The ceiling is the availability recorded on the conflict, not 100:
        # a part-time resource has less, and a day covered by an absence has
        # none. Reducing cannot help when there is no capacity at all, so no
        # suggestion is offered in that case rather than a misleading one.
        if (
            assignment.allocation_percent
            and assignment.allocation_percent > 20
            and conflict.available_percent > 0
        ):
            other_total = sum(
                (a.allocation_percent or 0)
                for a in all_assignments
                if a.id != assignment.id
            )
            max_allowed = max(conflict.available_percent - other_total, 10.0)
            if max_allowed < (assignment.allocation_percent or 0):
                suggestions.append(
                    ResolutionSuggestion(
                        type="reduce_allocation",
                        assignment_id=assignment.id,
                        description=f"Reduce '{wp_name}' from {int(assignment.allocation_percent)}% to {int(max_allowed)}%",
                        new_allocation_percent=round(max_allowed, 0),
                    )
                )

        # 2. Shift forward
        if assignment.start_date and assignment.end_date:
            new_start = conflict.end_date + timedelta(days=1)
            shift = (new_start - assignment.start_date).days
            if 0 < shift <= 30:
                suggestions.append(
                    ResolutionSuggestion(
                        type="shift_forward",
                        assignment_id=assignment.id,
                        description=f"Shift '{wp_name}' {shift} days forward (start {new_start.isoformat()})",
                        shift_days=shift,
                    )
                )

        # 3. Shift backward
        if assignment.start_date and assignment.end_date:
            new_end = conflict.start_date - timedelta(days=1)
            duration = (assignment.end_date - assignment.start_date).days
            new_start = new_end - timedelta(days=duration)
            shift = (assignment.start_date - new_start).days
            if 0 < shift <= 30:
                suggestions.append(
                    ResolutionSuggestion(
                        type="shift_backward",
                        assignment_id=assignment.id,
                        description=f"Shift '{wp_name}' {shift} days backward (start {new_start.isoformat()})",
                        shift_days=-shift,
                    )
                )

        # 4. Swap to available resource (skill-matched)
        required_skills = await self._get_required_skills_for_assignment(assignment)
        swap = await self._find_available_personal_resource(
            assignment, conflict, required_skills
        )
        if swap:
            suggestions.append(swap)

        return suggestions

    async def _suggest_for_infrastructure(
        self,
        assignment: Assignment,
        conflict: Conflict,
        all_assignments: list[Assignment],
    ) -> list[ResolutionSuggestion]:
        """Generate suggestions for an infrastructure resource conflict.

        Branches on the CAUSE, because the two infrastructure causes need different
        actions and offering the wrong one is worse than offering none.

        For a booking outside the operating hours, a whole-day shift cannot help:
        the clock time is unchanged, so a booking at 03:00 is still at 03:00 three
        days later. Those suggestions are derived from an overlap that does not
        exist for this cause, so they are not offered — only a shift into an actual
        window is (ADR-005).
        """
        if conflict.cause == ConflictCause.outside_availability:
            return await self._suggest_shift_into_window(assignment)

        suggestions: list[ResolutionSuggestion] = []
        wp_name = await self._get_work_package_name(assignment.work_package_id)

        # 1. Shift forward past conflict
        if assignment.start_at and assignment.end_at:
            new_start = conflict.end_date + timedelta(days=1)
            shift = (new_start - assignment.start_at.date()).days
            if 0 < shift <= 30:
                suggestions.append(
                    ResolutionSuggestion(
                        type="shift_forward",
                        assignment_id=assignment.id,
                        description=f"Shift '{wp_name}' {shift} days forward",
                        shift_days=shift,
                    )
                )

        # 2. Shift backward before conflict
        if assignment.start_at and assignment.end_at:
            new_end_date = conflict.start_date - timedelta(days=1)
            duration = (assignment.end_at.date() - assignment.start_at.date()).days
            new_start_date = new_end_date - timedelta(days=duration)
            shift = (assignment.start_at.date() - new_start_date).days
            if 0 < shift <= 30:
                suggestions.append(
                    ResolutionSuggestion(
                        type="shift_backward",
                        assignment_id=assignment.id,
                        description=f"Shift '{wp_name}' {shift} days backward",
                        shift_days=-shift,
                    )
                )

        # 3. Swap to available infra resource (skill-matched)
        required_skills = await self._get_required_skills_for_assignment(assignment)
        swap = await self._find_available_infra_resource(
            assignment, conflict, required_skills
        )
        if swap:
            suggestions.append(swap)

        return suggestions

    async def _suggest_shift_into_window(
        self, assignment: Assignment
    ) -> list[ResolutionSuggestion]:
        """Propose moving a booking into one of the resource's operating spans.

        Returns an empty list when no single span can hold the booking — a night
        shift's worth of work will not fit into a two-hour window, and inventing a
        suggestion that does not resolve the violation is worse than reporting the
        conflict without one.
        """
        if assignment.start_at is None or assignment.end_at is None:
            return []

        working_time = await self._prepared_working_time(
            [assignment.resource_id],
            assignment.start_at.date(),
            assignment.end_at.date(),
        )
        spans = working_time.covered_spans(
            assignment.resource_id, assignment.start_at.date()
        )
        new_start = shift_into_span(assignment.start_at, assignment.end_at, spans)
        if new_start is None:
            return []

        wp_name = await self._get_work_package_name(assignment.work_package_id)
        return [
            ResolutionSuggestion(
                type="shift_into_window",
                assignment_id=assignment.id,
                description=(
                    f"Move '{wp_name}' to {new_start.strftime('%H:%M')}, "
                    "inside the operating hours"
                ),
                new_start_at=new_start,
            )
        ]

    async def _find_available_personal_resource(
        self,
        assignment: Assignment,
        conflict: Conflict,
        required_skills: set[UUID],
    ) -> ResolutionSuggestion | None:
        """Find a personal resource with matching skills and capacity in the conflict period.

        Pre-loads all candidate skill assignments and overlapping assignments/absences
        in batch queries to avoid per-candidate database round-trips.
        """
        if not assignment.start_date or not assignment.end_date:
            return None

        wp_name = await self._get_work_package_name(assignment.work_package_id)

        candidates = await self._load_personal_candidates(assignment.resource_id)
        if not candidates:
            return None

        candidate_ids = [c.id for c in candidates]

        skills_by_resource = await self._load_candidate_skills(
            candidate_ids, ResourceType.personal
        )

        candidate_assignments = await self._load_candidate_assignments_in_range(
            candidate_ids, conflict.start_date, conflict.end_date
        )
        assignments_by_resource: dict[UUID, list[Assignment]] = {
            cid: [] for cid in candidate_ids
        }
        for a in candidate_assignments:
            assignments_by_resource.setdefault(a.resource_id, []).append(a)

        # Absences are deliberately NOT summed into a load figure here. They
        # reduce availability, and WorkingTimeService owns that (ADR-004), so
        # candidate headroom comes from the working-time model rather than from
        # "100 minus load" — which would both double-count a vacation and assume
        # every candidate has a full eight-hour day.
        working_time = await self._prepared_working_time(
            candidate_ids, conflict.start_date, conflict.end_date
        )

        needed = assignment.allocation_percent or 100.0

        for candidate in candidates:
            # Check skill match: candidate must have all required skills
            if required_skills:
                candidate_skills = skills_by_resource.get(candidate.id, set())
                if not required_skills.issubset(candidate_skills):
                    continue

            # Smallest headroom across the conflict period decides: a candidate
            # that fits on four days out of five does not fit.
            c_assignments = assignments_by_resource.get(candidate.id, [])
            available = _min_headroom_percent(
                working_time,
                candidate.id,
                c_assignments,
                conflict.start_date,
                conflict.end_date,
            )
            if available >= needed:
                return ResolutionSuggestion(
                    type="swap_resource",
                    assignment_id=assignment.id,
                    description=f"Swap '{wp_name}' to '{candidate.name}' ({int(available)}% available)",
                    target_resource_id=candidate.id,
                    target_resource_name=candidate.name,
                )

        return None

    async def _get_required_skills_for_assignment(
        self, assignment: Assignment
    ) -> set[UUID]:
        """Get required skill_attribute_ids for an assignment.

        Reads from work_package_requirements. Falls back to the skills of the
        currently assigned resource if no requirements are defined.
        """
        if self._preloaded_wp_requirements is not None:
            wp_skills = self._preloaded_wp_requirements.get(
                assignment.work_package_id, set()
            )
            if wp_skills:
                return wp_skills
            return await self._get_resource_skill_ids(assignment.resource_id)

        from app.models.work_package_requirement import WorkPackageRequirement

        stmt = select(WorkPackageRequirement.skill_attribute_id).where(
            WorkPackageRequirement.work_package_id == assignment.work_package_id,
            WorkPackageRequirement.skill_attribute_id.is_not(None),
        )
        result = await self.session.execute(stmt)
        wp_skills = {row[0] for row in result.all()}
        if wp_skills:
            return wp_skills

        # Fallback: use skills of the currently assigned resource
        return await self._get_resource_skill_ids(assignment.resource_id)

    async def _get_resource_skill_ids(self, resource_id: UUID) -> set[UUID]:
        """Get the set of skill_attribute_ids assigned to a resource."""
        if self._preloaded_resource_skills is not None:
            return self._preloaded_resource_skills.get(resource_id, set())

        from app.models.skill import PersonalResourceSkill

        stmt = select(PersonalResourceSkill.skill_attribute_id).where(
            PersonalResourceSkill.resource_id == resource_id
        )
        result = await self.session.execute(stmt)
        return {row[0] for row in result.all()}

    async def _find_available_infra_resource(
        self,
        assignment: Assignment,
        conflict: Conflict,
        required_skills: set[UUID],
    ) -> ResolutionSuggestion | None:
        """Find an infrastructure resource with matching skills and no bookings in the conflict period.

        Pre-loads all candidate skill assignments and overlapping assignments
        in batch queries to avoid the N+1 pattern.
        """
        if not assignment.start_at or not assignment.end_at:
            return None

        wp_name = await self._get_work_package_name(assignment.work_package_id)

        candidates = await self._load_infra_candidates(assignment.resource_id)
        if not candidates:
            return None

        candidate_ids = [c.id for c in candidates]

        skills_by_resource = await self._load_candidate_skills(
            candidate_ids, ResourceType.infrastructure
        )

        overlaps_by_resource = await self._load_overlapping_infra_assignments(
            candidate_ids, assignment.start_at, assignment.end_at
        )

        for candidate in candidates:
            # Check skill match
            if required_skills:
                candidate_skills = skills_by_resource.get(candidate.id, set())
                if not required_skills.issubset(candidate_skills):
                    continue

            # Check if candidate has any overlapping assignments
            if candidate.id not in overlaps_by_resource:
                return ResolutionSuggestion(
                    type="swap_resource",
                    assignment_id=assignment.id,
                    description=f"Move '{wp_name}' to '{candidate.name}' (available)",
                    target_resource_id=candidate.id,
                    target_resource_name=candidate.name,
                )

        return None

    async def _get_infra_resource_skill_ids(self, resource_id: UUID) -> set[UUID]:
        """Get the set of skill_attribute_ids assigned to an infrastructure resource."""
        if self._preloaded_resource_skills is not None:
            return self._preloaded_resource_skills.get(resource_id, set())

        from app.models.skill import InfrastructureResourceSkill

        stmt = select(InfrastructureResourceSkill.skill_attribute_id).where(
            InfrastructureResourceSkill.resource_id == resource_id
        )
        result = await self.session.execute(stmt)
        return {row[0] for row in result.all()}

    async def _get_work_package_name(self, wp_id: UUID) -> str:
        """Get work package name for display, using pre-loaded cache when available."""
        if wp_id in self._wp_name_cache:
            return self._wp_name_cache[wp_id]
        if self._preloaded:
            return "—"

        from app.models.project import WorkPackage

        wp = await self.session.get(WorkPackage, wp_id)
        return wp.name if wp else "—"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def shift_into_span(
    start_at: datetime, end_at: datetime, spans: list[tuple[int, int]]
) -> datetime | None:
    """A new start timestamp that puts the whole booking inside one operating span.

    Args:
        start_at: Current booking start.
        end_at: Current booking end.
        spans: Bookable ``[start_minute, end_minute)`` pairs for the booking's day,
            as :meth:`WorkingTimeService.covered_spans` returns them — already
            merged and sorted.

    Returns:
        The proposed new start, or None when no single span can hold the booking.

    Chooses the span whose start is **nearest** to the current start, because the
    point of the suggestion is the smallest change that fixes the problem, not the
    earliest possible slot. A booking wrongly placed at 03:00 against a two-shift
    resource should be offered 06:00 rather than being pushed to whichever shift
    happens to come first in the list.

    Returns None when the booking already fits: there is then nothing to suggest,
    and emitting a "shift" of zero would look like a fix for a conflict raised by
    something else.

    Returns None for a booking that crosses midnight. Spans belong to the day a
    shift STARTS on (ADR-005), so relocating such a booking would have to re-derive
    its tail against the next day's spans — a different calculation, and guessing at
    it would produce a suggestion that does not actually resolve the violation.
    """
    if end_at <= start_at:
        return None
    if end_at.date() != start_at.date():
        return None

    duration = int((end_at - start_at).total_seconds() // 60)
    if duration <= 0:
        return None

    start_minute = start_at.hour * 60 + start_at.minute
    end_minute = start_minute + duration

    # Already inside one span: nothing to propose.
    if any(s <= start_minute and end_minute <= e for s, e in spans):
        return None

    candidates = [(s, e) for s, e in spans if e - s >= duration]
    if not candidates:
        return None

    best_start = min(candidates, key=lambda span: abs(span[0] - start_minute))[0]
    if best_start == start_minute:
        return None
    return datetime.combine(start_at.date(), time()) + timedelta(minutes=best_start)


def _min_headroom_percent(
    working_time: WorkingTimeService,
    resource_id: UUID,
    assignments: list[Assignment],
    start: date,
    end: date,
) -> float:
    """Smallest spare capacity across a period, as percent of a normative day.

    Availability comes from the week profile, the site calendar and absences;
    demand from the assignments already on the resource. The *minimum* is what
    decides a swap: a candidate with room on four days out of five cannot take
    a five-day assignment.

    Non-working days are skipped rather than counted as zero headroom. They
    place no demand either (ADR-004), so counting them would make every
    candidate look fully booked over any weekend.
    """
    headroom: float | None = None
    current = start
    while current <= end:
        if working_time.is_working_day(resource_id, current):
            available = working_time.available_minutes(resource_id, current)
            assigned = percent_to_minutes(
                sum(
                    (a.allocation_percent or 0)
                    for a in assignments
                    if a.start_date
                    and a.end_date
                    and a.start_date <= current <= a.end_date
                )
            )
            day_headroom = minutes_to_percent(max(0, available - assigned))
            headroom = day_headroom if headroom is None else min(headroom, day_headroom)
        current += timedelta(days=1)

    # No working day in the period: nothing can be scheduled, so no headroom.
    return headroom if headroom is not None else 0.0
