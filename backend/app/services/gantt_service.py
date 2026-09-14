"""GanttService: Preparation of Gantt data for a project."""

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import NotFoundError
from app.models.assignment import Assignment
from app.models.conflict import ConflictAssignment
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource


@dataclass
class GanttResourceInfo:
    """Resource info for a Gantt bar."""

    id: UUID
    name: str
    resource_type: str  # "personal" | "infrastructure"


@dataclass
class GanttResourceAssignmentInfo:
    """Resource with allocation percent from an assignment."""

    id: UUID
    name: str
    resource_type: str  # "personal" | "infrastructure"
    allocation_percent: float  # 2 decimals


@dataclass
class GanttWorkPackageBar:
    """A work package as a Gantt bar."""

    id: UUID
    name: str
    start_date: date
    end_date: date
    resources: list[GanttResourceInfo] = field(default_factory=list)
    resource_assignments: list[GanttResourceAssignmentInfo] = field(
        default_factory=list
    )
    has_conflict: bool = False


class GanttService:
    """Prepare Gantt data for a project.

    - Work packages as horizontal bars
    - Assigned resources per bar
    - Conflict flag when an assignment in the work package is involved in a conflict
    """

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    async def get_gantt_data(self, project_id: UUID) -> dict:
        """Return Gantt data for a project: work packages with resources and conflict flags."""
        # Load project
        project = await self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project", project_id)

        # Load work packages for the project
        wp_stmt = select(WorkPackage).where(WorkPackage.project_id == project_id)
        wp_result = await self.session.execute(wp_stmt)
        work_packages = list(wp_result.scalars().all())

        if not work_packages:
            return {
                "project_id": project.id,
                "project_name": project.name,
                "work_packages": [],
            }

        # Load all assignments for the work packages
        wp_ids = [wp.id for wp in work_packages]
        assignment_stmt = select(Assignment).where(
            Assignment.work_package_id.in_(wp_ids)
        )
        assignment_result = await self.session.execute(assignment_stmt)
        all_assignments = list(assignment_result.scalars().all())

        # Mapping: work_package_id -> list of assignments
        wp_assignments: dict[UUID, list[Assignment]] = {}
        for a in all_assignments:
            if a.work_package_id not in wp_assignments:
                wp_assignments[a.work_package_id] = []
            wp_assignments[a.work_package_id].append(a)

        # Collect all assignment IDs for conflict checking
        all_assignment_ids = {a.id for a in all_assignments}

        # Load ConflictAssignments that reference our assignments
        conflict_assignment_ids: set[UUID] = set()
        if all_assignment_ids:
            ca_stmt = select(ConflictAssignment).where(
                ConflictAssignment.assignment_id.in_(list(all_assignment_ids))
            )
            ca_result = await self.session.execute(ca_stmt)
            conflict_assignments = list(ca_result.scalars().all())
            conflict_assignment_ids = {ca.assignment_id for ca in conflict_assignments}

        # Load resource names (personal + infrastructure)
        resource_ids = {a.resource_id for a in all_assignments}
        resource_info_map: dict[UUID, GanttResourceInfo] = {}

        if resource_ids:
            # Personal resources
            personal_stmt = select(PersonalResource).where(
                PersonalResource.id.in_(list(resource_ids))
            )
            personal_result = await self.session.execute(personal_stmt)
            for r in personal_result.scalars().all():
                resource_info_map[r.id] = GanttResourceInfo(
                    id=r.id, name=r.name, resource_type="personal"
                )

            # Infrastructure resources
            infra_stmt = select(InfrastructureResource).where(
                InfrastructureResource.id.in_(list(resource_ids))
            )
            infra_result = await self.session.execute(infra_stmt)
            for infra_r in infra_result.scalars().all():
                resource_info_map[infra_r.id] = GanttResourceInfo(
                    id=infra_r.id, name=infra_r.name, resource_type="infrastructure"
                )

        # Build Gantt bars
        bars: list[GanttWorkPackageBar] = []
        for wp in work_packages:
            assignments = wp_assignments.get(wp.id, [])

            # Resources for this work package
            resources: list[GanttResourceInfo] = []
            # Hours/day per resource (sum when multiple assignments for the same resource)
            percent_by_resource: dict[UUID, float] = {}
            has_conflict = False

            for a in assignments:
                # Add resource info
                resource_info = resource_info_map.get(a.resource_id)
                if resource_info and resource_info not in resources:
                    resources.append(resource_info)

                # Sum hours. For personal the values come directly from
                # ``allocation_percent``; for infra we estimate the occupancy
                # share as interval hours / calendar days.
                percent_by_resource[a.resource_id] = percent_by_resource.get(
                    a.resource_id, 0.0
                ) + _assignment_percent(a)

                # Check conflict flag
                if a.id in conflict_assignment_ids:
                    has_conflict = True

            resource_assignments = [
                GanttResourceAssignmentInfo(
                    id=r.id,
                    name=r.name,
                    resource_type=r.resource_type,
                    allocation_percent=round(percent_by_resource.get(r.id, 0.0), 2),
                )
                for r in resources
            ]

            bars.append(
                GanttWorkPackageBar(
                    id=wp.id,
                    name=wp.name,
                    start_date=wp.start_date,
                    end_date=wp.end_date,
                    resources=resources,
                    resource_assignments=resource_assignments,
                    has_conflict=has_conflict,
                )
            )

        return {
            "project_id": project.id,
            "project_name": project.name,
            "work_packages": bars,
        }


def _assignment_percent(assignment: Assignment) -> float:
    """Allocation percent for either assignment shape."""
    if assignment.resource_type == "personal":
        return assignment.allocation_percent or 0.0
    if (
        assignment.start_at is not None
        and assignment.end_at is not None
        and assignment.end_at > assignment.start_at
    ):
        return 100.0  # Infrastructure is always 100% exclusive
    return 0.0
