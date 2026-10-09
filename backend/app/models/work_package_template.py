"""SQLAlchemy entities for work package templates and their skill requirements.

A template defines what skills (and optionally specific attributes) are
needed to execute a type of work package, and how many resources with
each skill are required.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.models.work_package_requirement import RequirementMode
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WorkPackageTemplate(ORMModel, kw_only=True, eq=False):
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

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(
        sa.String(1000), nullable=True, default=None
    )
    lead_time_working_days: Mapped[int | None] = mapped_column(
        sa.Integer(), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )


class WorkPackageTemplateRequirement(ORMModel, kw_only=True, eq=False):
    """A single skill requirement within a template.

    If skill_attribute_id is set, the requirement is for that specific attribute.
    If null, any attribute of the skill satisfies the requirement.
    """

    __tablename__ = "work_package_template_requirements"
    __table_args__ = (sa.Index("ix_wpt_requirements_template_id", "template_id"),)

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    template_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "work_package_templates.id",
            name="fk_wpt_requirements_template_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=False,
    )
    skill_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("skills.id"), nullable=False
    )
    skill_attribute_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("skill_attributes.id"), nullable=True, default=None
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
