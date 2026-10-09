"""SQLAlchemy models for conflicts and the junction table Conflict ↔ Assignment."""

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ORMModel
from app.models.resource import ResourceType
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ConflictCause(StrEnum):
    """Why a conflict was raised.

    The cause has to be stored rather than inferred, because the resolutions
    differ: shifting a booking into an operating window is a different action
    from moving it to another resource or lowering an allocation. A consumer
    that only knows "there is a conflict" cannot propose the right fix
    (ADR-005).
    """

    over_allocation = "over_allocation"
    """Personal: demanded minutes exceed available minutes on a day."""

    booking_overlap = "booking_overlap"
    """Infrastructure: two or more bookings occupy the same interval."""

    outside_availability = "outside_availability"
    """Infrastructure: a booking falls outside every availability window."""


class ConflictAssignment(ORMModel, kw_only=True, eq=False):
    """Junction table: which assignments are involved in a conflict."""

    __tablename__ = "conflict_assignments"

    conflict_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("conflicts.id"), nullable=False, primary_key=True
    )
    assignment_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("assignments.id"),
        nullable=False,
        primary_key=True,
        index=True,
    )


class Conflict(ORMModel, kw_only=True, eq=False):
    """Detected capacity conflict for a resource in a time period.

    Personal conflicts occur when the minutes demanded by assignments exceed the
    minutes the resource has available on a day — week profile and site calendar
    minus absences. Infrastructure conflicts are overlapping bookings, or a
    booking outside the resource's availability windows.

    ``total_assigned_percent`` and ``available_percent`` are derived from minutes
    and kept for API stability. ``available_percent`` is therefore no longer
    always 100: a part-time resource reports its own day.
    """

    __tablename__ = "conflicts"

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
    )
    cause: Mapped[ConflictCause] = mapped_column(
        sa.Enum(
            ConflictCause,
            name="conflictcause",
            native_enum=True,
            length=20,
            create_constraint=False,
        ),
        nullable=False,
        index=True,
        default=ConflictCause.over_allocation,
    )
    start_date: Mapped[date] = mapped_column(sa.Date(), nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(sa.Date(), nullable=False, index=True)
    total_assigned_percent: Mapped[float] = mapped_column(sa.Float(), nullable=False)
    available_percent: Mapped[float] = mapped_column(sa.Float(), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )

    assignments: Mapped[list["ConflictAssignment"]] = relationship(
        init=False, repr=False, compare=False
    )
