"""Router for capacity overview.

Endpoints:
- GET /capacity/overview          — Capacity overview (weekly, filterable)
- GET /capacity/resources/{id}    — Detailed utilization of a resource (daily)

Conflict endpoints are in ``app.routers.conflicts``.
"""

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.exceptions import NotFoundError
from app.models.assignment import Assignment
from app.models.project import WorkPackage
from app.models.resource import (
    InfrastructureResource,
    PersonalResource,
    ResourceType,
)
from app.models.user import User
from app.schemas.capacity import (
    CapacityOverviewResponse,
    DailyUtilizationResponse,
    ResourceCapacityDetailResponse,
    ResourceOverviewItem,
    WeeklyUtilizationResponse,
)
from app.services.capacity_service import CapacityService
from app.services.permissions import get_current_user

router = APIRouter(tags=["Capacity"])


def _parse_project_ids(project_ids_str: str) -> list[UUID]:
    """Parse comma-separated project IDs; raise 400 on invalid UUIDs."""
    ids: list[UUID] = []
    for raw_id in project_ids_str.split(","):
        raw_id = raw_id.strip()
        if not raw_id:
            continue
        try:
            ids.append(UUID(raw_id))
        except (ValueError, AttributeError) as err:
            raise HTTPException(
                status_code=400,
                detail="Invalid project ID in parameter project_ids.",
            ) from err
    return ids


async def _get_resource_ids_for_projects(
    session: AsyncSession, project_ids: list[UUID]
) -> set[UUID]:
    """Resource IDs that have assignments on work packages of these projects."""
    wp_stmt = select(WorkPackage.id).where(WorkPackage.project_id.in_(project_ids))
    wp_result = await session.execute(wp_stmt)
    wp_ids = [row[0] for row in wp_result.all()]

    if not wp_ids:
        return set()

    assign_stmt = select(Assignment.resource_id).where(
        Assignment.work_package_id.in_(wp_ids)
    )
    assign_result = await session.execute(assign_stmt)
    return {row[0] for row in assign_result.all()}


