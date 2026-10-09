"""Pydantic-Schemas für Dashboard- und Gantt-API (Response)."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel

from app.schemas import ResponseModel

# --- Dashboard Schemas ---


class WeeklyUtilizationResponse(BaseModel):
    """Weekly utilization aggregated across all resources of a type."""

    week_start: date
    total_available: float
    total_assigned: float
    utilization: float  # percent
    overbooked: float  # percent (overbooked portion)
    color: str  # "green", "yellow", "red"


class ProjectConflictSummary(ResponseModel):
    """Project with open conflict count for the dashboard project list."""

    id: UUID
    name: str
    start_date: date
    end_date: date
    conflict_count: int


class DashboardResponse(ResponseModel):
    """Response schema for GET /api/dashboard."""

    personal_utilization: list[WeeklyUtilizationResponse]
    infrastructure_utilization: list[WeeklyUtilizationResponse]
    projects: list[ProjectConflictSummary]


# --- Gantt Schemas ---


class GanttResourceInfo(ResponseModel):
    """Resource info for a Gantt bar."""

    id: UUID
    name: str
    resource_type: str  # "personal" | "infrastructure"


class GanttResourceAssignmentSchema(ResponseModel):
    """Ressource mit zugewiesenen Stunden/Tag."""

    id: UUID
    name: str
    resource_type: str  # "personal" | "infrastructure"
    allocation_percent: float


class GanttWorkPackageBar(ResponseModel):
    """A work package as a Gantt bar with assigned resources and conflict flag."""

    id: UUID
    name: str
    start_date: date
    end_date: date
    resources: list[GanttResourceInfo]
    resource_assignments: list[GanttResourceAssignmentSchema]
    has_conflict: bool


class GanttResponse(ResponseModel):
    """Response-Schema für GET /api/gantt/projects/{projectId}."""

    project_id: UUID
    project_name: str
    work_packages: list[GanttWorkPackageBar]
