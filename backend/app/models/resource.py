"""SQLModel models for personal and infrastructure resources.

Both resource types reference a ResourceGroup via group_id for organizational
grouping and scope-based access control.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class ResourceType(StrEnum):
    """Resource type: personal or infrastructure."""

    personal = "personal"
    infrastructure = "infrastructure"


class PersonalResource(SQLModel, table=True):
    """Personal resource (employee).

    Skills are modeled via the unified skill system (personal_resource_skills).
    Management responsibility is derived from User scopes (editors with
    scope_group_ids).
    """

    __tablename__ = "personal_resources"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255)
    group_id: UUID = Field(foreign_key="resource_groups.id", index=True)
    site_id: UUID | None = Field(default=None, foreign_key="sites.id", index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class InfrastructureResource(SQLModel, table=True):
    """Infrastructure resource (hall, track, crane bay, cabin, etc.).

    Skills are modeled via the unified skill system (infrastructure_resource_skills).
    Occupancy conflicts are detected via time intervals of assignments, bounded
    by availability windows when any are defined (ADR-005).
    """

    __tablename__ = "infrastructure_resources"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255)
    group_id: UUID = Field(foreign_key="resource_groups.id", index=True)
    site_id: UUID | None = Field(default=None, foreign_key="sites.id", index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
