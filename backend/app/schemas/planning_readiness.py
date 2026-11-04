"""Read-only evidence for one work package, assembled from existing checks."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.models.resource import ResourceType
from app.schemas import ResponseModel
from app.schemas.assignment import (
    AssignmentResponse,
    PreviewConflict,
    UnmetRequirementResponse,
)
from app.schemas.capacity import ConflictResponse

ReadinessStatus = Literal[
    "covered", "missing_requirements", "conflicting", "not_fully_assessable"
]
ReadinessLimit = Literal[
    "no_personnel_requirements",
    "no_infrastructure_requirements",
    "no_standard_profile",
    "missing_calendar",
    "personnel_clock_times",
    "infrastructure_continuity",
    "capacity_window_limit",
]


class PlanningWorkPackage(ResponseModel):
    """An active package selectable in the existing planning overview."""

    id: UUID
    name: str
    project_id: UUID
    project_name: str
    start_date: date
    end_date: date


class ReadinessConflict(PreviewConflict):
    """A current, read-only conflict with its affected resource and bookings."""

    resource_id: UUID
    resource_name: str
    resource_type: ResourceType
    assignment_ids: list[UUID]


class PersonnelSupplyGap(ResponseModel):
    """First booked standard workday with zero individual calendar supply."""

    resource_id: UUID
    resource_name: str
    day: date


class WorkPackageReadiness(ResponseModel):
    """Scoped evidence, known blockers and explicit limits of the checks."""

    work_package: PlanningWorkPackage
    checked_at: datetime
    status: ReadinessStatus
    personnel_status: ReadinessStatus
    infrastructure_status: ReadinessStatus
    qualification_status: ReadinessStatus
    personnel_requirements: int
    infrastructure_requirements: int
    limits: list[ReadinessLimit]
    supply_gaps: list[PersonnelSupplyGap]
    unmet_requirements: list[UnmetRequirementResponse]
    conflicts: list[ReadinessConflict]
    assignments: list[AssignmentResponse]


class PlanningOverviewResponse(ResponseModel):
    """Existing problem lists plus selectable active work packages."""

    unmet_requirements: list[UnmetRequirementResponse]
    conflicts: list[ConflictResponse]
    mismatched_assignments: list[AssignmentResponse]
    work_packages: list[PlanningWorkPackage]
