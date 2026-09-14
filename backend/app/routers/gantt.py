"""Gantt router: project and resource Gantt chart data.

GET /api/gantt/projects/{project_id}
GET /api/gantt/resources/infrastructure
GET /api/gantt/resources/departments
GET /api/gantt/resources/infrastructure/{group_id}
GET /api/gantt/resources/department/{department_name}
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.dashboard import (
    GanttResourceAssignmentSchema,
    GanttResourceInfo,
    GanttResponse,
    GanttWorkPackageBar,
)
from app.schemas.gantt_resource import (
    InfraGroupOption,
    ResourceGanttBarSchema,
    ResourceGanttProjectGroupSchema,
    ResourceGanttResponseSchema,
)
from app.services.gantt_resource_service import GanttResourceService
from app.services.gantt_service import GanttService
from app.services.permissions import get_current_user

router = APIRouter(tags=["Gantt"])


@router.get(
    "/gantt/projects/{project_id}",
    response_model=GanttResponse,
    summary="Get project Gantt chart data",
)
async def get_gantt_data(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> GanttResponse:
    """Return Gantt chart data for a project.

    Includes work packages as bars with assigned resources and conflict flags.

    Args:
        project_id: The UUID of the project.
        session: Database session.

    Returns:
        Gantt response with work package bars and resource assignments.

    """
    service = GanttService(session)
    data = await service.get_gantt_data(project_id)

    return GanttResponse(
        project_id=data["project_id"],
        project_name=data["project_name"],
        work_packages=[
            GanttWorkPackageBar(
                id=wp.id,
                name=wp.name,
                start_date=wp.start_date,
                end_date=wp.end_date,
                resources=[
                    GanttResourceInfo(
                        id=r.id,
                        name=r.name,
                        resource_type=r.resource_type,
                    )
                    for r in wp.resources
                ],
                resource_assignments=[
                    GanttResourceAssignmentSchema(
                        id=ra.id,
                        name=ra.name,
                        resource_type=ra.resource_type,
                        allocation_percent=ra.allocation_percent,
                    )
                    for ra in wp.resource_assignments
                ],
                has_conflict=wp.has_conflict,
            )
            for wp in data["work_packages"]
        ],
    )


# --- Resource Gantt endpoints ---


@router.get(
    "/gantt/resources/infrastructure",
    response_model=list[InfraGroupOption],
    summary="List available infrastructure groups",
)
async def get_available_infra_groups(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> list[InfraGroupOption]:
    """Return all active top-level infrastructure groups for the selection list.

    Args:
        session: Database session.

    Returns:
        List of infrastructure group options (id and name).

    """
    service = GanttResourceService(session)
    groups = await service.get_available_infra_groups()
    return [InfraGroupOption(**g) for g in groups]


@router.get(
    "/gantt/resources/departments",
    response_model=list[str],
    summary="List available departments",
)
async def get_available_departments(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> list[str]:
    """Return all distinct department names for the Gantt selection list.

    Args:
        session: Database session.

    Returns:
        Sorted list of department name strings.

    """
    service = GanttResourceService(session)
    return await service.get_available_departments()


@router.get(
    "/gantt/resources/infrastructure/{group_id}",
    response_model=ResourceGanttResponseSchema,
    summary="Get infrastructure group Gantt data",
)
async def get_infra_group_gantt(
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> ResourceGanttResponseSchema:
    """Return Gantt chart data for an infrastructure group.

    Args:
        group_id: The UUID of the infrastructure group.
        session: Database session.

    Returns:
        Resource Gantt response with project-grouped work package bars.

    """
    service = GanttResourceService(session)
    data = await service.get_infra_group_gantt_data(group_id)

    return ResourceGanttResponseSchema(
        resource_type=data.resource_type,
        resource_name=data.resource_name,
        projects=[
            ResourceGanttProjectGroupSchema(
                project_id=group.project_id,
                project_name=group.project_name,
                work_packages=[
                    ResourceGanttBarSchema(
                        id=bar.id,
                        name=bar.name,
                        start_date=bar.start_date.isoformat(),
                        end_date=bar.end_date.isoformat(),
                        resource_id=bar.resource_id,
                        resource_name=bar.resource_name,
                        allocation_percent=bar.allocation_percent,
                        has_conflict=bar.has_conflict,
                    )
                    for bar in group.work_packages
                ],
            )
            for group in data.projects
        ],
    )


@router.get(
    "/gantt/resources/department/{department_name}",
    response_model=ResourceGanttResponseSchema,
    summary="Get department Gantt data",
)
async def get_department_gantt(
    department_name: str = Path(..., min_length=1, max_length=255),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> ResourceGanttResponseSchema:
    """Return Gantt chart data for a department.

    Args:
        department_name: The name of the department.
        session: Database session.

    Returns:
        Resource Gantt response with project-grouped work package bars.

    """
    service = GanttResourceService(session)
    data = await service.get_department_gantt_data(department_name)

    return ResourceGanttResponseSchema(
        resource_type=data.resource_type,
        resource_name=data.resource_name,
        projects=[
            ResourceGanttProjectGroupSchema(
                project_id=group.project_id,
                project_name=group.project_name,
                work_packages=[
                    ResourceGanttBarSchema(
                        id=bar.id,
                        name=bar.name,
                        start_date=bar.start_date.isoformat(),
                        end_date=bar.end_date.isoformat(),
                        resource_id=bar.resource_id,
                        resource_name=bar.resource_name,
                        allocation_percent=bar.allocation_percent,
                        has_conflict=bar.has_conflict,
                    )
                    for bar in group.work_packages
                ],
            )
            for group in data.projects
        ],
    )
