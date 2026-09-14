"""Pydantic schemas for the working-time configuration API.

Covers sites, holidays, week profiles, their bindings to resources, and
infrastructure availability windows — the supply side of the capacity model
(ADR-003, ADR-004, ADR-005).

Durations are exchanged as **minutes**, matching storage. The UI converts to
hours for display; the API does not, because a rounded hour would lose the
half-hour boundaries real shift patterns use.
"""

from datetime import date, time
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

MINUTES_PER_DAY = 1440


class SiteCreate(BaseModel):
    """Request body for creating a site."""

    name: str = Field(min_length=1, max_length=255)
    region_code: str | None = Field(default=None, max_length=16)
    is_default: bool = False


class SiteUpdate(BaseModel):
    """Request body for updating a site (partial)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    region_code: str | None = Field(default=None, max_length=16)
    is_default: bool | None = None
    is_active: bool | None = None


class SiteResponse(BaseModel):
    """Response schema for a site."""

    id: UUID
    name: str
    region_code: str | None
    is_default: bool
    is_active: bool

    model_config = {"from_attributes": True}


class HolidayCreate(BaseModel):
    """Request body for creating a calendar exception.

    ``working_minutes`` defaults to zero, i.e. a non-working day. A value above
    zero expresses a half day, or a designated working Saturday on a day the
    week profile calls free.
    """

    site_id: UUID
    day: date
    name: str = Field(min_length=1, max_length=255)
    working_minutes: int = Field(default=0, ge=0, le=MINUTES_PER_DAY)


class HolidayUpdate(BaseModel):
    """Request body for updating a calendar exception (partial)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    working_minutes: int | None = Field(default=None, ge=0, le=MINUTES_PER_DAY)


class HolidayResponse(BaseModel):
    """Response schema for a calendar exception."""

    id: UUID
    site_id: UUID
    day: date
    name: str
    working_minutes: int

    model_config = {"from_attributes": True}


class WorkWeekProfileCreate(BaseModel):
    """Request body for creating a week profile.

    Defaults describe a standard five-day week so a caller only has to state
    what deviates from it.
    """

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    monday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    tuesday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    wednesday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    thursday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    friday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    saturday_minutes: int = Field(default=0, ge=0, le=MINUTES_PER_DAY)
    sunday_minutes: int = Field(default=0, ge=0, le=MINUTES_PER_DAY)
    is_default: bool = False


class WorkWeekProfileUpdate(BaseModel):
    """Request body for updating a week profile (partial)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    monday_minutes: int | None = Field(default=None, ge=0, le=MINUTES_PER_DAY)
    tuesday_minutes: int | None = Field(default=None, ge=0, le=MINUTES_PER_DAY)
    wednesday_minutes: int | None = Field(default=None, ge=0, le=MINUTES_PER_DAY)
    thursday_minutes: int | None = Field(default=None, ge=0, le=MINUTES_PER_DAY)
    friday_minutes: int | None = Field(default=None, ge=0, le=MINUTES_PER_DAY)
    saturday_minutes: int | None = Field(default=None, ge=0, le=MINUTES_PER_DAY)
    sunday_minutes: int | None = Field(default=None, ge=0, le=MINUTES_PER_DAY)
    is_default: bool | None = None


class WorkWeekProfileResponse(BaseModel):
    """Response schema for a week profile."""

    id: UUID
    name: str
    description: str | None
    monday_minutes: int
    tuesday_minutes: int
    wednesday_minutes: int
    thursday_minutes: int
    friday_minutes: int
    saturday_minutes: int
    sunday_minutes: int
    is_default: bool
    weekly_minutes: int = 0

    model_config = {"from_attributes": True}


class ResourceWorkProfileCreate(BaseModel):
    """Request body for binding a week profile to a resource or a group.

    Exactly one of resource_id and group_id is given. Binding a group is
    the normal case -- a department states its hours once -- and an individual
    binding is the exception that overrides it.
    """

    resource_id: UUID | None = None
    group_id: UUID | None = None
    profile_id: UUID
    valid_from: date
    valid_until: date | None = None

    @model_validator(mode="after")
    def _check_target_and_order(self) -> "ResourceWorkProfileCreate":
        """Require exactly one target and a range that moves forward."""
        if (self.resource_id is None) == (self.group_id is None):
            raise ValueError("give exactly one of resource_id or group_id")
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not be before valid_from")
        return self


class ResourceWorkProfileResponse(BaseModel):
    """Response schema for a profile binding."""

    id: UUID
    resource_id: UUID | None
    group_id: UUID | None
    profile_id: UUID
    valid_from: date
    valid_until: date | None

    model_config = {"from_attributes": True}


class AvailabilityWindowCreate(BaseModel):
    """Request body for an infrastructure availability window.

    A resource with no windows at all is available around the clock, so adding
    the first window is what starts restricting it (ADR-005).

    ``end_time`` **before** ``start_time`` means the window runs past midnight:
    22:00–06:00 is a night shift expressed as one row. Only an empty window is
    rejected.
    """

    resource_id: UUID
    weekday: int = Field(
        ge=0,
        le=6,
        description="Monday = 0 through Sunday = 6; the day the window starts on",
    )
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _check_times_differ(self) -> "AvailabilityWindowCreate":
        """Reject a zero-length window.

        Equal times are ambiguous rather than useful: they could mean "no time"
        or "the whole day", and neither reading is worth guessing at.
        """
        if self.end_time == self.start_time:
            raise ValueError(
                "start_time and end_time must differ; for a window that runs "
                "past midnight set end_time before start_time"
            )
        return self


class AvailabilityWindowResponse(BaseModel):
    """Response schema for an availability window."""

    id: UUID
    resource_id: UUID
    weekday: int
    start_time: time
    end_time: time

    model_config = {"from_attributes": True}
