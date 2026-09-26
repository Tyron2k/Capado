"""SQLModel model for assignments (resource → work package).

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

from sqlmodel import Field, Relationship, SQLModel

from app.models.resource import ResourceType


def _utcnow() -> datetime:
    return datetime.now(UTC)


if TYPE_CHECKING:
    from app.models.project import WorkPackage


class Assignment(SQLModel, table=True):
    """Assignment of a resource to a work package.

    For ``resource_type == personal``, ``start_date``/``end_date`` and
    ``allocation_percent`` must be set; ``start_at``/``end_at`` remain ``None``.
    For ``resource_type == infrastructure`` it is the opposite: ``start_at``
    and ``end_at`` are set, the resource is implicitly 100% allocated.
    """

    __tablename__ = "assignments"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    resource_id: UUID = Field(index=True)
    resource_type: ResourceType = Field(index=True)
    work_package_id: UUID = Field(foreign_key="work_packages.id", index=True)

    # Personal-assignment fields (nullable; required when resource_type=personal)
    start_date: date | None = Field(default=None, index=True)
    end_date: date | None = Field(default=None, index=True)
    allocation_percent: float | None = Field(default=None, gt=0, le=100)

    # Infrastructure-assignment fields (nullable; required when resource_type=infrastructure)
    start_at: datetime | None = Field(default=None)
    end_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    work_package: Optional["WorkPackage"] = Relationship(back_populates="assignments")
