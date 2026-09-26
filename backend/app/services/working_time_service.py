"""WorkingTimeService: the single source of truth for available working time.

Both ``CapacityService`` (what the dashboard shows) and ``ConflictService``
(what the planning page flags) resolve capacity through this service. They must
agree exactly — a dashboard that reports 90% utilization next to a conflict list
claiming over-allocation for the same day is worse than either being wrong
alone.

The model has three distinct layers, and conflating them is the mistake this
docstring exists to prevent (ADR-004):

**Calendar minutes** — the working-time supply from the week profile, overridden
by a holiday row for that site and date. Zero on a weekend or public holiday.

**Available minutes** — calendar minutes reduced by absences. An absence is a
*share of the resource's own day*: a full-day vacation removes exactly that
resource's day, whether that is 8 hours or 6.

**Demand minutes** — what assignments ask for. ``allocation_percent`` is a share
of a *normative* working day, not of the individual resource, so assigning a
30 h/week employee at 100% demands 480 minutes against 360 available and is
correctly reported as a conflict.

Demand is gated on **calendar** minutes, not on available minutes. That
distinction carries real weight:

- Sunday: calendar 0, so no demand and no conflict — otherwise every assignment
  spanning a weekend would raise one, and the feature would be unusable.
- Vacation day: calendar 480 (it is a working day), available 0, demand 480 →
  conflict. This preserves the "on leave but assigned" signal that exists
  today.
- Public holiday: calendar 0, so no demand and no conflict. The work assigned
  across it quietly delivers less time than planned, which is a *shortfall*
  rather than an over-allocation, and belongs to the unmet-requirements
  surface.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.absence import Absence, AbsenceStatus
from app.models.calendar import (
    MINUTES_PER_DAY,
    Holiday,
    InfrastructureAvailabilityWindow,
    ResourceWorkProfile,
    WorkWeekProfile,
)
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.resource_group import ResourceGroup
from app.services.time_zone import local_wall_time_to_utc, planning_zone

# A share of this is what allocation_percent means. Kept as a module constant
# rather than a settings field for now: changing it retroactively reinterprets
# every existing assignment, so it needs a migration story before it becomes
# configurable.
NORMATIVE_DAY_MINUTES = 480


def percent_to_minutes(allocation_percent: float) -> int:
    """Convert an allocation percentage into normative-day minutes.

    Rounded once, at the boundary, so everything downstream sums integers and
    cannot drift (ADR-004).
    """
    return int(round(allocation_percent / 100.0 * NORMATIVE_DAY_MINUTES))


def minutes_to_percent(minutes: int) -> float:
    """Express absolute minutes as a share of a normative working day.

    The inverse of :func:`percent_to_minutes`, and it lives here for that reason. It previously
    existed as a private ``_minutes_to_percent`` in three services — ``capacity_service``,
    ``conflict_service`` and ``conflict_suggestion_service`` — with byte-identical bodies and
    docstrings. All three already imported ``NORMATIVE_DAY_MINUTES`` from this module, so the
    constant had a canonical home while its two conversions did not.

    The cost of that was latent rather than active: the copies agreed. They were, however, the three
    places that would have had to change together if the normative day ever stopped being a
    constant — and each being private meant nothing could enforce that.
    """
    return minutes / NORMATIVE_DAY_MINUTES * 100.0


class WorkingTimeService:
    """Resolve calendar, available and demand minutes for resources.

    Call :meth:`prepare` once with the resources and date range in play, then
    use the synchronous accessors. Loading up front keeps the per-day hot loops
    free of database round-trips, which is what makes the sweep in
    ``ConflictService`` and the dashboard's weekly aggregation affordable.
    """

    def __init__(self, session: AsyncSession):
        """Initialize with a database session and empty caches."""
        self.session = session
        self._default_profile: WorkWeekProfile | None = None
        self._profiles: dict[UUID, WorkWeekProfile] = {}
        self._bindings: dict[UUID, list[ResourceWorkProfile]] = {}
        self._group_bindings: dict[UUID, list[ResourceWorkProfile]] = {}
        self._group_of_resource: dict[UUID, UUID | None] = {}
        self._group_parent: dict[UUID, UUID | None] = {}
        self._site_of_resource: dict[UUID, UUID | None] = {}
        self._holidays: dict[tuple[UUID, date], int] = {}
        self._absences: dict[UUID, list[Absence]] = {}
        self._windows: dict[UUID, list[InfrastructureAvailabilityWindow]] = {}
        self._prepared = False

    # ------------------------------------------------------------------ load

    async def prepare(self, resource_ids: list[UUID], start: date, end: date) -> None:
        """Bulk-load everything needed to answer questions about this window."""
        await self._load_profiles()
        if resource_ids:
            await self._load_bindings(resource_ids)
            await self._load_sites(resource_ids)
            await self._load_absences(resource_ids, start, end)
            await self._load_windows(resource_ids)
            await self._load_group_hierarchy()
            await self._load_holidays(start, end)
        self._prepared = True

    async def _load_group_hierarchy(self) -> None:
        """Parent links for resource groups, so a binding can be inherited.

        Loaded wholesale: the hierarchy is small (documented maximum depth 2) and
        walking it per resource would otherwise cost a query per level.
        """
        result = await self.session.execute(
            select(ResourceGroup.id, ResourceGroup.parent_id)
        )
        for group_id, parent_id in result.all():
            self._group_parent[group_id] = parent_id

    async def _load_windows(self, resource_ids: list[UUID]) -> None:
        statement = select(InfrastructureAvailabilityWindow).where(
            InfrastructureAvailabilityWindow.resource_id.in_(resource_ids)
        )
        result = await self.session.execute(statement)
        for window in result.scalars().all():
            self._windows.setdefault(window.resource_id, []).append(window)

    @classmethod
    def from_data(
        cls,
        *,
        default_profile: WorkWeekProfile | None = None,
        bindings: dict[UUID, list[ResourceWorkProfile]] | None = None,
        group_bindings: dict[UUID, list[ResourceWorkProfile]] | None = None,
        groups: dict[UUID, UUID | None] | None = None,
        group_parents: dict[UUID, UUID | None] | None = None,
        profiles: dict[UUID, WorkWeekProfile] | None = None,
        sites: dict[UUID, UUID | None] | None = None,
        holidays: dict[tuple[UUID, date], int] | None = None,
        absences: dict[UUID, list[Absence]] | None = None,
        windows: dict[UUID, list[InfrastructureAvailabilityWindow]] | None = None,
    ) -> WorkingTimeService:
        """Build a service with data supplied directly, bypassing the database.

        A seam for tests: every accessor below is a pure function over these
        caches, and the project tests services with hand-built doubles rather
        than a live database. Reaching into the private caches from a test would
        couple it to internals that are free to change.
        """
        service = cls.__new__(cls)
        service.session = None  # type: ignore[assignment]
        service._default_profile = default_profile
        service._profiles = profiles or {}
        service._bindings = bindings or {}
        service._group_bindings = group_bindings or {}
        service._group_of_resource = groups or {}
        service._group_parent = group_parents or {}
        service._site_of_resource = sites or {}
        service._holidays = holidays or {}
        service._absences = absences or {}
        service._windows = windows or {}
        service._prepared = True
        return service

    async def _load_profiles(self) -> None:
        result = await self.session.execute(select(WorkWeekProfile))
        for profile in result.scalars().all():
            self._profiles[profile.id] = profile
            if profile.is_default:
                self._default_profile = profile

    async def _load_bindings(self, resource_ids: list[UUID]) -> None:
        statement = select(ResourceWorkProfile).where(
            ResourceWorkProfile.resource_id.in_(resource_ids)
        )
        result = await self.session.execute(statement)
        for binding in result.scalars().all():
            if binding.resource_id is not None:
                self._bindings.setdefault(binding.resource_id, []).append(binding)

        # Group bindings are few (one per department at most) and are needed for
        # every resource, so they are loaded wholesale rather than per group.
        group_statement = select(ResourceWorkProfile).where(
            ResourceWorkProfile.group_id.is_not(None)
        )
        group_result = await self.session.execute(group_statement)
        for binding in group_result.scalars().all():
            if binding.group_id is not None:
                self._group_bindings.setdefault(binding.group_id, []).append(binding)

    async def _load_sites(self, resource_ids: list[UUID]) -> None:
        for model in (PersonalResource, InfrastructureResource):
            statement = select(model.id, model.site_id, model.group_id).where(
                model.id.in_(resource_ids)
            )
            result = await self.session.execute(statement)
            for resource_id, site_id, group_id in result.all():
                self._site_of_resource[resource_id] = site_id
                self._group_of_resource[resource_id] = group_id

    async def _load_absences(
        self, resource_ids: list[UUID], start: date, end: date
    ) -> None:
        statement = select(Absence).where(
            Absence.resource_id.in_(resource_ids),
            Absence.start_date <= end,
            Absence.end_date >= start,
        )
        result = await self.session.execute(statement)
        for absence in result.scalars().all():
            self._absences.setdefault(absence.resource_id, []).append(absence)

    async def _load_holidays(self, start: date, end: date) -> None:
        statement = select(Holiday).where(Holiday.day >= start, Holiday.day <= end)
        result = await self.session.execute(statement)
        for holiday in result.scalars().all():
            self._holidays[(holiday.site_id, holiday.day)] = holiday.working_minutes

    # ------------------------------------------------------------- accessors

    def profile_for(self, resource_id: UUID, day: date) -> WorkWeekProfile | None:
        """Week profile in force for a resource on a day.

        Resolution order, most specific first:

        1. a binding on the resource itself,
        2. a binding on the resource's own group,
        3. a binding on that group's parent,
        4. the default profile.

        The order is what makes group bindings usable: a department states its
        hours once and an individual row overrides it for the one part-time
        employee, rather than every person needing a row of their own.

        Falls back to the default profile so a fresh install has capacity instead
        of reporting zero everywhere.
        """
        for binding in self._bindings.get(resource_id, ()):
            if binding.covers(day):
                profile = self._profiles.get(binding.profile_id)
                if profile is not None:
                    return profile

        for group_id in self._group_chain(resource_id):
            for binding in self._group_bindings.get(group_id, ()):
                if binding.covers(day):
                    profile = self._profiles.get(binding.profile_id)
                    if profile is not None:
                        return profile

        return self._default_profile

    def _group_chain(self, resource_id: UUID) -> list[UUID]:
        """The resource's group, then its ancestors, nearest first."""
        group_id = self._group_of_resource.get(resource_id)
        chain: list[UUID] = []
        seen: set[UUID] = set()
        while group_id is not None and group_id not in seen:
            seen.add(group_id)
            chain.append(group_id)
            group_id = self._group_parent.get(group_id)
        return chain

    def calendar_minutes(self, resource_id: UUID, day: date) -> int:
        """Working-time supply from profile and site calendar, before absences."""
        site_id = self._site_of_resource.get(resource_id)
        if site_id is not None:
            override = self._holidays.get((site_id, day))
            if override is not None:
                return override

        profile = self.profile_for(resource_id, day)
        if profile is None:
            return 0
        return profile.minutes_for_weekday(day.weekday())

    def absence_percent(self, resource_id: UUID, day: date) -> float:
        """Total absence share for a resource on a day, capped at 100.

        Provisional and confirmed absences count IDENTICALLY. Excluding provisional ones
        would plan work against days that are likely to disappear, and the plan would break
        at approval rather than now. See :class:`AbsenceStatus`.
        """
        total = 0.0
        for absence in self._absences.get(resource_id, ()):
            if absence.start_date <= day <= absence.end_date:
                total += absence.allocation_percent
        return min(total, 100.0)

    def provisional_percent(self, resource_id: UUID, day: date) -> float:
        """How much of the day's absence is still only requested.

        Reported separately rather than subtracted: this is the share of the capacity gap a
        planner could still renegotiate. Capped the same way, so it is directly comparable
        with :meth:`absence_percent` — a day where both return the same number is a day
        whose entire gap is still open.
        """
        total = 0.0
        for absence in self._absences.get(resource_id, ()):
            if (
                absence.start_date <= day <= absence.end_date
                and absence.status == AbsenceStatus.provisional
            ):
                total += absence.allocation_percent
        return min(total, 100.0)

    def available_minutes(self, resource_id: UUID, day: date) -> int:
        """Calendar minutes reduced by absences — the real supply for the day."""
        calendar = self.calendar_minutes(resource_id, day)
        if calendar == 0:
            return 0
        remaining_share = (100.0 - self.absence_percent(resource_id, day)) / 100.0
        return int(round(calendar * remaining_share))

    def is_working_day(self, resource_id: UUID, day: date) -> bool:
        """Whether the calendar grants any working time on this day."""
        return self.calendar_minutes(resource_id, day) > 0

    def demand_minutes(
        self, resource_id: UUID, day: date, allocation_percent: float
    ) -> int:
        """Demand one assignment places on a day, in normative-day minutes.

        Zero on a non-working day: assignments are date ranges and naturally
        span weekends, so charging them there would flood every plan with
        conflicts it cannot act on.
        """
        if not self.is_working_day(resource_id, day):
            return 0
        return percent_to_minutes(allocation_percent)

    # -------------------------------------------------- infrastructure (007)

    def windows_for(
        self, resource_id: UUID, day: date
    ) -> list[InfrastructureAvailabilityWindow]:
        """Windows *attributed to* this date, if the site calendar allows it.

        A window that runs past midnight also covers part of the following date;
        use :meth:`covered_spans` to ask whether a given minute is bookable.

        An empty list from a resource that has windows means the date is closed.
        A resource with no windows at all is unrestricted, which keeps the
        pre-ADR-005 default. A site holiday suppresses every window attributed to
        that date regardless of ``working_minutes`` — a half day is a statement
        about people, not about which clock hours a machine runs.
        """
        windows = self._windows.get(resource_id)
        if not windows:
            return []

        site_id = self._site_of_resource.get(resource_id)
        if site_id is not None and (site_id, day) in self._holidays:
            return []

        return [w for w in windows if w.weekday == day.weekday()]

    def has_windows(self, resource_id: UUID) -> bool:
        """Whether any availability window is defined for this resource."""
        return bool(self._windows.get(resource_id))

    def covered_spans(self, resource_id: UUID, day: date) -> list[tuple[int, int]]:
        """Bookable minute spans on a date, as merged ``[start, end)`` pairs.

        A window whose ``end_time`` is not after its ``start_time`` runs past
        midnight. It contributes ``[start, 1440)`` to its own weekday and
        ``[0, end)`` to the next one, so a night shift such as 22:00–06:00 is one
        row rather than two that a reader has to mentally join.

        The tail is governed by the calendar of the day the shift *started*, not
        the day it ends on: a holiday cancels a shift, and the small hours after
        midnight belong to the shift that began the evening before.

        An unrestricted resource reports the whole day. Overlapping spans are
        merged, so a misconfigured pair cannot report more time than a day holds.
        """
        if not self.has_windows(resource_id):
            return [(0, MINUTES_PER_DAY)]

        spans: list[tuple[int, int]] = []

        for window in self.windows_for(resource_id, day):
            start = window.start_time.hour * 60 + window.start_time.minute
            end = window.end_time.hour * 60 + window.end_time.minute
            spans.append((start, end) if end > start else (start, MINUTES_PER_DAY))

        for window in self.windows_for(resource_id, day - timedelta(days=1)):
            start = window.start_time.hour * 60 + window.start_time.minute
            end = window.end_time.hour * 60 + window.end_time.minute
            if end <= start and end > 0:
                spans.append((0, end))

        spans.sort()
        merged: list[tuple[int, int]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def window_minutes(self, resource_id: UUID, day: date) -> int:
        """Bookable minutes on a date for an infrastructure resource."""
        return sum(end - start for start, end in self.covered_spans(resource_id, day))

    def covered_minutes_within(
        self, resource_id: UUID, day: date, start_minute: int, end_minute: int
    ) -> int:
        """How much of a minute range on a date falls inside a bookable span."""
        return sum(
            max(0, min(end_minute, span_end) - max(start_minute, span_start))
            for span_start, span_end in self.covered_spans(resource_id, day)
        )

    def day_booking_bounds(
        self, resource_id: UUID, day: date
    ) -> tuple[datetime, datetime] | None:
        """Timestamps for booking an infrastructure resource for a whole day.

        Returns the resource's **operating envelope** on that date: from the start
        of its first bookable span to the end of its last. A two-shift resource
        running 06:00–14:00 and 14:00–22:00 yields 06:00 to 22:00; an
        unrestricted one yields midnight to midnight.

        The envelope deliberately spans the gap between shifts. A track occupied
        for the day is occupied during the shift change too — it is not free for
        someone else to take. Availability windows say when work may be scheduled;
        a day booking says the resource is taken.

        Returns ``None`` when the date is closed — a holiday, or a weekday with no
        window — so the caller can refuse the booking instead of inventing a
        zero-length one.

        This is what lets a planner pick a day rather than typing a time range for
        every booking: the window configuration is stated once per resource and
        the booking maps onto it.
        """
        spans = self.covered_spans(resource_id, day)
        if not spans:
            return None

        start_minute = spans[0][0]
        end_minute = spans[-1][1]
        day_start = datetime.combine(day, time.min)
        zone = planning_zone()
        return (
            local_wall_time_to_utc(day_start + timedelta(minutes=start_minute), zone),
            local_wall_time_to_utc(day_start + timedelta(minutes=end_minute), zone),
        )
