"""Pydantic schemas for the unified skill system API (request/response)."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

# --- Skill Schemas ---


class SkillCreate(BaseModel):
    """Request schema for creating a skill."""

    name: str = Field(
        ..., min_length=1, max_length=100, description="Name of the skill"
    )
    resource_type: str = Field(
        default="personal", description="Resource type: personal or infrastructure"
    )


class SkillResponse(BaseModel):
    """Response schema for a skill."""

    id: UUID
    name: str
    resource_type: str

    model_config = {"from_attributes": True}


class SkillWithAttributesResponse(BaseModel):
    """Response schema for a skill including its attributes."""

    id: UUID
    name: str
    resource_type: str
    attributes: list["SkillAttributeResponse"]

    model_config = {"from_attributes": True}


# --- SkillAttribute Schemas ---


class SkillAttributeCreate(BaseModel):
    """Request schema for creating a skill attribute."""

    name: str = Field(
        ..., min_length=1, max_length=100, description="Name of the attribute"
    )


class SkillAttributeResponse(BaseModel):
    """Response schema for a skill attribute."""

    id: UUID
    skill_id: UUID
    name: str

    model_config = {"from_attributes": True}


# --- Resource Skill Assignment Schemas ---


class ResourceSkillAssignmentCreate(BaseModel):
    """Request schema for assigning a skill attribute to a resource."""

    skill_attribute_id: UUID = Field(..., description="ID of the skill attribute")
    valid_from: date | None = None
    # NULL means it does not expire — the ordinary case for a trade learned once.
    valid_until: date | None = None
    # NULL means nobody assessed the level, which is not the same as level 1.
    level: int | None = Field(default=None, ge=1, le=5)


class ResourceSkillAssignmentResponse(BaseModel):
    """Response schema for a resource skill assignment."""

    id: UUID
    skill_attribute_id: UUID
    skill_id: UUID
    skill_name: str
    attribute_name: str
    valid_from: date | None = None
    valid_until: date | None = None
    level: int | None = None

    model_config = {"from_attributes": True}


class ResourceSkillEntry(BaseModel):
    """One qualification in a bulk replace, with its optional bounds."""

    skill_attribute_id: UUID
    valid_from: date | None = None
    # NULL means the qualification does not expire, which is the ordinary case for a
    # trade learned once.
    valid_until: date | None = None
    # NULL means nobody assessed the level, which is deliberately different from 1.
    level: int | None = Field(default=None, ge=1, le=5)


class ResourceSkillBoundsUpdate(BaseModel):
    """Partial update of one held qualification's bounds.

    All three fields are nullable AND optional, and the difference matters: omitting a field
    leaves it alone, while sending an explicit null clears it. Without that distinction an
    expiry date could never be removed once entered — "this no longer expires" is a
    legitimate correction, not a missing value.

    ``model_fields_set`` is what carries the distinction; the router passes only the fields
    the client actually mentioned.
    """

    valid_from: date | None = None
    valid_until: date | None = None
    level: int | None = Field(default=None, ge=1, le=5)


class ResourceSkillBulkUpdate(BaseModel):
    """Request schema for atomically replacing all skill assignments of a resource.

    Entries rather than bare ids, because the replace deletes and recreates every row:
    validity and level have to travel with the payload or they would be wiped on the
    next save.
    """

    entries: list[ResourceSkillEntry] = Field(
        ..., max_length=500, description="Qualifications to set (max 500)"
    )


# --- Resource Search Schemas ---


class ResourceSearchResult(BaseModel):
    """Response schema for a resource in the skill-based search."""

    id: UUID
    name: str
    department: str
    skills: list[ResourceSkillAssignmentResponse]

    model_config = {"from_attributes": True}
