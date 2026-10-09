"""CSV validation schemas for baseline rows."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class BaselineTransfer(BaseModel):
    """Validate persisted baselines rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(max_length=255)
    note: str | None = Field(default=None, max_length=1000)
    created_by: UUID | None = Field(default=None)
    is_current: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)


class BaselineEntryTransfer(BaseModel):
    """Validate persisted baseline_entries rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    baseline_id: UUID
    entity_type: str = Field(max_length=64)
    entity_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)
