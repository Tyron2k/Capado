"""SQLModel models for conflicts and the junction table Conflict ↔ Assignment."""

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel

from app.models.resource import ResourceType


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


class ConflictAssignment(SQLModel, table=True):
    """Junction table: which assignments are involved in a conflict."""

    __tablename__ = "conflict_assignments"

    conflict_id: UUID = Field(foreign_key="conflicts.id", primary_key=True)
    assignment_id: UUID = Field(
        foreign_key="assignments.id", primary_key=True, index=True
    )


class Conflict(SQLModel, table=True):
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

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    resource_id: UUID = Field(index=True)
    resource_type: ResourceType
    cause: ConflictCause = Field(default=ConflictCause.over_allocation, index=True)
    start_date: date = Field(index=True)
    end_date: date = Field(index=True)
    total_assigned_percent: float
    available_percent: float
    detected_at: datetime = Field(default_factory=_utcnow)

    assignments: list["ConflictAssignment"] = Relationship()
