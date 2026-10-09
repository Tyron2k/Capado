"""CSV validation schemas for skill rows."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class SkillTransfer(BaseModel):
    """Validate persisted skills rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(max_length=100)
    resource_type: str = Field(max_length=20, default="personal")
    created_at: datetime = Field(default_factory=_utcnow)


class SkillAttributeTransfer(BaseModel):
    """Validate persisted skill_attributes rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    skill_id: UUID
    name: str = Field(max_length=100)
    created_at: datetime = Field(default_factory=_utcnow)


class PersonalResourceSkillTransfer(BaseModel):
    """Validate persisted personal_resource_skills rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    resource_id: UUID
    skill_attribute_id: UUID
    valid_from: date | None = Field(default=None)
    valid_until: date | None = Field(default=None)
    level: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime = Field(default_factory=_utcnow)


class InfrastructureResourceSkillTransfer(BaseModel):
    """Validate persisted infrastructure_resource_skills rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    resource_id: UUID
    skill_attribute_id: UUID
    valid_from: date | None = Field(default=None)
    valid_until: date | None = Field(default=None)
    level: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime = Field(default_factory=_utcnow)
