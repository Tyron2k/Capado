"""CSV validation schemas for resource rows."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.resource import ResourceType


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class PersonalResourceTransfer(BaseModel):
    """Validate persisted personal_resources rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(max_length=255)
    group_id: UUID
    site_id: UUID | None = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class InfrastructureResourceTransfer(BaseModel):
    """Validate persisted infrastructure_resources rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(max_length=255)
    group_id: UUID
    site_id: UUID | None = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ResourceGroupTransfer(BaseModel):
    """Validate full CSV rows without constructing a persistence object.

    Retain the previous SQLModel constraints and nullable-parent semantics.
    Explicit timestamp offsets remain enforced by the shared CSV parser.
    """

    id: UUID
    name: str = Field(max_length=255)
    resource_type: ResourceType
    parent_id: UUID | None
    created_at: datetime
    updated_at: datetime
