"""Pydantic schemas for the autocomplete API (response)."""

from uuid import UUID

from pydantic import BaseModel, Field


class AutocompleteResultResponse(BaseModel):
    """Response schema for an autocomplete result."""

    id: UUID = Field(..., description="Resource ID")
    name: str = Field(..., description="Resource name")
    type: str = Field(..., description="Resource type: 'personal' or 'infrastructure'")
    detail: str = Field(
        ...,
        description="Group name for the resource",
    )

    model_config = {"from_attributes": True}