@router.get(
    "/capacity/overview",
    response_model=CapacityOverviewResponse,
    summary="Get capacity overview",
)
async def get_capacity_overview(
    start_date: date | None = Query(
        default=None, alias="startDate", description="Start date of the time range"
    ),
    end_date: date | None = Query(
        default=None, alias="endDate", description="End date of the time range"
    ),
    resource_type: ResourceType | None = Query(
        default=None, alias="resourceType", description="Filter by resource type"
    ),
    department: str | None = Query(
        default=None,
        description="Filter by department (personal) or location (infrastructure)",
    ),
    project_ids: str | None = Query(
        default=None,
        description="Comma-separated project IDs to filter by project membership",
    ),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return weekly utilization overview for all resources.

    Supports filtering by resource type, department/location, and project
    membership. Defaults to a 4-week window starting from the current Monday.

    Args:
        start_date: Start of the time range (default: current Monday).
        end_date: End of the time range (default: 4 weeks from start).
        resource_type: Optional filter by personal or infrastructure.
        department: Optional filter by department or location name.
        project_ids: Comma-separated project IDs to filter by membership.
        session: Database session.

    Returns:
        Capacity overview with weekly utilization per resource.

    """
    parsed_project_ids: list[UUID] | None = None
    if project_ids is not None:
        parsed_project_ids = _parse_project_ids(project_ids)

    if start_date is None:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
    if end_date is None:
        end_date = start_date + timedelta(weeks=4)

    project_resource_ids: set | None = None
    if parsed_project_ids is not None:
        project_resource_ids = await _get_resource_ids_for_projects(
            session, parsed_project_ids
        )

    capacity_service = CapacityService(session)
    resources: list[ResourceOverviewItem] = []

    if resource_type is None or resource_type == ResourceType.personal:
        from app.models.resource_group import ResourceGroup

        # The group name is joined rather than read off the resource: free-text
        # department and location fields were replaced by ResourceGroup, so
        # `res.department` no longer exists. This mirrors the infrastructure
        # branch below.
        statement = (
            select(PersonalResource, ResourceGroup.name.label("group_name"))
            .outerjoin(ResourceGroup, PersonalResource.group_id == ResourceGroup.id)
            .where(PersonalResource.is_active.is_(True))
        )
        if department is not None:
            statement = statement.where(ResourceGroup.name == department)
        personal_rows = (await session.execute(statement)).all()

        for row in personal_rows:
            res = row[0]
            group_name = row[1] or ""
            if project_resource_ids is not None and res.id not in project_resource_ids:
                continue
            weeks = await capacity_service.get_weekly_utilization(
                res.id, start_date, end_date
            )
            resources.append(
                ResourceOverviewItem(
                    resource_id=res.id,
                    resource_name=res.name,
                    resource_type=ResourceType.personal,
                    department_or_location=group_name,
                    weeks=[
                        WeeklyUtilizationResponse(
                            week_start=w.week_start,
                            total_available=w.total_available,
                            total_assigned=w.total_assigned,
                            utilization=w.utilization,
                            overbooked=w.overbooked,
                            color=w.color,
                        )
                        for w in weeks
                    ],
                )
            )

    if resource_type is None or resource_type == ResourceType.infrastructure:
        from app.models.resource_group import ResourceGroup

        infra_stmt = (
            select(InfrastructureResource, ResourceGroup.name.label("group_name"))
            .outerjoin(
                ResourceGroup, InfrastructureResource.group_id == ResourceGroup.id
            )
            .where(InfrastructureResource.is_active.is_(True))
        )
        if department is not None:
            infra_stmt = infra_stmt.where(ResourceGroup.name == department)
        infra_rows = (await session.execute(infra_stmt)).all()

        for row in infra_rows:
            res = row[0]
            group_name = row[1] or ""
            if project_resource_ids is not None and res.id not in project_resource_ids:
                continue
            weeks = await capacity_service.get_weekly_utilization(
                res.id, start_date, end_date
            )
            resources.append(
                ResourceOverviewItem(
                    resource_id=res.id,
                    resource_name=res.name,
                    resource_type=ResourceType.infrastructure,
                    department_or_location=group_name,
                    weeks=[
                        WeeklyUtilizationResponse(
                            week_start=w.week_start,
                            total_available=w.total_available,
                            total_assigned=w.total_assigned,
                            utilization=w.utilization,
                            overbooked=w.overbooked,
                            color=w.color,
                        )
                        for w in weeks
                    ],
                )
            )

    return CapacityOverviewResponse(
        resources=resources,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/capacity/resources/{resource_id}",
    response_model=ResourceCapacityDetailResponse,
    summary="Get resource capacity detail",
)
async def get_resource_capacity_detail(
    resource_id: UUID,
    start_date: date | None = Query(
        default=None, alias="startDate", description="Start date"
    ),
    end_date: date | None = Query(
        default=None, alias="endDate", description="End date"
    ),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return detailed daily utilization for a single resource.

    Defaults to a 2-week window starting from the current Monday.

    Args:
        resource_id: The UUID of the resource.
        start_date: Start of the time range (default: current Monday).
        end_date: End of the time range (default: 2 weeks from start).
        session: Database session.

    Returns:
        Daily utilization breakdown for the resource.

    Raises:
        NotFoundError: If the resource does not exist.

    """
    if start_date is None:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
    if end_date is None:
        end_date = start_date + timedelta(weeks=2)

    personal = await session.get(PersonalResource, resource_id)
    infrastructure = await session.get(InfrastructureResource, resource_id)

    if personal is not None:
        resource_name = personal.name
        res_type = ResourceType.personal
    elif infrastructure is not None:
        resource_name = infrastructure.name
        res_type = ResourceType.infrastructure
    else:
        raise NotFoundError("Resource", resource_id)

    capacity_service = CapacityService(session)
    daily_data = await capacity_service.calculate_utilization(
        resource_id, start_date, end_date
    )

    days = [
        DailyUtilizationResponse(
            date=d.date,
            available=d.available,
            assigned=d.assigned,
            utilization=d.utilization,
            color=d.color,
        )
        for d in daily_data
    ]

    return ResourceCapacityDetailResponse(
        resource_id=resource_id,
        resource_name=resource_name,
        resource_type=res_type,
        days=days,
    )
