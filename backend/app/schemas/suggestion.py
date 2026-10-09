"""Pydantic schemas for resource suggestions (response models)."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas import ResponseModel

AvailabilityStatus = Literal["available", "partially_available", "unavailable"]


class ResourceSuggestionResponse(ResponseModel):
    """Response schema for a resource suggestion."""

    resource_id: UUID = Field(..., description="ID of the suggested resource")
    resource_name: str = Field(..., description="Name of the resource")
    qualification_summary: str = Field(
        ...,
        description=(
            "Comma-separated summary of matrix qualifications "
            "(e.g. 'Series Alpha/Electrical, Series Beta/Mechanical'). Empty string when "
            "no matrix entries exist."
        ),
    )
    department: str = Field(..., description="Department of the resource")
    availability_status: AvailabilityStatus = Field(
        ...,
        description="Availability status: available, partially_available, unavailable",
    )
    average_free_capacity: float = Field(
        ..., description="Average free capacity as percentage"
    )
    reason: str = Field(..., description="Explanation of suitability")
