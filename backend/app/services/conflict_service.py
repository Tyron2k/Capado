"""ConflictService: Detection and management of capacity conflicts.

Personal conflicts arise when the minutes demanded by overlapping assignments
exceed the minutes the resource actually has available on that day — week
profile and site calendar minus absences, resolved by
:class:`WorkingTimeService` (ADR-004). This replaced a fixed comparison against
100%, which treated every calendar day as a full working day.

Two consequences of that model are deliberate and easy to mistake for bugs:

- A weekend or public holiday grants no capacity, so an assignment spanning it
  places no demand and raises no conflict. Without this, every multi-week
  assignment would flag both weekend days.
- A vacation day still *is* a working day in the calendar, so an assignment on
  it demands its full time against zero availability and is reported — the
  "on leave but assigned" signal.

Infrastructure conflicts remain time-interval overlaps (``start_at`` /
``end_at``, minute granularity), since infrastructure is exclusive rather than
proportionally allocated. Bookings outside an availability window are a
separate conflict cause (ADR-005).

Conflicts are stored per resource as ``Conflict``, with ``ConflictAssignment``
as a join table to the involved assignments. The stored percentages are derived
from minutes so the API shape stays stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
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
class ConflictDay:
    """A single day with a capacity conflict (personal)."""

    date: date
    available: float
    assigned: float
    assignment_ids: list[UUID] = field(default_factory=list)


@dataclass
class ConflictPeriod:
    """A contiguous conflict period."""

    resource_id: UUID
    resource_type: ResourceType
    start_date: date
    end_date: date
    total_assigned_percent: float
    available_percent: float
    cause: ConflictCause = ConflictCause.over_allocation
    assignment_ids: list[UUID] = field(default_factory=list)


class ConflictService:
    """Detect and manage capacity conflicts for resources."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session
        self._working_time: WorkingTimeService | None = None
        self._preloaded_resources: dict[UUID, ResourceType] | None = None
        self._preloaded_assignments: dict[UUID, list[Assignment]] | None = None

    @classmethod
    def from_data(
        cls,
        *,
        session: AsyncSession,
        working_time: WorkingTimeService,
        resources: dict[UUID, PersonalResource | InfrastructureResource],
        assignments: dict[UUID, list[Assignment]],
    ) -> ConflictService:
        """Build a service with data supplied directly, bypassing the database.

        A seam for tests: the conflict-detection logic is a pure function over
        these inputs, and the project tests services with hand-built doubles
        rather than a live database. Reaching into private caches from a test
        would couple it to internals that are free to change.
        """
        service = cls(session)
        service._working_time = working_time
        service._preloaded_resources = {}
        for rid, resource in resources.items():
            if isinstance(resource, PersonalResource):
                service._preloaded_resources[rid] = ResourceType.personal
            elif isinstance(resource, InfrastructureResource):
                service._preloaded_resources[rid] = ResourceType.infrastructure
        service._preloaded_assignments = assignments
        return service

    # ------------------------------------------------------------------ helpers

    async def _get_resource_type(self, resource_id: UUID) -> ResourceType | None:
        if self._preloaded_resources is not None:
            return self._preloaded_resources.get(resource_id)
        personal = await self.session.get(PersonalResource, resource_id)
        if personal is not None:
            return ResourceType.personal
        infrastructure = await self.session.get(InfrastructureResource, resource_id)
        if infrastructure is not None:
            return ResourceType.infrastructure
        return None

    async def _get_assignments_for_resource(
        self, resource_id: UUID
    ) -> list[Assignment]:
        if self._preloaded_assignments is not None:
            return self._preloaded_assignments.get(resource_id, [])
        statement = (
            select(Assignment)
            .where(Assignment.resource_id == resource_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    # ------------------------------------------------------------------ personal

    async def group_consecutive_conflict_days(
        self,
        conflict_days: list[ConflictDay],
        resource_id: UUID,
        resource_type: ResourceType,
    ) -> list[ConflictPeriod]:
        """Group consecutive conflict days into periods.

        Two conflict days are merged into the same period when they are on
        consecutive calendar days (gap == 1) or share the same triggering
        assignments.
        """
        if not conflict_days:
            return []
        sorted_days = sorted(conflict_days, key=lambda d: d.date)
        periods: list[ConflictPeriod] = []
        current_group: list[ConflictDay] = [sorted_days[0]]

        def same_cause(a: ConflictDay, b: ConflictDay) -> bool:
            return set(a.assignment_ids) == set(b.assignment_ids)

        for i in range(1, len(sorted_days)):
            prev = sorted_days[i - 1]
            curr = sorted_days[i]
            gap_days = (curr.date - prev.date).days
            merge = gap_days == 1 or same_cause(prev, curr)

            if merge:
                current_group.append(curr)
            else:
                periods.append(
                    self._make_personal_period(
                        current_group, resource_id, resource_type
                    )
                )
                current_group = [curr]
        periods.append(
            self._make_personal_period(current_group, resource_id, resource_type)
        )
        return periods

    def _make_personal_period(
        self,
        days: list[ConflictDay],
        resource_id: UUID,
        resource_type: ResourceType,
    ) -> ConflictPeriod:
        all_ids: set[UUID] = set()
        for day in days:
            all_ids.update(day.assignment_ids)
        max_assigned = max(d.assigned for d in days)
        day_with_max = max(days, key=lambda d: d.assigned - d.available)
        return ConflictPeriod(
            resource_id=resource_id,
            resource_type=resource_type,
            cause=(
                ConflictCause.over_allocation
                if resource_type == ResourceType.personal
                else ConflictCause.booking_overlap
            ),
            start_date=days[0].date,
            end_date=days[-1].date,
            total_assigned_percent=max_assigned,
            available_percent=day_with_max.available,
            assignment_ids=list(all_ids),
        )

    # ------------------------------------------------------------------ infra

    def _emit_infrastructure_period(
        self,
        resource_id: UUID,
        cluster: list[tuple[datetime, datetime, UUID | None]],
        assignment_ids: set[UUID],
    ) -> list[ConflictPeriod]:
        """Find actual overlap periods within a cluster of intervals.

        Uses a sweep-line approach: collect all start/end events, sweep through
        them, and emit a ConflictPeriod for each contiguous span where 2+
        intervals are active simultaneously.
        """
        if len(cluster) < 2:
            return []

        # Build events: +1 at start, -1 at end
        events: list[tuple[datetime, int, UUID | None]] = []
        for start, end, aid in cluster:
            events.append((start, +1, aid))
            events.append((end, -1, aid))
        events.sort(key=lambda e: (e[0], e[1]))  # ties: ends before starts

        periods: list[ConflictPeriod] = []
        active_count = 0
        conflict_start: datetime | None = None
        max_concurrent = 0

        for event_time, delta, _ in events:
            if active_count >= 2 and delta == -1 and active_count + delta < 2:
                # Conflict period ends here
                if conflict_start and event_time > conflict_start:
                    periods.append(
                        ConflictPeriod(
                            resource_id=resource_id,
                            resource_type=ResourceType.infrastructure,
                            cause=ConflictCause.booking_overlap,
                            start_date=conflict_start.date(),
                            end_date=event_time.date(),
                            total_assigned_percent=max_concurrent * 100.0,
                            available_percent=100.0,
                            assignment_ids=list(assignment_ids),
                        )
                    )
                conflict_start = None
                max_concurrent = 0

            active_count += delta

            if active_count >= 2 and conflict_start is None:
                # Conflict period starts here
                conflict_start = event_time
                max_concurrent = active_count
            elif active_count >= 2:
                max_concurrent = max(max_concurrent, active_count)

        # Handle case where conflict extends to the end
        if conflict_start is not None and active_count >= 2:
            end_time = max(entry[1] for entry in cluster)
            periods.append(
                ConflictPeriod(
                    resource_id=resource_id,
                    resource_type=ResourceType.infrastructure,
                    cause=ConflictCause.booking_overlap,
                    start_date=conflict_start.date(),
                    end_date=end_time.date(),
                    total_assigned_percent=max_concurrent * 100.0,
                    available_percent=100.0,
                    assignment_ids=list(assignment_ids),
                )
            )

        return periods

    # ------------------------------------------------------------------ persistence

    def _get_date_range(
        self, assignments: list[Assignment], resource_type: ResourceType
    ) -> tuple[date, date] | None:
        """Overall date range of all assignments for a resource."""
        dates: list[date] = []
        for a in assignments:
            if resource_type == ResourceType.personal:
                if a.start_date is not None:
                    dates.append(a.start_date)
                if a.end_date is not None:
                    dates.append(a.end_date)
            else:
                if a.start_at is not None:
                    dates.append(a.start_at.date())
                if a.end_at is not None:
                    dates.append(a.end_at.date())
        if not dates:
            return None
        return min(dates), max(dates)

    async def _delete_conflicts_for_resource(self, resource_id: UUID) -> None:
        """Delete all conflicts and their junction records for a resource.

        Uses bulk DELETE statements instead of individual session.delete() calls
        to minimize round-trips for resources with many conflicts.
        """
        from sqlalchemy import delete

        statement = select(Conflict.id).where(Conflict.resource_id == resource_id)
        result = await self.session.execute(statement)
        conflict_ids = list(result.scalars().all())

        if not conflict_ids:
            return

        # Bulk-delete ConflictAssignment rows referencing these conflicts
        await self.session.execute(
            delete(ConflictAssignment).where(
                ConflictAssignment.conflict_id.in_(conflict_ids)
            )
        )

        # Bulk-delete Conflict rows
        await self.session.execute(
            delete(Conflict).where(Conflict.resource_id == resource_id)
        )

    async def _save_conflict_periods(
        self, periods: list[ConflictPeriod]
    ) -> list[Conflict]:
        saved: list[Conflict] = []
        for period in periods:
            conflict = Conflict(
                resource_id=period.resource_id,
                resource_type=period.resource_type,
                cause=period.cause,
                start_date=period.start_date,
                end_date=period.end_date,
                total_assigned_percent=period.total_assigned_percent,
                available_percent=period.available_percent,
            )
            self.session.add(conflict)
            await self.session.flush()
            for assignment_id in period.assignment_ids:
                self.session.add(
                    ConflictAssignment(
                        conflict_id=conflict.id, assignment_id=assignment_id
                    )
                )
            saved.append(conflict)
        return saved

    async def refresh_conflicts(self, resource_id: UUID) -> list[Conflict]:
        """Serialize recalculations and atomically replace a resource's results.

        The transaction lock covers reading inputs through committing results. All
        entry points (edits, imports, scheduled runs) use this same boundary.
        """
        try:
            if (
                isinstance(self.session, AsyncSession)
                and self.session.get_bind().dialect.name == "postgresql"
            ):
                await self.session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": resource_id.int % (2**63 - 1)},
                )
            return await self._refresh_conflicts(resource_id)
        except BaseException:
            await self.session.rollback()
            raise

    async def _refresh_conflicts(self, resource_id: UUID) -> list[Conflict]:
        """Recalculate and persist conflicts for a resource.

        Uses an event-driven sweep-line algorithm instead of iterating each
        calendar day. Personal assignments are swept into stable date spans;
        infrastructure bookings are swept at timestamp precision. Complexity
        is O(n log n) in the number of interval endpoints rather than
        O(days × assignments).
        """
        periods = await self.calculate_periods(resource_id)
        return await self._replace_periods(resource_id, periods)

    async def calculate_periods(
        self, resource_id: UUID, assignments: list[Assignment] | None = None
    ) -> list[ConflictPeriod]:
        """Calculate conflicts without changing the session or stored conflicts.

        Preview and persistence use this same calculation. The optional
        assignments replace database rows with a hypothetical schedule.
        """
        resource_type = await self._get_resource_type(resource_id)
        if resource_type is None:
            return []

        # Load all assignments for this resource
        all_assignments = (
            assignments
            if assignments is not None
            else await self._get_assignments_for_resource(resource_id)
        )
        if not all_assignments:
            return []

        # Determine date range
        date_range = self._get_date_range(all_assignments, resource_type)
        if date_range is None:
            return []
        start_date, end_date = date_range

        # Absences are NOT demand intervals. They reduce availability, and
        # WorkingTimeService owns that (ADR-004). Adding them here as well would
        # count a vacation twice: once against supply, once as demand.
        if self._working_time is not None:
            working_time = self._working_time
        else:
            working_time = WorkingTimeService(self.session)
            await working_time.prepare([resource_id], start_date, end_date)

        if resource_type == ResourceType.infrastructure:
            periods = self._infrastructure_overlaps(all_assignments, resource_id)
            periods.extend(
                self._detect_window_violations(
                    all_assignments, resource_id, working_time
                )
            )
            return periods

        # Build day-range intervals: (start_inclusive, end_inclusive, pct, id|None)
        intervals: list[tuple[date, date, float, UUID | None]] = []

        for a in all_assignments:
            if a.start_date is not None and a.end_date is not None:
                intervals.append(
                    (a.start_date, a.end_date, a.allocation_percent or 0.0, a.id)
                )

        if not intervals:
            return []

        # Sweep-line: boundaries are where the active ASSIGNMENT SET changes.
        # Capacity itself varies per day (weekend, holiday, absence), so each
        # span is still walked day by day — but the active set and its ids are
        # resolved once per span rather than once per day, which is what keeps
        # this O(days + n log n) instead of O(days × assignments).
        boundary_dates: set[date] = set()
        for s, e, _, _ in intervals:
            boundary_dates.add(s)
            boundary_dates.add(e + timedelta(days=1))  # day after end
        sorted_boundaries = sorted(boundary_dates)

        conflict_days: list[ConflictDay] = []
        for i in range(len(sorted_boundaries) - 1):
            span_start = sorted_boundaries[i]
            span_end = sorted_boundaries[i + 1] - timedelta(days=1)
            if span_end < span_start:
                continue

            demand_percent = 0.0
            active_ids: list[UUID] = []
            for iv_start, iv_end, pct, aid in intervals:
                if iv_start <= span_start and iv_end >= span_end:
                    demand_percent += pct
                    if aid is not None:
                        active_ids.append(aid)

            if demand_percent <= 0.0:
                continue

            current = span_start
            while current <= span_end:
                available_minutes = working_time.available_minutes(resource_id, current)
                is_working = working_time.is_working_day(resource_id, current)
                demand_minutes = percent_to_minutes(demand_percent) if is_working else 0

                if demand_minutes > available_minutes:
                    conflict_days.append(
                        ConflictDay(
                            date=current,
                            available=minutes_to_percent(available_minutes),
                            assigned=minutes_to_percent(demand_minutes),
                            assignment_ids=active_ids,
                        )
                    )
                current += timedelta(days=1)

        # Group consecutive conflict days into periods
        periods = await self.group_consecutive_conflict_days(
            conflict_days, resource_id, resource_type
        )

        return periods

    async def _replace_periods(
        self, resource_id: UUID, periods: list[ConflictPeriod]
    ) -> list[Conflict]:
        # Calculate first. DELETE + INSERT then share one transaction, so readers
        # see either the old complete result or the new one, never an empty gap.
        if isinstance(self.session, AsyncSession):
            existing = list(
                (
                    await self.session.execute(
                        select(Conflict).where(Conflict.resource_id == resource_id)
                    )
                )
                .scalars()
                .all()
            )
            if existing:
                links = (
                    (
                        await self.session.execute(
                            select(ConflictAssignment).where(
                                ConflictAssignment.conflict_id.in_(
                                    [c.id for c in existing]
                                )
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                ids: dict[UUID, set[UUID]] = {}
                for link in links:
                    ids.setdefault(link.conflict_id, set()).add(link.assignment_id)

                def signature(c, assignments):
                    return (
                        c.cause,
                        c.start_date,
                        c.end_date,
                        c.total_assigned_percent,
                        c.available_percent,
                        tuple(sorted(assignments)),
                    )

                old = sorted(signature(c, ids.get(c.id, set())) for c in existing)
                new = sorted(signature(p, p.assignment_ids) for p in periods)
                if old == new:
                    await self.session.commit()
                    return existing
        await self._delete_conflicts_for_resource(resource_id)
        saved = await self._save_conflict_periods(periods)
        await self.session.commit()
        return saved

    def _infrastructure_overlaps(
        self, assignments: list[Assignment], resource_id: UUID
    ) -> list[ConflictPeriod]:
        """Half-open booking intervals: an end at 10:00 permits a start at 10:00.

        Emit only the assignments actually overlapping in each span. A third
        booking elsewhere in a connected cluster must not inherit a conflict.
        """
        events: dict[datetime, list[tuple[int, UUID]]] = {}
        for assignment in assignments:
            if assignment.start_at is None or assignment.end_at is None:
                continue
            events.setdefault(assignment.start_at, []).append((1, assignment.id))
            events.setdefault(assignment.end_at, []).append((-1, assignment.id))
        active: set[UUID] = set()
        previous: datetime | None = None
        periods: list[ConflictPeriod] = []
        for moment in sorted(events):
            if previous is not None and moment > previous and len(active) > 1:
                periods.append(
                    ConflictPeriod(
                        resource_id=resource_id,
                        resource_type=ResourceType.infrastructure,
                        cause=ConflictCause.booking_overlap,
                        start_date=previous.date(),
                        end_date=(moment - timedelta(microseconds=1)).date(),
                        total_assigned_percent=len(active) * 100.0,
                        available_percent=100.0,
                        assignment_ids=sorted(active),
                    )
                )
            for delta, aid in sorted(events[moment]):
                if delta < 0:
                    active.discard(aid)
                else:
                    active.add(aid)
            previous = moment
        return periods

    def _detect_window_violations(
        self,
        assignments: list[Assignment],
        resource_id: UUID,
        working_time: WorkingTimeService,
    ) -> list[ConflictPeriod]:
        """Bookings that fall outside the resource's availability windows.

        A per-booking check rather than part of the sweep: this is not about how
        much is booked but about *when*, so folding it into the overlap path
        would conflate two causes that need different resolutions (ADR-005).

        Returns nothing when the resource defines no windows at all — that means
        unrestricted, which keeps every plan made before windows existed valid.
        """
        if not working_time.has_windows(resource_id):
            return []

        periods: list[ConflictPeriod] = []
        for assignment in assignments:
            if assignment.start_at is None or assignment.end_at is None:
                continue

            offending: list[date] = []
            booked_minutes = 0
            allowed_minutes = 0

            day = assignment.start_at.date()
            last_day = assignment.end_at.date()
            while day <= last_day:
                day_start = datetime.combine(day, datetime.min.time())
                overlap_start = max(assignment.start_at, day_start)
                overlap_end = min(assignment.end_at, day_start + timedelta(days=1))
                if overlap_end <= overlap_start:
                    day += timedelta(days=1)
                    continue

                start_minute = overlap_start.hour * 60 + overlap_start.minute
                end_minute = start_minute + int(
                    (overlap_end - overlap_start).total_seconds() // 60
                )
                booked_minutes += end_minute - start_minute

                covered = working_time.covered_minutes_within(
                    resource_id, day, start_minute, end_minute
                )
                allowed_minutes += covered

                if covered < end_minute - start_minute:
                    offending.append(day)

                day += timedelta(days=1)

            if offending:
                periods.append(
                    ConflictPeriod(
                        resource_id=resource_id,
                        resource_type=ResourceType.infrastructure,
                        cause=ConflictCause.outside_availability,
                        start_date=min(offending),
                        end_date=max(offending),
                        total_assigned_percent=minutes_to_percent(booked_minutes),
                        available_percent=minutes_to_percent(allowed_minutes),
                        assignment_ids=[assignment.id],
                    )
                )

        return periods

    async def get_conflicts_for_resource(self, resource_id: UUID) -> list[Conflict]:
        """Return all conflicts for a specific resource."""
        statement = select(Conflict).where(Conflict.resource_id == resource_id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_all_conflicts(self) -> list[Conflict]:
        """Return all conflicts across all resources."""
        statement = select(Conflict)
        result = await self.session.execute(statement)
        return list(result.scalars().all())
