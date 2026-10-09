"""SQLAlchemy entity for work package skill requirements.

Work packages have their own direct skill requirements. Templates serve
only as a convenience for copying requirements when creating a work package.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RequirementMode(StrEnum):
    """How ``quantity`` is to be satisfied.

    The distinction exists because effort is not freely divisible across people.
    Two people working eight hours do not deliver sixteen hours of a job that
    needs two of them present at once: a blasting cabin staffed by two, a lift
    that takes two operators, a weld one person cannot hold. Treating the two
    readings as one is how a plan looks covered while the work cannot happen.
    """

    headcount = "headcount"
    """``quantity`` distinct resources, each allocated at least
    ``min_allocation_percent``. Four people at 25% do NOT satisfy a requirement
    for two. This is the default, because it is the safe reading: it never
    reports coverage that cannot be staffed."""

    effort_fte = "effort_fte"
    """``quantity`` full-time equivalents, freely divisible. Four people at 50%
    satisfy a requirement for two. Only correct where the work genuinely
    parallelises across bodies."""


class WorkPackageRequirement(ORMModel, kw_only=True, eq=False):
    """A single skill requirement directly on a work package.

    If skill_attribute_id is set, the requirement is for that specific attribute.
    If null, any attribute of the skill satisfies the requirement.

    ``quantity`` is read according to ``requirement_mode``; see
    :class:`RequirementMode`. Note what is deliberately absent: there is no
    effort field in hours, and duration is never derived from effort divided by
    headcount. A work package's dates say how long the work takes; the
    requirement says who has to be there while it does.
    """

    __tablename__ = "work_package_requirements"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    work_package_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "work_packages.id",
            name="work_package_requirements_work_package_id_fkey",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("skills.id"), nullable=False, index=True
    )
    skill_attribute_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("skill_attributes.id"),
        nullable=True,
        index=True,
        default=None,
    )
    quantity: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=1)
    requirement_mode: Mapped[RequirementMode] = mapped_column(
        sa.Enum(
            RequirementMode,
            name="requirementmode",
            native_enum=True,
            length=10,
            create_constraint=False,
        ),
        nullable=False,
        index=True,
        default=RequirementMode.headcount,
    )
    min_allocation_percent: Mapped[float] = mapped_column(
        sa.Float(), nullable=False, default=100.0
    )
    # Minimum assessed level a qualification must carry to satisfy this requirement.
    # NULL means the level is not part of the requirement at all.
    min_level: Mapped[int | None] = mapped_column(
        sa.Integer(), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
