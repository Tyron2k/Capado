"""CSV validation schemas for customer rows."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class CustomerTransfer(BaseModel):
    """Validate persisted customers rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(max_length=255)
    reference: str = Field(default="", max_length=128)
    note: str = Field(default="", max_length=1000)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
