"""CSV validation schemas for work package requirement rows."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.work_package_requirement import RequirementMode


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class WorkPackageRequirementTransfer(BaseModel):
    """Validate persisted work_package_requirements rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    work_package_id: UUID
    skill_id: UUID
    skill_attribute_id: UUID | None = Field(default=None)
    quantity: int = Field(default=1, ge=1)
    requirement_mode: RequirementMode = Field(default=RequirementMode.headcount)
    min_allocation_percent: float = Field(default=100.0, gt=0, le=100)
    min_level: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime = Field(default_factory=_utcnow)
