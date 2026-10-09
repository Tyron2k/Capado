"""CSV validation schemas for user rows."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.user import UserRole


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class UserTransfer(BaseModel):
    """Validate persisted users rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    email: str = Field(max_length=255)
    name: str = Field(max_length=255)
    role: str = Field(default=UserRole.viewer)
    scope_group_ids: list[UUID] | None = Field(default=None)
    scope_project_ids: list[UUID] | None = Field(default=None)
    is_active: bool = Field(default=True)
    resource_id: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
