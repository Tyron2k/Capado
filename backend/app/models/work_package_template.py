"""SQLModel entities for work package templates and their skill requirements.

A template defines what skills (and optionally specific attributes) are
needed to execute a type of work package, and how many resources with
each skill are required.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.models.work_package_requirement import RequirementMode


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class WorkPackageTemplate(SQLModel, table=True):
    """Reusable template defining the skill requirements for a work package type.

    Attributes:
        lead_time_working_days: How long the process takes in WORKING days, which
            is the unit the templates were already written in — "34 Arbeitstage
            Durchlaufzeit". Optional, because a template may describe requirements
            without claiming a duration.

            Used to warn when a work package's entered end date cannot hold the
            process. The entered date is never overwritten: it is a commitment, and
            a computation that rewrote it would hide the very fact worth reporting.
    """

    __tablename__ = "work_package_templates"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    lead_time_working_days: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkPackageTemplateRequirement(SQLModel, table=True):
    """A single skill requirement within a template.

    If skill_attribute_id is set, the requirement is for that specific attribute.
    If null, any attribute of the skill satisfies the requirement.
    """

    __tablename__ = "work_package_template_requirements"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    template_id: UUID = Field(foreign_key="work_package_templates.id", index=True)
    skill_id: UUID = Field(foreign_key="skills.id")
    skill_attribute_id: UUID | None = Field(
        default=None, foreign_key="skill_attributes.id"
    )
    quantity: int = Field(default=1, ge=1)
    requirement_mode: RequirementMode = Field(default=RequirementMode.headcount)
    min_allocation_percent: float = Field(default=100.0, gt=0, le=100)
    # Minimum assessed level a qualification must carry to satisfy this requirement.
    # NULL means the level is not part of the requirement at all.
    min_level: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime = Field(default_factory=_utcnow)
