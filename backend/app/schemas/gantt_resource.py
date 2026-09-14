"""Pydantic schemas for the resource Gantt view (response)."""

from uuid import UUID

from pydantic import BaseModel


class InfraGroupOption(BaseModel):
    """An active infrastructure group as a selection option for the resource perspective."""

    id: UUID
    name: str
    location: str


class ResourceGanttBarSchema(BaseModel):
    """A work package bar in the resource Gantt view."""

    id: UUID
    name: str
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    resource_id: UUID
    resource_name: str
    allocation_percent: float
    has_conflict: bool


class ResourceGanttProjectGroupSchema(BaseModel):
    """A project group with associated work package bars."""

    project_id: UUID
    project_name: str
    work_packages: list[ResourceGanttBarSchema]


class ResourceGanttResponseSchema(BaseModel):
    """Complete response for resource Gantt (infrastructure or department)."""

    resource_type: str  # "infrastructure" | "department"
    resource_name: str
    projects: list[ResourceGanttProjectGroupSchema]
