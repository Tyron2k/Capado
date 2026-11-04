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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import BusinessRuleError
from app.models.assignment import Assignment
from app.models.conflict import Conflict, ConflictAssignment, ConflictCause
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.schemas.conflict_suggestion import SuggestionType
from app.services.assignment_service import AssignmentService, clip_assignment
from app.services.conflict_service import ConflictService
from app.services.qualification import HeldQualification, satisfies
from app.services.time_zone import (
    local_date,
    local_time,
    local_wall_time_to_utc,
    planning_zone,
)
from app.services.unmet_requirements_service import assignment_span
from app.services.working_time_service import (
    WorkingTimeService,
    minutes_to_percent,
    percent_to_minutes,
)


@dataclass
class ResolutionSuggestion:
    """A single suggestion for resolving a conflict."""

    type: SuggestionType
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
    new_end_at: datetime | None = None
    """Every infrastructure time shift carries the exact UTC interval to apply."""


def _shift_booking(
    assignment: Assignment, days: int
) -> tuple[datetime, datetime] | None:
    """Shift calendar days in the planning zone, never in a viewer's display zone.

    Keep both local clock readings. If either target is missing or ambiguous,
    do not offer a suggestion that would require guessing an offset.
    """
    if assignment.start_at is None or assignment.end_at is None:
        return None
    zone = planning_zone()
    try:
        start, end = (
            local_wall_time_to_utc(
                local_time(value, zone).replace(tzinfo=None) + timedelta(days=days),
                zone,
            )
            for value in (assignment.start_at, assignment.end_at)
        )
    except ValueError:
        return None
    return (start, end) if end > start else None


