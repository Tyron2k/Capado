"""Pydantic schemas for the absences API."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.absence import AbsenceReason, AbsenceStatus
from app.models.resource import ResourceType


class AbsenceCreate(BaseModel):
    """Request body for creating an absence."""

    resource_id: UUID
    resource_type: ResourceType
    reason: AbsenceReason
    start_date: date
    end_date: date
    allocation_percent: float = Field(default=100.0, gt=0, le=100)
    # Defaults to confirmed: an absence a planner types in is a fact unless they say
    # otherwise. Both statuses reduce capacity identically — see AbsenceStatus.
    status: AbsenceStatus = AbsenceStatus.confirmed
    note: str | None = Field(default=None, max_length=500)


class AbsenceUpdate(BaseModel):
    """Request body for updating an absence (partial)."""

    reason: AbsenceReason | None = None
    start_date: date | None = None
    end_date: date | None = None
    allocation_percent: float | None = Field(default=None, gt=0, le=100)
    status: AbsenceStatus | None = None
    note: str | None = None


class AbsenceResponse(BaseModel):
    """Response schema for an absence."""

    id: UUID
    resource_id: UUID
    resource_type: ResourceType
    reason: AbsenceReason
    start_date: date
    end_date: date
    allocation_percent: float
    status: AbsenceStatus
    note: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}
