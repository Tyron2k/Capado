"""GanttResourceService: Preparation of Gantt data from the resource perspective."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import NotFoundError
from app.models.assignment import Assignment
from app.models.conflict import ConflictAssignment
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource


@dataclass
class ResourceGanttBar:
    """A work package bar in the resource perspective."""

    id: UUID
    name: str
    start_date: date
    end_date: date
    resource_id: UUID
    resource_name: str
    allocation_percent: float = 0.0
    has_conflict: bool = False


@dataclass
class ResourceGanttProjectGroup:
    """A project group with associated work package bars."""

    project_id: UUID
    project_name: str
    work_packages: list[ResourceGanttBar] = field(default_factory=list)


@dataclass
class ResourceGanttResponse:
    """Complete response for resource Gantt."""

    resource_type: str  # "infrastructure" | "department"
    resource_name: str
    projects: list[ResourceGanttProjectGroup] = field(default_factory=list)


class GanttResourceService:
    """Prepare Gantt data from the resource perspective.

    - Infrastructure perspective: All assignments of the group and its active children
    - Department perspective: All assignments of active employees in a department
    - Grouped by project, sorted by name/start date
    - Conflict flag per work package bar
    """

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    async def get_infra_group_gantt_data(self, group_id: UUID) -> ResourceGanttResponse:
        """Return Gantt data for an infrastructure group.

        Retrieves all assignments of the selected infrastructure resource,
        grouped by project.

        Args:
            group_id: UUID of the infrastructure resource.

        Returns:
            ResourceGanttResponse with Gantt bars grouped by project.

        Raises:
            NotFoundError: If the resource does not exist or is inactive.

        """
        # 1. Load and validate resource group.
        from app.models.resource_group import ResourceGroup

        group = await self.session.get(ResourceGroup, group_id)
        if group is None:
            raise NotFoundError("ResourceGroup", group_id)

        # 2. Load all active infrastructure resources in this group
        infra_stmt = select(InfrastructureResource).where(
            InfrastructureResource.group_id == group_id,
            InfrastructureResource.is_active == True,  # noqa: E712
        )
        infra_result = await self.session.execute(infra_stmt)
        infra_resources = list(infra_result.scalars().all())

        if not infra_resources:
            raise NotFoundError("InfrastructureGroup", group_id)

        # All relevant resource IDs
        resource_ids = [r.id for r in infra_resources]

        # Build resource name map
        resource_name_map: dict[UUID, str] = {r.id: r.name for r in infra_resources}

        # 3. Load assignments for group + active children (resource_type = "infrastructure")
        assignment_stmt = select(Assignment).where(
            Assignment.resource_id.in_(resource_ids),
            Assignment.resource_type == "infrastructure",
        )
        assignment_result = await self.session.execute(assignment_stmt)
        assignments = list(assignment_result.scalars().all())

        if not assignments:
            return ResourceGanttResponse(
                resource_type="infrastructure",
                resource_name=group.name,
                projects=[],
            )

        # 4. Load associated work packages and projects
        wp_ids = list({a.work_package_id for a in assignments})
        wp_stmt = select(WorkPackage).where(WorkPackage.id.in_(wp_ids))
        wp_result = await self.session.execute(wp_stmt)
        work_packages = list(wp_result.scalars().all())
        wp_map: dict[UUID, WorkPackage] = {wp.id: wp for wp in work_packages}

        # Load projects (only existing/active projects)
        project_ids = list({wp.project_id for wp in work_packages})
        project_stmt = select(Project).where(Project.id.in_(project_ids))
        project_result = await self.session.execute(project_stmt)
        projects = list(project_result.scalars().all())
        project_map: dict[UUID, Project] = {p.id: p for p in projects}

        # 5. Check ConflictAssignments for has_conflict flag
        assignment_ids = [a.id for a in assignments]
        conflict_assignment_ids: set[UUID] = set()
        if assignment_ids:
            ca_stmt = select(ConflictAssignment).where(
                ConflictAssignment.assignment_id.in_(assignment_ids)
            )
            ca_result = await self.session.execute(ca_stmt)
            conflict_assignments = list(ca_result.scalars().all())
            conflict_assignment_ids = {ca.assignment_id for ca in conflict_assignments}

        # 6. Group by project (alphabetically), within by start_date
        project_groups: dict[UUID, ResourceGanttProjectGroup] = {}

        for assignment in assignments:
            wp = wp_map.get(assignment.work_package_id)
            if wp is None:
                continue

            project = project_map.get(wp.project_id)
            if project is None:
                continue

            # Create or retrieve project group
            if project.id not in project_groups:
                project_groups[project.id] = ResourceGanttProjectGroup(
                    project_id=project.id,
                    project_name=project.name,
                    work_packages=[],
                )

            # Create Gantt bar
            bar = ResourceGanttBar(
                id=wp.id,
                name=wp.name,
                start_date=_assignment_dates(assignment)[0],
                end_date=_assignment_dates(assignment)[1],
                resource_id=assignment.resource_id,
                resource_name=resource_name_map.get(assignment.resource_id, ""),
                allocation_percent=_assignment_display_percent(assignment),
                has_conflict=assignment.id in conflict_assignment_ids,
            )
            project_groups[project.id].work_packages.append(bar)

        # Sort: projects alphabetically by name, work packages by start_date
        sorted_groups = sorted(
            project_groups.values(), key=lambda g: g.project_name.lower()
        )
        for pg in sorted_groups:
            pg.work_packages.sort(key=lambda bar: bar.start_date)

        return ResourceGanttResponse(
            resource_type="infrastructure",
            resource_name=group.name,
            projects=sorted_groups,
        )

    async def get_department_gantt_data(
        self, department_name: str
    ) -> ResourceGanttResponse:
        """Return Gantt data for a department.

        Retrieves all assignments of active personal resources in this
        department, grouped by project.

        Args:
            department_name: Name of the department.

        Returns:
            ResourceGanttResponse with Gantt bars grouped by project.

        Raises:
            NotFoundError: If no active employees exist for the department.

        """
        # 1. Load active PersonalResources in the named group
        from app.models.resource_group import ResourceGroup

        personal_stmt = (
            select(PersonalResource)
            .join(ResourceGroup, PersonalResource.group_id == ResourceGroup.id)
            .where(
                ResourceGroup.name == department_name,
                PersonalResource.is_active == True,  # noqa: E712
            )
        )
        personal_result = await self.session.execute(personal_stmt)
        personal_resources = list(personal_result.scalars().all())

        # If no active employees found: NotFoundError
        if not personal_resources:
            raise NotFoundError(
                "Department",
                department_name,
            )

        # Build resource IDs and name map
        resource_ids = [r.id for r in personal_resources]
        resource_name_map: dict[UUID, str] = {r.id: r.name for r in personal_resources}

        # 2. Load assignments for found resources (resource_type = "personal")
        assignment_stmt = select(Assignment).where(
            Assignment.resource_id.in_(resource_ids),
            Assignment.resource_type == "personal",
        )
        assignment_result = await self.session.execute(assignment_stmt)
        assignments = list(assignment_result.scalars().all())

        if not assignments:
            return ResourceGanttResponse(
                resource_type="department",
                resource_name=department_name,
                projects=[],
            )

        # 3. Load associated work packages and projects
        wp_ids = list({a.work_package_id for a in assignments})
        wp_stmt = select(WorkPackage).where(WorkPackage.id.in_(wp_ids))
        wp_result = await self.session.execute(wp_stmt)
        work_packages = list(wp_result.scalars().all())
        wp_map: dict[UUID, WorkPackage] = {wp.id: wp for wp in work_packages}

        project_ids = list({wp.project_id for wp in work_packages})
        project_stmt = select(Project).where(Project.id.in_(project_ids))
        project_result = await self.session.execute(project_stmt)
        projects = list(project_result.scalars().all())
        project_map: dict[UUID, Project] = {p.id: p for p in projects}

        # 4. Check ConflictAssignments for has_conflict flag
        assignment_ids = [a.id for a in assignments]
        conflict_assignment_ids: set[UUID] = set()
        if assignment_ids:
            ca_stmt = select(ConflictAssignment).where(
                ConflictAssignment.assignment_id.in_(assignment_ids)
            )
            ca_result = await self.session.execute(ca_stmt)
            conflict_assignments = list(ca_result.scalars().all())
            conflict_assignment_ids = {ca.assignment_id for ca in conflict_assignments}

        # 5. Group by project (alphabetically), within by start_date
        project_groups: dict[UUID, ResourceGanttProjectGroup] = {}

        for assignment in assignments:
            wp = wp_map.get(assignment.work_package_id)
            if wp is None:
                continue

            project = project_map.get(wp.project_id)
            if project is None:
                continue

            # Create or retrieve project group
            if project.id not in project_groups:
                project_groups[project.id] = ResourceGanttProjectGroup(
                    project_id=project.id,
                    project_name=project.name,
                    work_packages=[],
                )

            # Create Gantt bar
            bar = ResourceGanttBar(
                id=wp.id,
                name=wp.name,
                start_date=_assignment_dates(assignment)[0],
                end_date=_assignment_dates(assignment)[1],
                resource_id=assignment.resource_id,
                resource_name=resource_name_map.get(assignment.resource_id, ""),
                allocation_percent=_assignment_display_percent(assignment),
                has_conflict=assignment.id in conflict_assignment_ids,
            )
            project_groups[project.id].work_packages.append(bar)

        # Sort: projects alphabetically by name, work packages by start_date
        sorted_groups = sorted(
            project_groups.values(), key=lambda g: g.project_name.lower()
        )
        for group in sorted_groups:
            group.work_packages.sort(key=lambda bar: bar.start_date)

        return ResourceGanttResponse(
            resource_type="department",
            resource_name=department_name,
            projects=sorted_groups,
        )

    async def get_available_infra_groups(self) -> list[dict]:
        """Distinct group names from active infrastructure resources, with id.

        Returns groups that have at least one active infrastructure resource.
        """
        from app.models.resource_group import ResourceGroup

        stmt = (
            select(ResourceGroup.id, ResourceGroup.name)
            .join(
                InfrastructureResource,
                InfrastructureResource.group_id == ResourceGroup.id,
            )
            .where(InfrastructureResource.is_active == True)  # noqa: E712
            .distinct()
            .order_by(ResourceGroup.name)
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            {
                "id": row[0],
                "name": row[1],
                "location": "",
            }
            for row in rows
        ]

    async def get_available_departments(self) -> list[str]:
        """Distinct group names from active personal resources, sorted.

        Returns:
            Sorted list of group names.

        """
        from app.models.resource_group import ResourceGroup

        stmt = (
            select(ResourceGroup.name)
            .join(PersonalResource, PersonalResource.group_id == ResourceGroup.id)
            .where(PersonalResource.is_active == True)  # noqa: E712
            .distinct()
            .order_by(ResourceGroup.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


def _assignment_display_percent(assignment: Assignment) -> float:
    """Return allocation percent. Infrastructure is always 100%."""
    if assignment.resource_type == "personal":
        return round(assignment.allocation_percent or 0.0, 2)
    return 100.0


def _assignment_dates(assignment: Assignment) -> tuple[date, date]:
    """Calendar days occupied by the booking; midnight ends are exclusive."""
    if assignment.start_at is not None and assignment.end_at is not None:
        return assignment.start_at.date(), (
            assignment.end_at - timedelta(microseconds=1)
        ).date()
    if assignment.start_date is not None and assignment.end_date is not None:
        return assignment.start_date, assignment.end_date
    raise ValueError(f"Assignment {assignment.id} has no complete booking interval")
