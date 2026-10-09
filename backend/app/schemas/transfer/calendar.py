"""CSV validation schemas for calendar rows."""

from datetime import UTC, date, datetime, time
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class HolidayTransfer(BaseModel):
    """Validate persisted holidays rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    site_id: UUID
    day: date
    name: str = Field(max_length=255)
    working_minutes: int = Field(default=0, ge=0, le=1440)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkWeekProfileTransfer(BaseModel):
    """Validate persisted work_week_profiles rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    monday_minutes: int = Field(default=480, ge=0, le=1440)
    tuesday_minutes: int = Field(default=480, ge=0, le=1440)
    wednesday_minutes: int = Field(default=480, ge=0, le=1440)
    thursday_minutes: int = Field(default=480, ge=0, le=1440)
    friday_minutes: int = Field(default=480, ge=0, le=1440)
    saturday_minutes: int = Field(default=0, ge=0, le=1440)
    sunday_minutes: int = Field(default=0, ge=0, le=1440)
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ResourceWorkProfileTransfer(BaseModel):
    """Validate persisted resource_work_profiles rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    resource_id: UUID | None = Field(default=None)
    group_id: UUID | None = Field(default=None)
    profile_id: UUID
    valid_from: date
    valid_until: date | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class InfrastructureAvailabilityWindowTransfer(BaseModel):
    """Validate persisted infrastructure_availability_windows rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    resource_id: UUID
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
