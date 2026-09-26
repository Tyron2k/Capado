"""SQLModel models for the unified skill system.

Skills and their attributes are global entities. Assignments link them
to personal or infrastructure resources via separate join tables.
"""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel, UniqueConstraint


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Skill(SQLModel, table=True):
    """A capability or competence (e.g. 'Assembly', 'Crane', 'Painting').

    Skills are scoped to a resource type (personal or infrastructure).
    They are only visible and assignable on the corresponding page.
    """

    __tablename__ = "skills"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=100, unique=True)
    resource_type: str = Field(max_length=20, default="personal")
    created_at: datetime = Field(default_factory=_utcnow)


class SkillAttribute(SQLModel, table=True):
    """A specific attribute/variant of a skill (e.g. 'Series Alpha' for skill 'Assembly').

    Each attribute belongs to exactly one skill. A resource is qualified
    for a skill by being assigned one or more of its attributes.
    """

    __tablename__ = "skill_attributes"
    __table_args__ = (
        UniqueConstraint("skill_id", "name", name="uq_skill_attributes_skill_name"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    skill_id: UUID = Field(foreign_key="skills.id", index=True)
    name: str = Field(max_length=100)
    created_at: datetime = Field(default_factory=_utcnow)


class PersonalResourceSkill(SQLModel, table=True):
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

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    resource_id: UUID = Field(foreign_key="personal_resources.id", index=True)
    skill_attribute_id: UUID = Field(foreign_key="skill_attributes.id", index=True)
    valid_from: date | None = Field(default=None)
    valid_until: date | None = Field(default=None, index=True)
    level: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime = Field(default_factory=_utcnow)


class InfrastructureResourceSkill(SQLModel, table=True):
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

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    resource_id: UUID = Field(foreign_key="infrastructure_resources.id", index=True)
    skill_attribute_id: UUID = Field(foreign_key="skill_attributes.id", index=True)
    valid_from: date | None = Field(default=None)
    valid_until: date | None = Field(default=None, index=True)
    level: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime = Field(default_factory=_utcnow)
