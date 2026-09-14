"""Pydantic schemas for work package templates."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RequirementCreate(BaseModel):
    """Request schema for a single skill requirement."""

    skill_id: UUID
    skill_attribute_id: UUID | None = None
    quantity: int = Field(default=1, ge=1)


class RequirementResponse(BaseModel):
    """Response schema for a skill requirement with resolved names."""

    id: UUID
    skill_id: UUID
    skill_name: str
    skill_attribute_id: UUID | None = None
    skill_attribute_name: str | None = None
    quantity: int

    model_config = {"from_attributes": True}


class TemplateCreate(BaseModel):
    """Request schema for creating a template."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    requirements: list[RequirementCreate] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    """Request schema for updating a template."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)


class TemplateResponse(BaseModel):
    """Response schema for a template with its requirements."""

    id: UUID
    name: str
    description: str | None = None
    requirements: list[RequirementResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateListResponse(BaseModel):
    """Response schema for template list (without requirements)."""

    id: UUID
    name: str
    description: str | None = None
    requirement_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}
