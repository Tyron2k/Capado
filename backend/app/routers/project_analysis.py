"""HTTP routes for project analysis; retain existing auth and scopes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.project_overview import (
    ProjectOverviewResponse,
    ProjectScheduleResponse,
)
from app.services.permissions import (
    get_current_user,
)
from app.services.project_overview_service import ProjectOverviewService
from app.services.project_schedule_service import ProjectScheduleService

router = APIRouter()


def _parse_project_ids(raw: str | None) -> list[UUID] | None:
    """Parse comma-separated project_ids query value.

    Returns ``None`` if not provided; an empty list if only whitespace/empty
    tokens remain after parsing; raises ``HTTPException(400)`` on invalid UUIDs.
    """
    if raw is None:
        return None
    tokens = [t.strip() for t in raw.split(",")]
    tokens = [t for t in tokens if t]
    if not tokens:
        return []
    parsed: list[UUID] = []
    for token in tokens:
        try:
            parsed.append(UUID(token))
        except ValueError as err:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid project_ids element: {token!r}",
            ) from err
    return parsed


@router.get(
    "/projects/overview",
    response_model=ProjectOverviewResponse,
    summary="Get project overview with KPIs",
)
async def get_project_overview(
    project_ids: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> ProjectOverviewResponse:
    """Return aggregated KPIs per project for the project overview.

    Returns progress, active work packages, next deadline, open conflicts,
    and average resource utilization percentage per project.
    """
    return await ProjectOverviewService(session).get_overview(
        _parse_project_ids(project_ids)
    )


@router.get(
    "/projects/{project_id}/schedule",
    response_model=ProjectScheduleResponse,
    summary="Critical path and float for one project",
)
async def get_project_schedule(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Forward and backward pass over the project's work packages.

    Reports, per package, the earliest and latest it can start and finish, its float in
    working days, and whether it is on the critical path.

    The deadline is the committed delivery date where one exists, otherwise the planned
    end — and which of the two was used is part of the response, because float measured
    against a planned end that already misses the customer date reads far more
    comfortable than the situation is.

    Args:
        project_id: The project to analyse.
        session: Database session.
        _current_user: Authenticated user.

    Returns:
        The deadline used and one entry per work package.

    Raises:
        NotFoundError: If the project does not exist.
    """
    return await ProjectScheduleService(session).get_schedule(project_id)
