"""SQLModel entity for resource groups (departments, locations, halls).

A ResourceGroup is a named container that groups personal or infrastructure
resources. It replaces the former free-text `department` and `location`
fields with a proper entity that can be renamed, deleted, and used for
scope-based access control.

Each group is scoped to a resource_type (personal or infrastructure) so that
the People and Infrastructure pages show only their relevant groups.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.models.resource import ResourceType


def _utcnow() -> datetime:
    """UTC timestamp as naive datetime (for TIMESTAMP WITHOUT TIME ZONE)."""
    return datetime.now(UTC).replace(tzinfo=None)


class ResourceGroup(SQLModel, table=True):
    """A named group for organizing resources.

    Groups can be hierarchical (max 2 levels, e.g. Hall → Track).
    Each group is scoped to a resource_type so that personal and
    infrastructure pages show only their relevant groups.
    User editor scopes reference groups via scope_group_ids.
    """

    __tablename__ = "resource_groups"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255)
    resource_type: ResourceType = Field(
        default=ResourceType.personal,
        max_length=20,
        index=True,
        sa_type=sa.String(20),
        description="Scopes the group to personal or infrastructure resources",
    )
    parent_id: UUID | None = Field(
        default=None, foreign_key="resource_groups.id", index=True
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
