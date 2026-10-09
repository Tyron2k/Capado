"""CSV validation schemas for absence rows."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.absence import AbsenceReason, AbsenceStatus
from app.models.resource import ResourceType


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class AbsenceTransfer(BaseModel):
    """Validate persisted absences rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    resource_id: UUID
    resource_type: ResourceType
    reason: AbsenceReason
    start_date: date
    end_date: date
    allocation_percent: float = Field(default=100.0, gt=0, le=100)
    status: str = Field(default=AbsenceStatus.confirmed, max_length=20)
    note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
