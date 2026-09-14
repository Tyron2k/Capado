"""Dashboard router: GET /api/dashboard."""

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.dashboard import (
    DashboardResponse,
    ProjectConflictSummary,
    WeeklyUtilizationResponse,
)
from app.services.dashboard_service import DashboardService
from app.services.permissions import get_current_user

router = APIRouter(tags=["Dashboard"])


def _parse_project_ids(project_ids_str: str) -> list[UUID]:
    """Parse comma-separated project IDs string into a list of UUIDs.

    Raises HTTP 400 if any ID is not a valid UUID.
    """
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


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Get dashboard data",
)
async def get_dashboard(
    start_date: date | None = Query(
        None,
        description="Start date for utilization calculation (default: current Monday)",
    ),
    end_date: date | None = Query(
        None,
        description="End date for utilization calculation (default: 12 weeks from start)",
    ),
    department: str | None = Query(
        None,
        description="Filter by department (for personal utilization)",
    ),
    location: str | None = Query(
        None,
        description="Filter by location (for infrastructure utilization)",
    ),
    project_ids: str | None = Query(
        None,
        description="Comma-separated project IDs to filter the project list",
    ),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    """Dashboard data: aggregated utilization and project list with conflicts.

    - personal_utilization: Aggregated personal utilization per calendar week
    - infrastructure_utilization: Aggregated infrastructure utilization per calendar week
    - projects: Project list with conflict count

    Filters:
    - department: Restricts personal utilization to a department
    - location: Restricts infrastructure utilization to a location
    - project_ids: Restricts project list to specific projects
    """
    # Validate project_ids if provided
    parsed_project_ids: list[UUID] | None = None
    if project_ids is not None:
        parsed_project_ids = _parse_project_ids(project_ids)

    service = DashboardService(session)

    # Default time range: current Monday + 12 weeks
    if start_date is None:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())  # Monday
    if end_date is None:
        end_date = start_date + timedelta(weeks=12)

    # Calculate aggregated utilization (with optional filters)
    personal_utilization = await service.get_aggregated_utilization(
        "personal", start_date, end_date, department=department
    )
    infrastructure_utilization = await service.get_aggregated_utilization(
        "infrastructure", start_date, end_date, location=location
    )

    # Project list with conflict count (optionally filtered by project_ids)
    project_summaries = await service.get_projects_with_conflict_count(
        project_ids=parsed_project_ids
    )

    return DashboardResponse(
        personal_utilization=[
            WeeklyUtilizationResponse(
                week_start=w.week_start,
                total_available=w.total_available,
                total_assigned=w.total_assigned,
                utilization=w.utilization,
                overbooked=w.overbooked,
                color=w.color,
            )
            for w in personal_utilization
        ],
        infrastructure_utilization=[
            WeeklyUtilizationResponse(
                week_start=w.week_start,
                total_available=w.total_available,
                total_assigned=w.total_assigned,
                utilization=w.utilization,
                overbooked=w.overbooked,
                color=w.color,
            )
            for w in infrastructure_utilization
        ],
        projects=[
            ProjectConflictSummary(
                id=p.id,
                name=p.name,
                start_date=p.start_date,
                end_date=p.end_date,
                conflict_count=p.conflict_count,
            )
            for p in project_summaries
        ],
    )
