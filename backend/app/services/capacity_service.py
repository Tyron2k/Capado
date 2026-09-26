"""CapacityService: compute available capacity and utilization for resources.

Personal resources resolve their capacity through :class:`WorkingTimeService`,
so the dashboard and the conflict list cannot disagree about what a day holds
(ADR-004). Utilization is ``demand minutes / available minutes``: a 30 h/week
employee fully booked reads 100%, not 75%, because utilization is a statement
about that resource, not about a normative day.

Infrastructure resources deliberately keep the pre-existing percent logic —
exclusive occupancy, 100% per overlapping booking. Their availability windows
(ADR-005) change what counts as a *conflict* rather than what counts as
utilization, so they land with the conflict service instead of here.

Performance-critical paths (dashboard, capacity overview, project overview)
pre-load assignments and working-time data once per resource and iterate
in-memory rather than issuing per-day database queries.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.assignment import Assignment
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.services.time_zone import local_day_bounds, planning_zone
from app.services.working_time_service import (
    NORMATIVE_DAY_MINUTES,
    WorkingTimeService,
    minutes_to_percent,
    percent_to_minutes,
)


@dataclass
class DailyUtilization:
    """Daily utilization data for a resource.

    ``available`` and ``assigned`` stay in percent for API compatibility, both
    expressed against a normative working day: a resource with a 6-hour day
    reports ``available = 75.0``. The minute fields carry the absolute values
    for surfaces that want hours.
    """

    date: date
    available: float
    assigned: float
    utilization: float
    color: str
    available_minutes: int = 0
    assigned_minutes: int = 0


@dataclass
class WeeklyUtilization:
    """Weekly utilization data for a resource."""

    week_start: date
    total_available: float
    total_assigned: float
    utilization: float
    overbooked: float
    color: str
    available_minutes: int = 0
    assigned_minutes: int = 0
    working_days: int = 0


def get_utilization_color(utilization_percent: float) -> str:
    """Color code: < 80% green, 80-100% yellow, > 100% red."""
    if utilization_percent > 100:
        return "red"
    elif utilization_percent >= 80:
        return "yellow"
    else:
        return "green"


# One normative working day, expressed as a percentage. This is what
# ``allocation_percent = 100`` means (ADR-004) — it is NOT a claim that every
# calendar day carries capacity, which is the assumption this module replaced.
BASE_CAPACITY_PERCENT = 100.0


class CapacityService:
    """Compute available capacity and utilization for resources."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session and internal caches."""
        self.session = session
        self._resource_type_cache: dict[UUID, ResourceType | None] = {}
        self._assignments_cache: dict[UUID, list[Assignment]] = {}
        self._absences_cache: dict[UUID, list] = {}
        self._working_time: WorkingTimeService | None = None

    async def _get_working_time(
        self, resource_id: UUID, start: date, end: date
    ) -> WorkingTimeService:
        """Working-time service prepared for this resource and window."""
        service = WorkingTimeService(self.session)
        await service.prepare([resource_id], start, end)
        self._working_time = service
        return service

    async def _resolve_resource_type(self, resource_id: UUID) -> ResourceType | None:
        """Determine resource type (cached per service instance)."""
        if resource_id in self._resource_type_cache:
            return self._resource_type_cache[resource_id]

        personal = await self.session.get(PersonalResource, resource_id)
        if personal is not None:
            self._resource_type_cache[resource_id] = ResourceType.personal
            return ResourceType.personal

        infrastructure = await self.session.get(InfrastructureResource, resource_id)
        if infrastructure is not None:
            self._resource_type_cache[resource_id] = ResourceType.infrastructure
            return ResourceType.infrastructure

        self._resource_type_cache[resource_id] = None
        return None

    async def _get_assignments(self, resource_id: UUID) -> list[Assignment]:
        """Load all assignments for a resource (cached per service instance)."""
        if resource_id in self._assignments_cache:
            return self._assignments_cache[resource_id]

        statement = select(Assignment).where(Assignment.resource_id == resource_id)
        result = await self.session.execute(statement)
        assignments = list(result.scalars().all())
        self._assignments_cache[resource_id] = assignments
        return assignments

    async def _get_absences(self, resource_id: UUID) -> list:
        """Load all absences for a resource (cached per service instance)."""
        if resource_id in self._absences_cache:
            return self._absences_cache[resource_id]

        from app.models.absence import Absence

        statement = select(Absence).where(Absence.resource_id == resource_id)
        result = await self.session.execute(statement)
        absences = list(result.scalars().all())
        self._absences_cache[resource_id] = absences
        return absences

    def _assigned_percent_for_day(
        self, assignments: list[Assignment], resource_type: ResourceType, day: date
    ) -> float:
        """Raw assigned percentage from pre-loaded assignments (no DB, no calendar).

        Personal: sums ``allocation_percent`` of all active assignments for the
        day. Infrastructure: 100% per overlapping interval (exclusive booking).

        This is the unfiltered demand. The calendar gate — an assignment places
        no demand on a non-working day — is applied by the callers below, not
        here, so this stays a pure function over its arguments.
        """
        day_start, day_end = local_day_bounds(day, planning_zone())

        total = 0.0
        for a in assignments:
            if resource_type == ResourceType.personal:
                if (
                    a.start_date is not None
                    and a.end_date is not None
                    and a.start_date <= day <= a.end_date
                    and a.allocation_percent is not None
                ):
                    total += a.allocation_percent
            elif a.start_at is not None and a.end_at is not None:
                overlap_start = max(a.start_at, day_start)
                overlap_end = min(a.end_at, day_end)
                if overlap_end > overlap_start:
                    # Infrastructure is always 100% per booking
                    total += 100.0
        return total

    def _absence_percent_for_day(self, absences: list, day: date) -> float:
        """Compute total absence percentage for a day."""
        total = 0.0
        for ab in absences:
            if ab.start_date <= day <= ab.end_date:
                total += ab.allocation_percent
        return total

    def _day_minutes(
        self,
        working_time: WorkingTimeService,
        assignments: list[Assignment],
        resource_id: UUID,
        resource_type: ResourceType,
        day: date,
    ) -> tuple[int, int]:
        """Available and demanded minutes for one resource on one day."""
        if resource_type == ResourceType.infrastructure:
            # Unchanged semantics: exclusive occupancy expressed in percent,
            # mapped onto the normative day so both types share one unit.
            demand_percent = self._assigned_percent_for_day(
                assignments, resource_type, day
            )
            return NORMATIVE_DAY_MINUTES, percent_to_minutes(demand_percent)

        available = working_time.available_minutes(resource_id, day)
        if not working_time.is_working_day(resource_id, day):
            return available, 0

        demand_percent = self._assigned_percent_for_day(assignments, resource_type, day)
        return available, percent_to_minutes(demand_percent)

    # --- Public API ---

    async def calculate_available_capacity(self, resource_id: UUID, day: date) -> float:
        """Available capacity for a resource on a day, as percent of a normal day.

        Zero on weekends, public holidays, and days fully covered by an absence.
        """
        rtype = await self._resolve_resource_type(resource_id)
        if rtype is None:
            return 0.0
        if rtype == ResourceType.infrastructure:
            return BASE_CAPACITY_PERCENT

        working_time = await self._get_working_time(resource_id, day, day)
        return minutes_to_percent(working_time.available_minutes(resource_id, day))

    async def get_assigned_percent(self, resource_id: UUID, day: date) -> float:
        """Demanded percentage for a resource on a day.

        Absences are no longer added here: they reduce *availability* rather
        than adding demand (ADR-004). Adding both would count a vacation twice.
        """
        rtype = await self._resolve_resource_type(resource_id)
        if rtype is None:
            return 0.0

        assignments = await self._get_assignments(resource_id)
        working_time = await self._get_working_time(resource_id, day, day)
        _, demand_minutes = self._day_minutes(
            working_time, assignments, resource_id, rtype, day
        )
        return minutes_to_percent(demand_minutes)

    async def calculate_utilization(
        self, resource_id: UUID, start_date: date, end_date: date
    ) -> list[DailyUtilization]:
        """Daily utilization for a resource over a date range."""
        assignments = await self._get_assignments(resource_id)
        return await self.calculate_utilization_for_assignments(
            resource_id, start_date, end_date, assignments
        )

    async def calculate_utilization_for_assignments(
        self,
        resource_id: UUID,
        start_date: date,
        end_date: date,
        assignments: list[Assignment],
    ) -> list[DailyUtilization]:
        """Calculate daily utilization from supplied, possibly hypothetical rows."""
        rtype = await self._resolve_resource_type(resource_id)
        if rtype is None:
            return []

        working_time = await self._get_working_time(resource_id, start_date, end_date)

        results: list[DailyUtilization] = []
        current = start_date
        while current <= end_date:
            available_minutes, assigned_minutes = self._day_minutes(
                working_time, assignments, resource_id, rtype, current
            )
            utilization = (
                assigned_minutes / available_minutes * 100.0
                if available_minutes > 0
                else (100.0 if assigned_minutes > 0 else 0.0)
            )
            results.append(
                DailyUtilization(
                    date=current,
                    available=minutes_to_percent(available_minutes),
                    assigned=minutes_to_percent(assigned_minutes),
                    utilization=utilization,
                    color=get_utilization_color(utilization),
                    available_minutes=available_minutes,
                    assigned_minutes=assigned_minutes,
                )
            )
            current += timedelta(days=1)

        return results

    async def get_weekly_utilization(
        self, resource_id: UUID, start_week: date, end_week: date
    ) -> list[WeeklyUtilization]:
        """Weekly utilization for a resource.

        ``working_days`` counts only days the calendar grants time. The previous
        implementation counted all seven, which is where the systematic ~28%
        capacity overstatement came from.
        """
        rtype = await self._resolve_resource_type(resource_id)
        if rtype is None:
            return []

        assignments = await self._get_assignments(resource_id)
        current_monday = start_week - timedelta(days=start_week.weekday())
        last_day = end_week + timedelta(days=6)
        working_time = await self._get_working_time(
            resource_id, current_monday, last_day
        )

        weeks: list[WeeklyUtilization] = []
        while current_monday <= end_week:
            available_minutes = 0
            assigned_minutes = 0
            overbooked_minutes = 0
            working_days = 0

            for offset in range(7):
                day = current_monday + timedelta(days=offset)
                day_available, day_assigned = self._day_minutes(
                    working_time, assignments, resource_id, rtype, day
                )
                available_minutes += day_available
                assigned_minutes += day_assigned
                if day_assigned > day_available:
                    overbooked_minutes += day_assigned - day_available
                if day_available > 0 or day_assigned > 0:
                    working_days += 1

            utilization = (
                assigned_minutes / available_minutes * 100.0
                if available_minutes > 0
                else (100.0 if assigned_minutes > 0 else 0.0)
            )
            overbooked = (
                overbooked_minutes / available_minutes * 100.0
                if available_minutes > 0
                else 0.0
            )
            weeks.append(
                WeeklyUtilization(
                    week_start=current_monday,
                    total_available=minutes_to_percent(available_minutes),
                    total_assigned=minutes_to_percent(assigned_minutes),
                    utilization=utilization,
                    overbooked=overbooked,
                    color=get_utilization_color(utilization),
                    available_minutes=available_minutes,
                    assigned_minutes=assigned_minutes,
                    working_days=working_days,
                )
            )
            current_monday += timedelta(weeks=1)

        return weeks
