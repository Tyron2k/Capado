"""SQLAlchemy models for personal and infrastructure resources.

Both resource types reference a ResourceGroup via group_id for organizational
grouping and scope-based access control.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class ResourceType(StrEnum):
    """Resource type: personal or infrastructure."""

    personal = "personal"
    infrastructure = "infrastructure"


class PersonalResource(ORMModel, kw_only=True, eq=False):
    """Personal resource (employee).

    Skills are modeled via the unified skill system (personal_resource_skills).
    Management responsibility is derived from User scopes (editors with
    scope_group_ids).
    """

    __tablename__ = "personal_resources"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    group_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("resource_groups.id"), nullable=False, index=True
    )
    site_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("sites.id"), nullable=True, index=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, index=True, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )


class InfrastructureResource(ORMModel, kw_only=True, eq=False):
    """Infrastructure resource (hall, track, crane bay, cabin, etc.).

    Skills are modeled via the unified skill system (infrastructure_resource_skills).
    Occupancy conflicts are detected via time intervals of assignments, bounded
    by availability windows when any are defined (ADR-005).
    """

    __tablename__ = "infrastructure_resources"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    group_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("resource_groups.id"), nullable=False, index=True
    )
    site_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("sites.id"), nullable=True, index=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, index=True, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
