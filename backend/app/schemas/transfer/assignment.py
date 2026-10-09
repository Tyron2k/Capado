"""CSV validation schemas for assignment rows."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.resource import ResourceType


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class AssignmentTransfer(BaseModel):
    """Validate persisted assignments rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    resource_id: UUID
    resource_type: ResourceType
    work_package_id: UUID
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)
    allocation_percent: float | None = Field(default=None, gt=0, le=100)
    start_at: datetime | None = Field(default=None)
    end_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
