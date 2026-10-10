"""CalendarService: CRUD for the working-time configuration.

Sites, holidays, week profiles, their bindings, and infrastructure availability
windows. Three invariants live here rather than in the router, because they must
hold no matter who writes:

- At most one site and at most one week profile carry ``is_default``. Two
  defaults would make capacity depend on row order.
- A profile still bound to a resource cannot be deleted. Removing it would
  silently move those resources onto the default profile and change their
  capacity without anyone touching them.
- The default profile cannot be deleted at all: resources without a binding fall
  back to it, and without one a fresh deployment reports zero capacity
  everywhere (ADR-004).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.calendar import (
    Holiday,
    InfrastructureAvailabilityWindow,
    ResourceWorkProfile,
    WorkWeekProfile,
)
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.services.conflict_refresh import refresh_resources


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


async def lock_calendar_default(
    session: AsyncSession, table: Literal["sites", "work_week_profiles"]
) -> None:
    """Serialize each default's read/change/commit, including CSV imports."""
    if (
        isinstance(session, AsyncSession)
        and session.get_bind().dialect.name == "postgresql"
    ):
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
            {"namespace": 0x43_41_50_43, "key": 1 if table == "sites" else 2},
        )


def weekly_minutes(profile: WorkWeekProfile) -> int:
    """Total available minutes across a week for a profile."""
    return sum(profile.minutes_for_weekday(weekday) for weekday in range(7))


