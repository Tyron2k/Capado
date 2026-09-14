"""Pydantic-Schemas für Kapazitäts- und Konflikt-Endpunkte: Response-Modelle."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.resource import ResourceType

# --- Capacity Overview (Weekly) ---


class WeeklyUtilizationResponse(BaseModel):
    """Weekly utilization for a single resource."""

    week_start: date
    total_available: float
    total_assigned: float
    utilization: float
    overbooked: float
    color: str


class ResourceOverviewItem(BaseModel):
    """Capacity overview for a single resource."""

    resource_id: UUID
    resource_name: str
    resource_type: ResourceType
    department_or_location: str
    weeks: list[WeeklyUtilizationResponse]


class CapacityOverviewResponse(BaseModel):
    """Full capacity overview (all resources with weekly utilization)."""

    resources: list[ResourceOverviewItem]
    start_date: date
    end_date: date


# --- Capacity Detail (Daily) ---


class DailyUtilizationResponse(BaseModel):
    """Daily utilization for a single resource."""

    date: date
    available: float
    assigned: float
    utilization: float
    color: str


class ResourceCapacityDetailResponse(BaseModel):
    """Detailed utilization for a single resource (daily breakdown)."""

    resource_id: UUID
    resource_name: str
    resource_type: ResourceType
    days: list[DailyUtilizationResponse]


# --- Conflicts ---


Severity = Literal["low", "medium", "high"]


class ConflictAssignmentInfo(BaseModel):
    """Information about an assignment involved in a conflict."""

    assignment_id: UUID
    work_package_id: UUID | None = None
    work_package_name: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    resource_id: UUID | None = None
    resource_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    allocation_percent: float | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    skill_mismatch: bool = False


class ConflictResponse(BaseModel):
    """Response schema for a conflict.

    Severity is derived from overload_ratio = total_assigned_percent / available_percent:
    overload_ratio <= 1.25 → "low"; 1.25 < ratio <= 1.5 → "medium"; > 1.5 → "high".
    If available_percent == 0, severity is forced to "high" and overload_ratio is null.
    """

    id: UUID
    resource_id: UUID
    resource_name: str | None = None
    resource_type: ResourceType
    start_date: date
    end_date: date
    total_assigned_percent: float
    available_percent: float
    severity: Severity
    overload_ratio: float | None = None
    detected_at: datetime
    assignments: list[ConflictAssignmentInfo] = []

    model_config = {"from_attributes": True}


class ConflictListResponse(BaseModel):
    """Liste aller Konflikte."""

    conflicts: list[ConflictResponse]
    total: int


def compute_severity(
    total_assigned_percent: float, available_percent: float
) -> tuple[Severity, float | None]:
    """Derive severity and overload_ratio from assigned vs available percent."""
    if available_percent <= 0:
        return "high", None
    ratio = round(total_assigned_percent / available_percent, 2)
    if ratio <= 1.25:
        return "low", ratio
    if ratio <= 1.5:
        return "medium", ratio
    return "high", ratio
