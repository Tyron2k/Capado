"""Compose current planning evidence without persisting or recalculating domain rules.

Checks run only for the selected package. Calendars and competing assignments
are batch-loaded; the existing conflict engine owns capacity/occupancy rules.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.assignment import Assignment
from app.models.calendar import WorkWeekProfile
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.skill import Skill
from app.models.work_package_requirement import WorkPackageRequirement
from app.schemas.assignment import AssignmentResponse
from app.schemas.planning_readiness import (
    PersonnelSupplyGap,
    PlanningWorkPackage,
    ReadinessConflict,
    ReadinessLimit,
    ReadinessStatus,
    WorkPackageReadiness,
)
from app.services.conflict_service import ConflictService
from app.services.skill_mismatch import detect_mismatches
from app.services.time_zone import local_day_bounds, planning_today, planning_zone
from app.services.unmet_requirements_service import (
    assignment_span,
    get_unmet_requirements,
)
from app.services.working_time_service import WorkingTimeService

# Same bounded interactive window as assignment preview, without bounding the
# existing boundary-based requirement/qualification checks.
MAX_CHECK_DAYS = 366


async def list_planning_work_packages(
    session: AsyncSession,
) -> list[PlanningWorkPackage]:
    """List unfinished current/future packages, including those without problems."""
    rows = await session.execute(
        select(WorkPackage, Project.name)
        .join(Project, Project.id == WorkPackage.project_id)
        .where(
            WorkPackage.end_date >= planning_today(), WorkPackage.completed_at.is_(None)
        )
        .order_by(Project.name, WorkPackage.name, WorkPackage.id)
    )
    return [_package(wp, name) for wp, name in rows]


def _package(wp: WorkPackage, project_name: str) -> PlanningWorkPackage:
    return PlanningWorkPackage(
        id=wp.id,
        name=wp.name,
        project_id=wp.project_id,
        project_name=project_name,
        start_date=wp.start_date,
        end_date=wp.end_date,
    )


def _status(
    *, conflicts: bool = False, gaps: bool = False, unknown: bool = False
) -> ReadinessStatus:
    # Known failures must survive an incomplete check in another dimension.
    if conflicts:
        return "conflicting"
    if gaps:
        return "missing_requirements"
    return "not_fully_assessable" if unknown else "covered"


def _clip(booking: Assignment, start: date, end: date) -> Assignment | None:
    """Transient input to the existing engine; never mutate tracked bookings."""
    if booking.resource_type == ResourceType.personal:
        if booking.start_date is None or booking.end_date is None:
            return None
        lo, hi = max(start, booking.start_date), min(end, booking.end_date)
        if lo > hi:
            return None
        return Assignment(
            id=booking.id,
            resource_id=booking.resource_id,
            resource_type=booking.resource_type,
            work_package_id=booking.work_package_id,
            start_date=lo,
            end_date=hi,
            allocation_percent=booking.allocation_percent,
        )
    if booking.start_at is None or booking.end_at is None:
        return None
    lower = local_day_bounds(start, planning_zone())[0]
    upper = local_day_bounds(end, planning_zone())[1]
    lo_at, hi_at = max(lower, booking.start_at), min(upper, booking.end_at)
    if lo_at >= hi_at:
        return None
    return Assignment(
        id=booking.id,
        resource_id=booking.resource_id,
        resource_type=booking.resource_type,
        work_package_id=booking.work_package_id,
        start_at=lo_at,
        end_at=hi_at,
    )


async def get_work_package_readiness(
    session: AsyncSession,
    work_package_id: UUID,
) -> WorkPackageReadiness:
    """Read current coverage/qualifications and preview resource constraints."""
    row = (
        await session.execute(
            select(WorkPackage, Project.name)
            .join(Project, Project.id == WorkPackage.project_id)
            .where(
                WorkPackage.id == work_package_id,
                WorkPackage.end_date >= planning_today(),
                WorkPackage.completed_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise NotFoundError("Active work package", work_package_id)
    wp, project_name = row
    requirements = list(
        (
            await session.scalars(
                select(Skill.resource_type)
                .join(
                    WorkPackageRequirement, WorkPackageRequirement.skill_id == Skill.id
                )
                .where(WorkPackageRequirement.work_package_id == wp.id)
            )
        ).all()
    )
    personal_count = requirements.count("personal")
    infra_count = requirements.count("infrastructure")
    own = list(
        (
            await session.scalars(
                select(Assignment)
                .where(Assignment.work_package_id == wp.id)
                .order_by(Assignment.resource_id, Assignment.id)
            )
        ).all()
    )
    ids = {a.resource_id for a in own}
    resources: dict[UUID, PersonalResource | InfrastructureResource] = {}
    if ids:
        personal = await session.scalars(
            select(PersonalResource).where(PersonalResource.id.in_(ids))
        )
        resources.update({r.id: r for r in personal.all()})
        infrastructure = await session.scalars(
            select(InfrastructureResource).where(InfrastructureResource.id.in_(ids))
        )
        resources.update({r.id: r for r in infrastructure.all()})
    mismatches = (
        await detect_mismatches(
            session,
            [(a.id, a.resource_id, wp.id) for a in own],
            {wp.id},
            ids,
        )
        if own
        else set()
    )
    unmet = await get_unmet_requirements(session, work_package_id=wp.id)
    default = await session.scalar(
        select(WorkWeekProfile).where(WorkWeekProfile.is_default)
    )
    limits: list[ReadinessLimit] = []
    if not personal_count:
        limits.append("no_personnel_requirements")
    if not infra_count:
        limits.append("no_infrastructure_requirements")
    if personal_count and default is None:
        limits.append("no_standard_profile")
    if personal_count and infra_count:
        limits.append("personnel_clock_times")
    if infra_count:
        limits.append("infrastructure_continuity")
    spans = [span for a in own if (span := assignment_span(a)) is not None]
    start = min([wp.start_date, *(s[0] for s in spans)])
    end = max([wp.end_date, *(s[1] for s in spans)])
    conflicts: list[ReadinessConflict] = []
    supply_gaps: list[PersonnelSupplyGap] = []
    if (end - start).days >= MAX_CHECK_DAYS or end == date.max:
        limits.append("capacity_window_limit")
    elif ids:
        # Include competing packages, clipped only in transient objects so long
        # historic/future bookings cannot expand this interactive check.
        lower = local_day_bounds(start, planning_zone())[0]
        upper = local_day_bounds(end, planning_zone())[1]
        competing = list(
            (
                await session.scalars(
                    select(Assignment).where(
                        Assignment.resource_id.in_(ids),
                        or_(
                            (Assignment.start_date <= end)
                            & (Assignment.end_date >= start),
                            (Assignment.start_at < upper) & (Assignment.end_at > lower),
                        ),
                    )
                )
            ).all()
        )
        grouped: dict[UUID, list[Assignment]] = {rid: [] for rid in ids}
        for booking in competing:
            clipped = _clip(booking, start, end)
            if clipped:
                grouped[booking.resource_id].append(clipped)
        working = WorkingTimeService(session)
        await working.prepare(list(ids), start, end)
        engine = ConflictService.from_data(
            session=session,
            working_time=working,
            resources=resources,
            assignments=grouped,
        )
        own_ids = {a.id for a in own}
        for rid in sorted(ids):
            for period in await engine.calculate_periods(rid):
                if not own_ids.intersection(period.assignment_ids):
                    continue
                conflicts.append(
                    ReadinessConflict(
                        **{
                            key: getattr(period, key)
                            for key in (
                                "cause",
                                "start_date",
                                "end_date",
                                "total_assigned_percent",
                                "available_percent",
                                "resource_id",
                                "resource_type",
                                "assignment_ids",
                            )
                        },
                        resource_name=resources[rid].name,
                    )
                )
            # A zero personal calendar suppresses demand in conflict detection.
            # Expose that separate evidence instead of inventing an overload.
            personal_bookings = [
                a
                for a in own
                if a.resource_id == rid and a.resource_type == ResourceType.personal
            ]
            missing = False
            first_zero = None
            for booking in personal_bookings:
                assert booking.start_date is not None and booking.end_date is not None
                day = booking.start_date
                while day <= booking.end_date:
                    missing |= working.profile_for(rid, day) is None
                    if (
                        default is not None
                        and default.minutes_for_weekday(day.weekday()) > 0
                        and working.calendar_minutes(rid, day) == 0
                        and first_zero is None
                    ):
                        first_zero = day
                    if day == booking.end_date:
                        break
                    day += timedelta(days=1)
            if missing and "missing_calendar" not in limits:
                limits.append("missing_calendar")
            if first_zero is not None:
                supply_gaps.append(
                    PersonnelSupplyGap(
                        resource_id=rid,
                        resource_name=resources[rid].name,
                        day=first_zero,
                    )
                )
    personal_status = _status(
        conflicts=any(c.resource_type == ResourceType.personal for c in conflicts),
        gaps=default is not None and any(u.resource_type == "personal" for u in unmet),
        unknown=not personal_count
        or default is None
        or bool(supply_gaps)
        or "missing_calendar" in limits
        or "capacity_window_limit" in limits,
    )
    infra_status = _status(
        conflicts=any(
            c.resource_type == ResourceType.infrastructure for c in conflicts
        ),
        gaps=any(u.resource_type == "infrastructure" for u in unmet),
        unknown=not infra_count or "capacity_window_limit" in limits,
    )
    qualification_status = _status(conflicts=bool(mismatches), unknown=not requirements)
    states = (personal_status, infra_status, qualification_status)
    status = _status(
        conflicts="conflicting" in states,
        gaps="missing_requirements" in states,
        unknown="not_fully_assessable" in states or bool(limits),
    )
    return WorkPackageReadiness(
        work_package=_package(wp, project_name),
        checked_at=datetime.now(UTC),
        status=status,
        personnel_status=personal_status,
        infrastructure_status=infra_status,
        qualification_status=qualification_status,
        personnel_requirements=personal_count,
        infrastructure_requirements=infra_count,
        limits=limits,
        supply_gaps=supply_gaps,
        unmet_requirements=unmet,
        conflicts=conflicts,
        assignments=[
            AssignmentResponse.model_validate(a).model_copy(
                update={
                    "resource_name": resources[a.resource_id].name,
                    "work_package_name": wp.name,
                    "project_id": wp.project_id,
                    "project_name": project_name,
                    "skill_mismatch": a.id in mismatches,
                }
            )
            for a in own
        ],
    )
