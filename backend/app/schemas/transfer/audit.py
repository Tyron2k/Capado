"""CSV validation schemas for audit rows."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.audit import AuditAction


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class AuditLogTransfer(BaseModel):
    """Validate persisted audit_log rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    entity_type: str = Field(max_length=64)
    entity_id: UUID
    action: AuditAction
    actor_id: UUID | None = Field(default=None)
    reason: str | None = Field(default=None, max_length=500)
    changes: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=_utcnow)
