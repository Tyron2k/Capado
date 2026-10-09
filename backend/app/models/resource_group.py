"""Typed resource-group persistence, separate from API and CSV validation.

The mapping preserves the table, indexes, foreign keys and eager defaults.
The parent relationship follows existing profile inheritance; sites remain a
separate location axis. All entities share the native SQLAlchemy registry.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ORMModel
from app.models.resource import ResourceType
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    """Generate the same eager UTC timestamp as the previous mapping."""
    return datetime.now(UTC)


class ResourceGroup(ORMModel, kw_only=True, eq=False):
    """A named personal/infrastructure group with an optional parent."""

    __tablename__ = "resource_groups"
    id: Mapped[UUID] = mapped_column(
        primary_key=True, default_factory=uuid4, insert_default=uuid4
    )
    name: Mapped[str] = mapped_column(sa.String(255))
    resource_type: Mapped[ResourceType] = mapped_column(
        sa.Enum(
            ResourceType,
            native_enum=False,
            length=20,
            values_callable=lambda enum: [value.value for value in enum],
        ),
        index=True,
        default=ResourceType.personal,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey(
            "resource_groups.id",
            name="fk_resource_groups_parent_id",
            ondelete="SET NULL",
        ),
        index=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default_factory=_utcnow, insert_default=_utcnow
    )
    parent: Mapped["ResourceGroup | None"] = relationship(
        remote_side="ResourceGroup.id",
        viewonly=True,
        init=False,
        repr=False,
        compare=False,
    )
