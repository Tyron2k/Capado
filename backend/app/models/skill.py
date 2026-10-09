"""SQLAlchemy models for the unified skill system.

Skills and their attributes are global entities. Assignments link them
to personal or infrastructure resources via separate join tables.
"""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Skill(ORMModel, kw_only=True, eq=False):
    """A capability or competence (e.g. 'Assembly', 'Crane', 'Painting').

    Skills are scoped to a resource type (personal or infrastructure).
    They are only visible and assignable on the corresponding page.
    """

    __tablename__ = "skills"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(100), nullable=False, unique=True)
    resource_type: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, default="personal"
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )


class SkillAttribute(ORMModel, kw_only=True, eq=False):
    """A specific attribute/variant of a skill (e.g. 'Series Alpha' for skill 'Assembly').

    Each attribute belongs to exactly one skill. A resource is qualified
    for a skill by being assigned one or more of its attributes.
    """

    __tablename__ = "skill_attributes"
    __table_args__ = (
        UniqueConstraint("skill_id", "name", name="uq_skill_attributes_skill_name"),
    )

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    skill_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "skills.id", name="fk_skill_attributes_skill_id", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )


class PersonalResourceSkill(ORMModel, kw_only=True, eq=False):
    """Assignment of a skill attribute to a resource.

    Attributes:
        valid_from: First day the qualification counts, or NULL for no lower bound.
        valid_until: Last day it counts, or NULL for a qualification that does not
            expire — the ordinary case for a trade learned once, which is why both
            bounds are optional rather than required.
        level: Assessed proficiency 1-5, or NULL when nobody assessed it. NULL and 1
            are deliberately different statements: the first says unknown, the second
            says assessed as lowest. A requirement with a minimum is not satisfied by
            an unrecorded level, because it cannot be shown to meet it.
    """

    __tablename__ = "personal_resource_skills"
    __table_args__ = (
        UniqueConstraint(
            "resource_id",
            "skill_attribute_id",
            name="uq_personal_resource_skills_resource_attribute",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    resource_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "personal_resources.id",
            name="fk_personal_resource_skills_resource_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    skill_attribute_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "skill_attributes.id",
            name="fk_personal_resource_skills_skill_attribute_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    valid_from: Mapped[date | None] = mapped_column(
        sa.Date(), nullable=True, default=None
    )
    valid_until: Mapped[date | None] = mapped_column(
        sa.Date(), nullable=True, index=True, default=None
    )
    level: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )


class InfrastructureResourceSkill(ORMModel, kw_only=True, eq=False):
    """Assignment of a skill attribute to a resource.

    Attributes:
        valid_from: First day the qualification counts, or NULL for no lower bound.
        valid_until: Last day it counts, or NULL for a qualification that does not
            expire — the ordinary case for a trade learned once, which is why both
            bounds are optional rather than required.
        level: Assessed proficiency 1-5, or NULL when nobody assessed it. NULL and 1
            are deliberately different statements: the first says unknown, the second
            says assessed as lowest. A requirement with a minimum is not satisfied by
            an unrecorded level, because it cannot be shown to meet it.
    """

    __tablename__ = "infrastructure_resource_skills"
    __table_args__ = (
        UniqueConstraint(
            "resource_id",
            "skill_attribute_id",
            name="uq_infrastructure_resource_skills_resource_attribute",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    resource_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "infrastructure_resources.id",
            name="fk_infrastructure_resource_skills_resource_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    skill_attribute_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "skill_attributes.id",
            name="fk_infrastructure_resource_skills_skill_attribute_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    valid_from: Mapped[date | None] = mapped_column(
        sa.Date(), nullable=True, default=None
    )
    valid_until: Mapped[date | None] = mapped_column(
        sa.Date(), nullable=True, index=True, default=None
    )
    level: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
