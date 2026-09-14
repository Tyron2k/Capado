"""Pydantic schemas for assignments.

Assignments come in two flavours that share one row:

* Personal: ``start_date`` / ``end_date`` / ``allocation_percent``
* Infrastructure: ``start_at`` / ``end_at`` (timestamps, minute precision)

The create and update schemas accept both shapes; the service layer enforces
that exactly the fields matching ``resource_type`` are supplied.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.resource import ResourceType


class AssignmentCreate(BaseModel):
    """Request payload for creating an assignment.

    Pass ``start_date``/``end_date``/``allocation_percent`` for personal assignments
    and ``start_at``/``end_at`` for infrastructure assignments. Mixing the two
    shapes in one payload is rejected by the service.
    """

    resource_id: UUID
    resource_type: ResourceType
    work_package_id: UUID

    # Personal assignment fields
    start_date: date | None = None
    end_date: date | None = None
    allocation_percent: float | None = Field(default=None, gt=0)

    # Infrastructure assignment fields
    start_at: datetime | None = None
    end_at: datetime | None = None


class AssignmentUpdate(BaseModel):
    """Partial update payload."""

    resource_id: UUID | None = None
    resource_type: ResourceType | None = None
    work_package_id: UUID | None = None

    start_date: date | None = None
    end_date: date | None = None
    allocation_percent: float | None = Field(default=None, gt=0)

    start_at: datetime | None = None
    end_at: datetime | None = None


class AssignmentResponse(BaseModel):
    """Response schema for an assignment of either shape.

    Enriched with resolved names (``resource_name``, ``work_package_name``,
    ``project_id`` + ``project_name``) so the UI does not have to render
    raw UUIDs. ``skill_mismatch`` indicates whether the assigned resource
    lacks skills required by the work package.
    """

    id: UUID
    resource_id: UUID
    resource_name: str | None = None
    resource_type: ResourceType
    work_package_id: UUID
    work_package_name: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    allocation_percent: float | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    skill_mismatch: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssignmentCreateResponse(BaseModel):
    """Response schema returned by POST/PUT (includes soft warnings)."""

    assignment: AssignmentResponse
    warnings: list[str] = []


class ResourceSuggestion(BaseModel):
    """A suggested resource that could fill an unmet requirement.

    Suggestions are ranked by fewest overlapping assignments in the work
    package date range so the least-busy candidates appear first.
    """

    resource_id: UUID
    resource_name: str
    resource_type: str  # 'personal' or 'infrastructure'
    group_name: str | None = None
    overlapping_assignments: int = 0


class UnmetRequirementResponse(BaseModel):
    """A single unmet skill requirement for a work package.

    Returned when a work package requires more resources with a specific
    skill/attribute than are currently assigned. Includes up to 5 suggested
    resources that have the matching skill and are ranked by availability.
    """

    work_package_id: UUID
    work_package_name: str
    project_id: UUID
    project_name: str
    start_date: date
    end_date: date
    skill_name: str
    attribute_name: str | None = None
    resource_type: str  # 'personal' or 'infrastructure'
    required_quantity: int
    assigned_quantity: float
    gap: float
    suggestions: list[ResourceSuggestion] = []