class CalendarService:
    """Read and write the working-time configuration."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    # ---------------------------------------------------------------- sites

    async def list_sites(self, include_inactive: bool = False) -> list[Site]:
        """All sites, active ones only unless asked otherwise."""
        statement = select(Site)
        if not include_inactive:
            statement = statement.where(Site.is_active == True)  # noqa: E712
        result = await self.session.execute(statement.order_by(Site.name))
        return list(result.scalars().all())

    async def get_site(self, site_id: UUID, *, for_update: bool = False) -> Site:
        """One site, or 404."""
        site = await self.session.get(
            Site, site_id, with_for_update=for_update, populate_existing=for_update
        )
        if site is None:
            raise NotFoundError("Site", site_id)
        return site

    async def create_site(
        self, name: str, region_code: str | None, is_default: bool
    ) -> Site:
        """Create a site, clearing any previous default when this one claims it."""
        if is_default:
            await lock_calendar_default(self.session, "sites")
            await self._clear_default_site()
        site = Site(name=name, region_code=region_code, is_default=is_default)
        self.session.add(site)
        await self.session.commit()
        await refresh_resources(self.session)
        await self.session.refresh(site)
        return site

    async def update_site(self, site_id: UUID, **changes: object) -> Site:
        """Apply partial changes to a site."""
        if "is_default" in changes or "is_active" in changes:
            await lock_calendar_default(self.session, "sites")
        site = await self.get_site(site_id, for_update=True)
        if site.is_default and changes.get("is_default") is False:
            raise BusinessRuleError(
                "Replace the default site by making another site the default first."
            )
        default = (
            changes.get("is_default")
            if changes.get("is_default") is not None
            else site.is_default
        )
        active = (
            changes.get("is_active")
            if changes.get("is_active") is not None
            else site.is_active
        )
        if default and not active:
            raise BusinessRuleError(
                "The default site must remain active; select another default first."
            )
        if changes.get("is_default") is True and not site.is_default:
            await self._clear_default_site()
        for field, value in changes.items():
            if value is not None:
                setattr(site, field, value)
        site.updated_at = _utcnow()
        self.session.add(site)
        await self.session.commit()
        await refresh_resources(self.session)
        await self.session.refresh(site)
        return site

    async def deactivate_site(self, site_id: UUID) -> None:
        """Soft-delete a site, consistent with resources and users."""
        await lock_calendar_default(self.session, "sites")
        site = await self.get_site(site_id, for_update=True)
        if site.is_default:
            raise BusinessRuleError(
                "the default site cannot be deactivated; make another site "
                "the default first"
            )
        site.is_active = False
        site.updated_at = _utcnow()
        self.session.add(site)
        await self.session.commit()
        await refresh_resources(self.session)

    async def _clear_default_site(self) -> None:
        """Unset the current default site.

        Loaded and mutated through the ORM rather than issued as a Core UPDATE:
        a Core statement bypasses the flush and would leave the change absent
        from the audit trail (ADR-006). At most one row carries the flag, so the
        extra round-trip costs nothing.
        """
        result = await self.session.execute(
            select(Site).where(Site.is_default == True)  # noqa: E712
        )
        for site in result.scalars().all():
            site.is_default = False
            site.updated_at = _utcnow()
            self.session.add(site)
        await self.session.flush()

    # ------------------------------------------------------------- holidays

    async def list_holidays(
        self,
        site_id: UUID | None = None,
        from_day: date | None = None,
        to_day: date | None = None,
    ) -> list[Holiday]:
        """Calendar exceptions, optionally narrowed to a site and a range."""
        statement = select(Holiday)
        if site_id is not None:
            statement = statement.where(Holiday.site_id == site_id)
        if from_day is not None:
            statement = statement.where(Holiday.day >= from_day)
        if to_day is not None:
            statement = statement.where(Holiday.day <= to_day)
        result = await self.session.execute(statement.order_by(Holiday.day))
        return list(result.scalars().all())

    async def create_holiday(
        self, site_id: UUID, day: date, name: str, working_minutes: int
    ) -> Holiday:
        """Create a calendar exception for one site and date."""
        await self.get_site(site_id)
        existing = await self.session.execute(
            select(Holiday).where(Holiday.site_id == site_id, Holiday.day == day)
        )
        if existing.scalars().first() is not None:
            raise BusinessRuleError(
                f"a calendar exception for {day.isoformat()} already exists at "
                "this site"
            )
        holiday = Holiday(
            site_id=site_id, day=day, name=name, working_minutes=working_minutes
        )
        self.session.add(holiday)
        await self.session.commit()
        await refresh_resources(self.session)
        await self.session.refresh(holiday)
        return holiday

    async def update_holiday(self, holiday_id: UUID, **changes: object) -> Holiday:
        """Apply partial changes to a calendar exception."""
        holiday = await self.session.get(Holiday, holiday_id)
        if holiday is None:
            raise NotFoundError("Holiday", holiday_id)
        for field, value in changes.items():
            if value is not None:
                setattr(holiday, field, value)
        holiday.updated_at = _utcnow()
        self.session.add(holiday)
        await self.session.commit()
        await refresh_resources(self.session)
        await self.session.refresh(holiday)
        return holiday

    async def delete_holiday(self, holiday_id: UUID) -> None:
        """Remove a calendar exception, restoring the week profile for that day."""
        holiday = await self.session.get(Holiday, holiday_id)
        if holiday is None:
            raise NotFoundError("Holiday", holiday_id)
        await self.session.delete(holiday)
        await self.session.commit()
        await refresh_resources(self.session)

    # ------------------------------------------------------------- profiles

    async def list_profiles(self) -> list[WorkWeekProfile]:
        """All week profiles, default first, then by name."""
        result = await self.session.execute(
            select(WorkWeekProfile).order_by(
                WorkWeekProfile.is_default.desc(), WorkWeekProfile.name
            )
        )
        return list(result.scalars().all())

    async def get_profile(
        self, profile_id: UUID, *, for_update: bool = False, key_share: bool = False
    ) -> WorkWeekProfile:
        """One week profile, or 404."""
        profile = await self.session.get(
            WorkWeekProfile,
            profile_id,
            with_for_update={"read": True, "key_share": True}
            if key_share
            else for_update,
            populate_existing=for_update or key_share,
        )
        if profile is None:
            raise NotFoundError("WorkWeekProfile", profile_id)
        return profile

    async def create_profile(
        self,
        name: str,
        description: str | None = None,
        monday_minutes: int = 480,
        tuesday_minutes: int = 480,
        wednesday_minutes: int = 480,
        thursday_minutes: int = 480,
        friday_minutes: int = 480,
        saturday_minutes: int = 0,
        sunday_minutes: int = 0,
        is_default: bool = False,
    ) -> WorkWeekProfile:
        """Create a week profile, clearing any previous default when claimed."""
        if is_default:
            await lock_calendar_default(self.session, "work_week_profiles")
            await self._clear_default_profile()
        profile = WorkWeekProfile(
            name=name,
            description=description,
            monday_minutes=monday_minutes,
            tuesday_minutes=tuesday_minutes,
            wednesday_minutes=wednesday_minutes,
            thursday_minutes=thursday_minutes,
            friday_minutes=friday_minutes,
            saturday_minutes=saturday_minutes,
            sunday_minutes=sunday_minutes,
            is_default=is_default,
        )
        self.session.add(profile)
        await self.session.commit()
        await refresh_resources(self.session)
        await self.session.refresh(profile)
        return profile

    async def update_profile(
        self, profile_id: UUID, **changes: object
    ) -> WorkWeekProfile:
        """Apply partial changes to a week profile."""
        if "is_default" in changes:
            await lock_calendar_default(self.session, "work_week_profiles")
        profile = await self.get_profile(profile_id, for_update=True)
        if profile.is_default and changes.get("is_default") is False:
            raise BusinessRuleError(
                "Replace the default profile by making another profile the default first."
            )
        if changes.get("is_default") is True and not profile.is_default:
            await self._clear_default_profile()
        for field, value in changes.items():
            if value is not None:
                setattr(profile, field, value)
        profile.updated_at = _utcnow()
        self.session.add(profile)
        await self.session.commit()
        await refresh_resources(self.session)
        await self.session.refresh(profile)
        return profile

    async def delete_profile(self, profile_id: UUID) -> None:
        """Delete a week profile that nothing depends on."""
        await lock_calendar_default(self.session, "work_week_profiles")
        profile = await self.get_profile(profile_id, for_update=True)
        if profile.is_default:
            raise BusinessRuleError(
                "the default profile cannot be deleted; resources without a "
                "binding fall back to it"
            )
        bindings = await self.session.execute(
            select(ResourceWorkProfile.id).where(
                ResourceWorkProfile.profile_id == profile_id
            )
        )
        if bindings.scalars().first() is not None:
            raise BusinessRuleError(
                "this profile is still assigned to resources; reassign them "
                "before deleting it"
            )
        await self.session.delete(profile)
        await self.session.commit()
        await refresh_resources(self.session)

    async def _clear_default_profile(self) -> None:
        """Unset the current default week profile.

        ORM-mutated for the same reason as :meth:`_clear_default_site`: a Core
        UPDATE would not be audited.
        """
        result = await self.session.execute(
            select(WorkWeekProfile).where(WorkWeekProfile.is_default == True)  # noqa: E712
        )
        for profile in result.scalars().all():
            profile.is_default = False
            profile.updated_at = _utcnow()
            self.session.add(profile)
        await self.session.flush()

    # ------------------------------------------------------------- bindings

    async def list_bindings(
        self, resource_id: UUID | None = None, group_id: UUID | None = None
    ) -> list[ResourceWorkProfile]:
        """Profile bindings, optionally for one resource or one group."""
        statement = select(ResourceWorkProfile)
        if resource_id is not None:
            statement = statement.where(ResourceWorkProfile.resource_id == resource_id)
        if group_id is not None:
            statement = statement.where(ResourceWorkProfile.group_id == group_id)
        result = await self.session.execute(
            statement.order_by(ResourceWorkProfile.valid_from)
        )
        return list(result.scalars().all())

    async def create_binding(
        self,
        profile_id: UUID,
        valid_from: date,
        valid_until: date | None,
        resource_id: UUID | None = None,
        group_id: UUID | None = None,
    ) -> ResourceWorkProfile:
        """Bind a profile to a resource or a group, rejecting overlaps.

        Overlaps are checked within the same target only. A group binding and an
        individual binding for the same period are legitimate and common: the
        group states the department default and the individual row overrides it.
        """
        if (resource_id is None) == (group_id is None):
            raise BusinessRuleError("give exactly one of resource_id or group_id")
        if valid_until is not None and valid_until < valid_from:
            raise BusinessRuleError("The binding end must not precede its start.")
        # Keep the referenced profile alive through the binding's commit, without
        # serializing independent bindings that merely share a profile.
        await self.get_profile(profile_id, key_share=True)
        if group_id is not None:
            group = await self.session.scalar(
                select(ResourceGroup)
                .where(ResourceGroup.id == group_id)
                .with_for_update(read=True, key_share=True)
            )
            if group is None:
                raise NotFoundError("ResourceGroup", group_id)
        for existing in await self.list_bindings(resource_id, group_id):
            existing_end = existing.valid_until or date.max
            new_end = valid_until or date.max
            if existing.valid_from <= new_end and valid_from <= existing_end:
                raise BusinessRuleError(
                    "this resource already has a profile for part of that "
                    "period; end the existing binding first"
                )
        binding = ResourceWorkProfile(
            resource_id=resource_id,
            group_id=group_id,
            profile_id=profile_id,
            valid_from=valid_from,
            valid_until=valid_until,
        )
        self.session.add(binding)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            name = getattr(
                getattr(exc.orig, "__cause__", None), "constraint_name", None
            )
            if name in {
                "ex_work_profiles_resource_period",
                "ex_work_profiles_group_period",
            }:
                raise BusinessRuleError(
                    "This target already has a profile for part of that period; end the existing binding first."
                ) from exc
            raise
        await refresh_resources(
            self.session, [resource_id] if resource_id is not None else None
        )
        await self.session.refresh(binding)
        return binding

    async def delete_binding(self, binding_id: UUID) -> None:
        """Remove a binding, returning the resource to the default profile."""
        binding = await self.session.get(ResourceWorkProfile, binding_id)
        if binding is None:
            raise NotFoundError("ResourceWorkProfile", binding_id)
        await self.session.delete(binding)
        await self.session.commit()
        await refresh_resources(
            self.session,
            [binding.resource_id] if binding.resource_id is not None else None,
        )

    # -------------------------------------------------------------- windows

    async def list_windows(
        self, resource_id: UUID
    ) -> list[InfrastructureAvailabilityWindow]:
        """Availability windows for one infrastructure resource."""
        result = await self.session.execute(
            select(InfrastructureAvailabilityWindow)
            .where(InfrastructureAvailabilityWindow.resource_id == resource_id)
            .order_by(
                InfrastructureAvailabilityWindow.weekday,
                InfrastructureAvailabilityWindow.start_time,
            )
        )
        return list(result.scalars().all())

    async def create_window(
        self, resource_id: UUID, weekday: int, start_time: time, end_time: time
    ) -> InfrastructureAvailabilityWindow:
        """Add an availability window to an infrastructure resource."""
        window = InfrastructureAvailabilityWindow(
            resource_id=resource_id,
            weekday=weekday,
            start_time=start_time,
            end_time=end_time,
        )
        self.session.add(window)
        await self.session.commit()
        await refresh_resources(
            self.session, [resource_id] if resource_id is not None else None
        )
        await self.session.refresh(window)
        return window

    async def delete_window(self, window_id: UUID) -> None:
        """Remove one window.

        Deleting the last window of a resource makes it unrestricted again,
        which is the documented meaning of having none (ADR-005).
        """
        window = await self.session.get(InfrastructureAvailabilityWindow, window_id)
        if window is None:
            raise NotFoundError("InfrastructureAvailabilityWindow", window_id)
        await self.session.delete(window)
        await self.session.commit()
        await refresh_resources(
            self.session,
            [window.resource_id] if window.resource_id is not None else None,
        )

    async def delete_windows_for_resource(self, resource_id: UUID) -> int:
        """Remove every window of a resource, making it unrestricted."""
        result = await self.session.execute(
            delete(InfrastructureAvailabilityWindow).where(
                InfrastructureAvailabilityWindow.resource_id == resource_id
            )
        )
        await self.session.commit()
        await refresh_resources(
            self.session, [resource_id] if resource_id is not None else None
        )
        return int(cast(CursorResult[Any], result).rowcount or 0)
