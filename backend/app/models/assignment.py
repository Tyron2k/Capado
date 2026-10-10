"""SQLAlchemy model for assignments (resource → work package).

Two shapes share one table:

- **Personal assignments** use ``start_date``, ``end_date`` and
  ``allocation_percent``. Conflict detection sums percentages; a conflict
  occurs when the total exceeds 100%.
- **Infrastructure assignments** use ``start_at`` and ``end_at`` (timestamps).
  They are implicitly 100% (exclusive). Conflict detection treats two
  overlapping timestamps on the same resource as a conflict.
"""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ORMModel
from app.models.resource import ResourceType
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


if TYPE_CHECKING:
    from app.models.project import WorkPackage


class Assignment(ORMModel, kw_only=True, eq=False):
    """Assignment of a resource to a work package.

    For ``resource_type == personal``, ``start_date``/``end_date`` and
    ``allocation_percent`` must be set; ``start_at``/``end_at`` remain ``None``.
    For ``resource_type == infrastructure`` it is the opposite: ``start_at``
    and ``end_at`` are set, the resource is implicitly 100% allocated.
    """

    __tablename__ = "assignments"
    __table_args__ = (
        sa.Index(
            "uq_assignments_personal_booking",
            "resource_type",
            "resource_id",
            "work_package_id",
            "start_date",
            "end_date",
            "allocation_percent",
            unique=True,
            postgresql_where=sa.text("resource_type = 'personal'"),
            sqlite_where=sa.text("resource_type = 'personal'"),
        ),
        sa.Index(
            "uq_assignments_infrastructure_booking",
            "resource_type",
            "resource_id",
            "work_package_id",
            "start_at",
            "end_at",
            unique=True,
            postgresql_where=sa.text("resource_type = 'infrastructure'"),
            sqlite_where=sa.text("resource_type = 'infrastructure'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    resource_id: Mapped[UUID] = mapped_column(sa.Uuid(), nullable=False, index=True)
    resource_type: Mapped[ResourceType] = mapped_column(
        sa.Enum(
            ResourceType,
            name="resourcetype",
            native_enum=True,
            length=14,
            create_constraint=False,
        ),
        nullable=False,
        index=True,
    )
    work_package_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("work_packages.id"), nullable=False, index=True
    )

    # Personal-assignment fields (nullable; required when resource_type=personal)
    start_date: Mapped[date | None] = mapped_column(
        sa.Date(), nullable=True, index=True, default=None
    )
    end_date: Mapped[date | None] = mapped_column(
        sa.Date(), nullable=True, index=True, default=None
    )
    allocation_percent: Mapped[float | None] = mapped_column(
        sa.Float(), nullable=True, default=None
    )

    # Infrastructure-assignment fields (nullable; required when resource_type=infrastructure)
    start_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, default=None
    )
    end_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, default=None
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )

    work_package: Mapped[Optional["WorkPackage"]] = relationship(
        back_populates="assignments", init=False, repr=False, compare=False
    )