class ConflictSuggestionService:
    """Generate resolution suggestions for a conflict."""

    def __init__(self, session: AsyncSession | None):
        """Initialize with a database session and empty preload caches."""
        self._session = session
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

    @property
    def session(self) -> AsyncSession:
        """Require a database only for queries, keeping preloaded calculations independent."""
        if self._session is None:
            raise RuntimeError(
                "A preloaded suggestion service cannot query the database"
            )
        return self._session

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
        # Cast rather than annotate: scalars() genuinely returns a typed resource sequence here,
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

    async def _load_already_assigned_candidate_ids(
        self, work_package_id: UUID, candidate_ids: list[UUID]
    ) -> set[UUID]:
        """Candidates already on this work package cannot be swap targets.

        The duplicate rule applies regardless of date overlap, so the conflict-
        window assignment loaders below cannot answer this question.
        """
        if not candidate_ids:
            return set()
        if self._preloaded_candidate_assignments is not None:
            candidate_id_set = set(candidate_ids)
            return {
                a.resource_id
                for a in self._preloaded_candidate_assignments
                if a.work_package_id == work_package_id
                and a.resource_id in candidate_id_set
            }
        stmt = select(Assignment.resource_id).where(
            Assignment.work_package_id == work_package_id,
            Assignment.resource_id.in_(candidate_ids),
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

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

    async def get_assignment_suggestions(
        self, assignment_id: UUID, *, alternatives_only: bool = False
    ) -> list[ResolutionSuggestion]:
        """Use current bookings, without requiring a saved conflict record."""
        assignment = await AssignmentService(self.session).get_by_id(assignment_id)
        span = assignment_span(assignment)
        if span is None or span[1] == date.max or (span[1] - span[0]).days > 365:
            raise BusinessRuleError(
                "Suggestions are limited to booking periods of 366 days."
            )
        suggestions = await self._qualified_alternatives(assignment)
        if not alternatives_only:
            bookings = list(
                (
                    await self.session.scalars(
                        select(Assignment).where(
                            Assignment.resource_id == assignment.resource_id
                        )
                    )
                ).all()
            )
            bounded = [
                clipped
                for a in bookings
                if (clipped := clip_assignment(a, *span)) is not None
            ]
            for period in await ConflictService(self.session).calculate_periods(
                assignment.resource_id, bounded
            ):
                if assignment.id not in period.assignment_ids:
                    continue
                conflict = Conflict(
                    resource_id=assignment.resource_id,
                    resource_type=assignment.resource_type,
                    cause=period.cause,
                    start_date=period.start_date,
                    end_date=period.end_date,
                    total_assigned_percent=period.total_assigned_percent,
                    available_percent=period.available_percent,
                )
                involved = [a for a in bookings if a.id in period.assignment_ids]
                method = (
                    self._suggest_for_personal
                    if assignment.resource_type == ResourceType.personal
                    else self._suggest_for_infrastructure
                )
                suggestions.extend(
                    s
                    for s in await method(
                        assignment, conflict, involved, include_swap=False
                    )
                    if s.type != "swap_resource"
                )
        # One booking can participate in several conflict phases.
        return list({tuple(vars(s).values()): s for s in suggestions}.values())

    async def _qualified_alternatives(
        self, assignment: Assignment
    ) -> list[ResolutionSuggestion]:
        """Same resource type, valid qualification and room for the whole booking.

        A replacement needs one applicable role, matching mismatch detection;
        a person is not expected to hold the package's machine qualifications.
        """
        from app.models.skill import (
            InfrastructureResourceSkill,
            PersonalResourceSkill,
            Skill,
            SkillAttribute,
        )
        from app.models.work_package_requirement import WorkPackageRequirement

        span = assignment_span(assignment)
        assert span is not None
        start, end = span
        model: type[PersonalResource] | type[InfrastructureResource] = (
            PersonalResource
            if assignment.resource_type == ResourceType.personal
            else InfrastructureResource
        )
        qualification_model: (
            type[PersonalResourceSkill] | type[InfrastructureResourceSkill]
        ) = (
            PersonalResourceSkill
            if assignment.resource_type == ResourceType.personal
            else InfrastructureResourceSkill
        )
        requirements = list(
            (
                await self.session.scalars(
                    select(WorkPackageRequirement)
                    .join(Skill, WorkPackageRequirement.skill_id == Skill.id)
                    .where(
                        WorkPackageRequirement.work_package_id
                        == assignment.work_package_id,
                        Skill.resource_type == assignment.resource_type.value,
                    )
                )
            ).all()
        )
        if not requirements:
            return []
        rows = cast(
            "Sequence[tuple[PersonalResource | InfrastructureResource, PersonalResourceSkill | InfrastructureResourceSkill, UUID]]",
            (
                await self.session.execute(
                    select(model, qualification_model, SkillAttribute.skill_id)
                    .join(
                        qualification_model, qualification_model.resource_id == model.id
                    )
                    .join(
                        SkillAttribute,
                        SkillAttribute.id == qualification_model.skill_attribute_id,
                    )
                    .where(
                        model.is_active.is_(True),
                        model.id != assignment.resource_id,
                        SkillAttribute.skill_id.in_({r.skill_id for r in requirements}),
                    )
                    .order_by(model.name, model.id)
                )
            ).all(),
        )
        candidates: dict[UUID, PersonalResource | InfrastructureResource] = {}
        for resource, qualification, skill_id in rows:
            if any(
                req.skill_id == skill_id
                and (
                    req.skill_attribute_id is None
                    or req.skill_attribute_id == qualification.skill_attribute_id
                )
                and satisfies(
                    HeldQualification(
                        valid_from=qualification.valid_from,
                        valid_until=qualification.valid_until,
                        level=qualification.level,
                    ),
                    req.min_level,
                    start,
                    end,
                )
                for req in requirements
            ):
                candidates[resource.id] = resource
        if not candidates:
            return []
        bookings = list(
            (
                await self.session.scalars(
                    select(Assignment).where(Assignment.resource_id.in_(candidates))
                )
            ).all()
        )
        working = WorkingTimeService(self.session)
        await working.prepare(list(candidates), start, end)
        from app.models.calendar import WorkWeekProfile

        standard = (
            await self.session.scalar(
                select(WorkWeekProfile).where(WorkWeekProfile.is_default)
            )
            if assignment.resource_type == ResourceType.personal
            else None
        )
        suggestions = []
        for rid, resource in candidates.items():
            own = [a for a in bookings if a.resource_id == rid]
            # Preserve distinct booking intervals, but never offer an exact duplicate.
            if any(
                a.work_package_id == assignment.work_package_id
                and a.start_date == assignment.start_date
                and a.end_date == assignment.end_date
                and a.allocation_percent == assignment.allocation_percent
                and a.start_at == assignment.start_at
                and a.end_at == assignment.end_at
                for a in own
            ):
                continue
            if assignment.resource_type == ResourceType.personal:
                day = start
                no_supply = standard is None
                while day <= end and not no_supply:
                    no_supply = (
                        standard is not None
                        and standard.minutes_for_weekday(day.weekday()) > 0
                        and working.calendar_minutes(rid, day) == 0
                    )
                    day += timedelta(days=1)
                if no_supply:
                    continue
                if _min_headroom_percent(working, rid, own, start, end) < (
                    assignment.allocation_percent or 100
                ):
                    continue
            else:
                proposed = Assignment(
                    resource_id=rid,
                    resource_type=assignment.resource_type,
                    work_package_id=assignment.work_package_id,
                    start_at=assignment.start_at,
                    end_at=assignment.end_at,
                )
                engine = ConflictService.from_data(
                    session=self.session,
                    working_time=working,
                    resources={rid: resource},
                    assignments={
                        rid: [
                            clipped
                            for a in [*own, proposed]
                            if (clipped := clip_assignment(a, start, end)) is not None
                        ]
                    },
                )
                if any(
                    proposed.id in p.assignment_ids
                    for p in await engine.calculate_periods(rid)
                ):
                    continue
            suggestions.append(
                ResolutionSuggestion(
                    type="swap_resource",
                    assignment_id=assignment.id,
                    description=f"Swap to '{resource.name}'",
                    target_resource_id=rid,
                    target_resource_name=resource.name,
                )
            )
            if len(suggestions) == 5:
                break
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
        *,
        include_swap: bool = True,
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

        if include_swap:
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
        *,
        include_swap: bool = True,
    ) -> list[ResolutionSuggestion]:
        """Generate suggestions for an infrastructure resource conflict.

        Branches on the CAUSE, because the two infrastructure causes need different
        actions and offering the wrong one is worse than offering none.

        A window violation needs a free operating span, including overnight
        spans. Blind whole-day shifts derived from an overlap do not establish
        availability, so search actual windows within the package instead.
        """
        if conflict.cause == ConflictCause.outside_availability:
            return await self._suggest_shift_into_window(assignment)

        suggestions: list[ResolutionSuggestion] = []
        wp_name = await self._get_work_package_name(assignment.work_package_id)

        # 1. Shift forward past conflict
        if assignment.start_at and assignment.end_at:
            new_start = conflict.end_date + timedelta(days=1)
            shift = (new_start - local_date(assignment.start_at, planning_zone())).days
            target = _shift_booking(assignment, shift) if 0 < shift <= 30 else None
            if target:
                suggestions.append(
                    ResolutionSuggestion(
                        type="shift_forward",
                        assignment_id=assignment.id,
                        description=f"Shift '{wp_name}' {shift} days forward",
                        shift_days=shift,
                        new_start_at=target[0],
                        new_end_at=target[1],
                    )
                )

        # 2. Shift backward before conflict
        if assignment.start_at and assignment.end_at:
            new_end_date = conflict.start_date - timedelta(days=1)
            duration = (
                local_date(assignment.end_at, planning_zone())
                - local_date(assignment.start_at, planning_zone())
            ).days
            new_start_date = new_end_date - timedelta(days=duration)
            shift = (
                local_date(assignment.start_at, planning_zone()) - new_start_date
            ).days
            target = _shift_booking(assignment, -shift) if 0 < shift <= 30 else None
            if target:
                suggestions.append(
                    ResolutionSuggestion(
                        type="shift_backward",
                        assignment_id=assignment.id,
                        description=f"Shift '{wp_name}' {shift} days backward",
                        shift_days=-shift,
                        new_start_at=target[0],
                        new_end_at=target[1],
                    )
                )

        if include_swap:
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
        """Find the nearest free span inside the package, preserving elapsed duration.

        Join touching daily spans before fitting overnight bookings. Ambiguous or
        missing local boundaries are skipped rather than guessed.
        """
        from app.models.project import WorkPackage

        if assignment.start_at is None or assignment.end_at is None:
            return []
        zone = planning_zone()
        day = local_date(assignment.start_at, zone)
        start = max(
            date.min + timedelta(days=1),
            day - timedelta(days=min(30, (day - date.min).days)),
        )
        end = min(
            date.max - timedelta(days=1),
            day + timedelta(days=min(30, (date.max - day).days)),
        )
        if not self._preloaded:
            package = await self.session.get(WorkPackage, assignment.work_package_id)
            if package is None:
                return []
            start, end = max(start, package.start_date), min(end, package.end_date)
        if end < start:
            return []
        working = await self._prepared_working_time(
            [assignment.resource_id], start, end
        )
        spans: list[tuple[datetime, datetime]] = []
        current = start
        while current <= end:
            midnight = datetime.combine(current, time())
            for lo, hi in working.covered_spans(assignment.resource_id, current):
                try:
                    lower = local_wall_time_to_utc(
                        midnight + timedelta(minutes=lo), zone
                    )
                    upper = local_wall_time_to_utc(
                        midnight + timedelta(minutes=hi), zone
                    )
                except ValueError:
                    continue
                if spans and lower <= spans[-1][1]:
                    spans[-1] = (spans[-1][0], max(upper, spans[-1][1]))
                else:
                    spans.append((lower, upper))
            current += timedelta(days=1)
        if self._preloaded_candidate_assignments is not None:
            bookings = self._preloaded_candidate_assignments
        else:
            bookings = list(
                (
                    await self.session.scalars(
                        select(Assignment).where(
                            Assignment.resource_id == assignment.resource_id,
                            Assignment.id != assignment.id,
                            Assignment.start_at.is_not(None),
                        )
                    )
                ).all()
            )
        # Subtract occupied intervals, including competing packages.
        for booking in bookings:
            if (
                booking.id == assignment.id
                or booking.resource_id != assignment.resource_id
                or booking.start_at is None
                or booking.end_at is None
            ):
                continue
            free = []
            for lower, upper in spans:
                if booking.end_at <= lower or booking.start_at >= upper:
                    free.append((lower, upper))
                else:
                    if lower < booking.start_at:
                        free.append((lower, booking.start_at))
                    if booking.end_at < upper:
                        free.append((booking.end_at, upper))
            spans = free
        duration = assignment.end_at - assignment.start_at
        new_start = shift_into_span(assignment.start_at, assignment.end_at, spans)
        if new_start is None:
            return []
        wp_name = await self._get_work_package_name(assignment.work_package_id)
        return [
            ResolutionSuggestion(
                type="shift_into_window",
                assignment_id=assignment.id,
                description=f"Move '{wp_name}' inside free operating hours",
                new_start_at=new_start,
                new_end_at=new_start + duration,
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

        already_assigned = await self._load_already_assigned_candidate_ids(
            assignment.work_package_id, [c.id for c in candidates]
        )
        candidates = [c for c in candidates if c.id not in already_assigned]
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
        wp_skills = {row[0] for row in result.all() if row[0] is not None}
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

        already_assigned = await self._load_already_assigned_candidate_ids(
            assignment.work_package_id, [c.id for c in candidates]
        )
        candidates = [c for c in candidates if c.id not in already_assigned]
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
    start_at: datetime, end_at: datetime, spans: list[tuple[datetime, datetime]]
) -> datetime | None:
    """Nearest placement of the complete booking in a free continuous span.

    Spans have resolved timestamps, so overnight and DST intervals preserve the
    actual elapsed duration. A zero move or an interval that cannot fit has no fix.
    """
    duration = end_at - start_at
    if duration <= timedelta() or any(
        lo <= start_at and end_at <= hi for lo, hi in spans
    ):
        return None
    candidates = [
        max(lo, min(start_at, hi - duration)) for lo, hi in spans if hi - lo >= duration
    ]
    return (
        min(candidates, key=lambda instant: (abs(instant - start_at), instant))
        if candidates
        else None
    )


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
