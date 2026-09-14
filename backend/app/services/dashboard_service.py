"""DashboardService: Aggregated utilization data and project list with conflict count."""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.assignment import Assignment
from app.models.conflict import ConflictAssignment
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource
from app.services.capacity_service import (
    BASE_CAPACITY_PERCENT,
    CapacityService,
    WeeklyUtilization,
    get_utilization_color,
)


@dataclass
class ProjectConflictSummary:
    """Project with count of open conflicts."""

    id: UUID
    name: str
    start_date: date
    end_date: date
    conflict_count: int


class DashboardService:
    """Aggregate utilization data for the dashboard.

    - Aggregated personal utilization per calendar week
    - Aggregated infrastructure utilization per calendar week
    - Project list with conflict count
    """

    def __init__(self, session: AsyncSession):
        """Initialize with a database session and capacity service."""
        self.session = session
        self.capacity_service = CapacityService(session)

    async def get_aggregated_utilization(
        self,
        resource_type: str,
        start_date: date,
        end_date: date,
        department: str | None = None,
        location: str | None = None,
    ) -> list[WeeklyUtilization]:
        """Compute aggregated weekly utilization across all active resources of a type.

        Bar chart of personal/infrastructure utilization per week.
        Filterable by department (personal) or location (infrastructure).

        Calculation: For each week the sum of all assigned hours is divided by
        the sum of all available hours across all resources of the type.

        Optimized to batch-load all assignments and absences upfront to avoid
        N+1 queries (one per resource).
        """
        from app.models.absence import Absence

        # Load active resources of the type (with optional filter)
        if resource_type == "personal":
            statement = select(PersonalResource).where(
                PersonalResource.is_active == True  # noqa: E712
            )
            if department is not None:
                from app.models.resource_group import ResourceGroup

                statement = statement.join(
                    ResourceGroup, PersonalResource.group_id == ResourceGroup.id
                ).where(ResourceGroup.name == department)
            result = await self.session.execute(statement)
            resources = list(result.scalars().all())
            resource_ids = [r.id for r in resources]
        else:
            infra_statement = select(InfrastructureResource).where(
                InfrastructureResource.is_active == True  # noqa: E712
            )
            if location is not None:
                from app.models.resource_group import ResourceGroup

                infra_statement = infra_statement.join(
                    ResourceGroup, InfrastructureResource.group_id == ResourceGroup.id
                ).where(ResourceGroup.name == location)
            result = await self.session.execute(infra_statement)
            resources = list(result.scalars().all())
            resource_ids = [r.id for r in resources]

        if not resource_ids:
            return []

        # Batch-load all assignments for these resources in one query
        assignments_stmt = select(Assignment).where(
            Assignment.resource_id.in_(resource_ids)
        )
        assignments_result = await self.session.execute(assignments_stmt)
        all_assignments = list(assignments_result.scalars().all())

        # Group assignments by resource_id
        assignments_by_resource: dict[UUID, list[Assignment]] = {
            rid: [] for rid in resource_ids
        }
        for a in all_assignments:
            assignments_by_resource.setdefault(a.resource_id, []).append(a)

        # Batch-load all absences for these resources in one query
        absences_stmt = select(Absence).where(Absence.resource_id.in_(resource_ids))
        absences_result = await self.session.execute(absences_stmt)
        all_absences = list(absences_result.scalars().all())

        # Group absences by resource_id
        absences_by_resource: dict[UUID, list] = {rid: [] for rid in resource_ids}
        for ab in all_absences:
            absences_by_resource.setdefault(ab.resource_id, []).append(ab)

        # Determine the resource type enum for capacity calculations
        from app.models.resource import ResourceType as RT

        rt = RT.personal if resource_type == "personal" else RT.infrastructure

        # Normalize to the Monday of start_date
        current_monday = start_date - timedelta(days=start_date.weekday())
        weeks: list[WeeklyUtilization] = []

        while current_monday <= end_date:
            total_available = 0.0
            total_assigned = 0.0
            total_overbooked = 0.0

            for resource_id in resource_ids:
                resource_assignments = assignments_by_resource.get(resource_id, [])
                resource_absences = absences_by_resource.get(resource_id, [])

                for i in range(7):
                    day = current_monday + timedelta(days=i)
                    if day > end_date:
                        break
                    available = BASE_CAPACITY_PERCENT
                    assigned = self.capacity_service._assigned_percent_for_day(
                        resource_assignments, rt, day
                    )
                    absent = self.capacity_service._absence_percent_for_day(
                        resource_absences, day
                    )
                    day_total = assigned + absent
                    total_available += available
                    total_assigned += day_total
                    if day_total > 100.0:
                        total_overbooked += day_total - 100.0

            utilization = (
                (total_assigned / total_available * 100) if total_available > 0 else 0.0
            )
            overbooked = (
                (total_overbooked / total_available * 100)
                if total_available > 0
                else 0.0
            )
            color = get_utilization_color(utilization)
            weeks.append(
                WeeklyUtilization(
                    week_start=current_monday,
                    total_available=total_available,
                    total_assigned=total_assigned,
                    utilization=utilization,
                    overbooked=overbooked,
                    color=color,
                )
            )
            current_monday += timedelta(weeks=1)

        return weeks

    async def get_projects_with_conflict_count(
        self, project_ids: list[UUID] | None = None
    ) -> list[ProjectConflictSummary]:
        """Return all projects with the count of open conflicts.

        Uses a SQL JOIN/GROUP BY to count conflicts per project in a single
        query instead of loading entire tables into memory.

        A conflict counts for a project if at least one of the involved
        assignments (ConflictAssignment) belongs to a work package of that project.
        """
        from sqlalchemy import distinct, func

        # Load all projects (optionally filtered)
        project_stmt = select(Project)
        if project_ids is not None:
            project_stmt = project_stmt.where(Project.id.in_(project_ids))
        project_result = await self.session.execute(project_stmt)
        projects = list(project_result.scalars().all())

        if not projects:
            return []

        # Count distinct conflicts per project via JOIN chain:
        # ConflictAssignment → Assignment → WorkPackage → Project
        count_stmt = (
            select(
                WorkPackage.project_id,
                func.count(distinct(ConflictAssignment.conflict_id)),
            )
            .join(Assignment, ConflictAssignment.assignment_id == Assignment.id)
            .join(WorkPackage, Assignment.work_package_id == WorkPackage.id)
        )
        if project_ids is not None:
            count_stmt = count_stmt.where(WorkPackage.project_id.in_(project_ids))
        count_stmt = count_stmt.group_by(WorkPackage.project_id)

        count_result = await self.session.execute(count_stmt)
        conflict_counts: dict[UUID, int] = {
            row[0]: row[1] for row in count_result.all()
        }

        return [
            ProjectConflictSummary(
                id=project.id,
                name=project.name,
                start_date=project.start_date,
                end_date=project.end_date,
                conflict_count=conflict_counts.get(project.id, 0),
            )
            for project in projects
        ]
