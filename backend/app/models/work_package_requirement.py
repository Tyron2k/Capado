"""SQLModel entity for work package skill requirements.

Work packages have their own direct skill requirements. Templates serve
only as a convenience for copying requirements when creating a work package.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


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


class WorkPackageRequirement(SQLModel, table=True):
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

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    work_package_id: UUID = Field(foreign_key="work_packages.id", index=True)
    skill_id: UUID = Field(foreign_key="skills.id", index=True)
    skill_attribute_id: UUID | None = Field(
        default=None, foreign_key="skill_attributes.id", index=True
    )
    quantity: int = Field(default=1, ge=1)
    requirement_mode: RequirementMode = Field(
        default=RequirementMode.headcount, index=True
    )
    min_allocation_percent: float = Field(default=100.0, gt=0, le=100)
    # Minimum assessed level a qualification must carry to satisfy this requirement.
    # NULL means the level is not part of the requirement at all.
    min_level: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime = Field(default_factory=_utcnow)
