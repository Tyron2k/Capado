"""Router for Resource Suggestions.

Endpoints:
- GET /suggestions — Resource suggestions based on time range and hours/day
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.suggestion import ResourceSuggestionResponse
from app.services.permissions import get_current_user
from app.services.suggestion_service import SuggestionService

router = APIRouter(tags=["Suggestions"])


@router.get(
    "/suggestions",
    response_model=list[ResourceSuggestionResponse],
    summary="Get resource suggestions for a work package",
)
async def get_suggestions(
    start_date: date = Query(
        ..., alias="start_date", description="Start date of the time range (required)"
    ),
    end_date: date = Query(
        ..., alias="end_date", description="End date of the time range (required)"
    ),
    allocation_percent: float = Query(
        ...,
        alias="allocation_percent",
        description="Required allocation percent (required)",
    ),
    work_package_id: UUID | None = Query(
        default=None,
        description="Exclude resources already assigned to this work package",
    ),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return resource suggestions for a work package based on availability.

    Provides a sorted list of suitable personal resources based on free
    capacity within the specified time range and allocation requirement.

    Args:
        start_date: Start date of the time range.
        end_date: End date of the time range.
        allocation_percent: Required allocation percentage.
        work_package_id: Optional work package whose assigned resources are excluded.
        session: Database session.

    Returns:
        Sorted list of resource suggestions with availability info.

    Raises:
        HTTPException: 400 if start_date > end_date or allocation_percent <= 0.

    """
    # Validation: start_date <= end_date
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="The start date must not be after the end date.",
        )

    # Validation: allocation_percent > 0
    if allocation_percent <= 0:
        raise HTTPException(
            status_code=400,
            detail="Allocation percent must be greater than 0.",
        )

    service = SuggestionService(session)
    suggestions = await service.get_suggestions(
        start_date=start_date,
        end_date=end_date,
        allocation_percent=allocation_percent,
        work_package_id=work_package_id,
    )

    return [
        ResourceSuggestionResponse(
            resource_id=s.resource_id,
            resource_name=s.resource_name,
            qualification_summary=s.qualification_summary,
            department=s.department,
            availability_status=s.availability_status,
            average_free_capacity=s.average_free_capacity,
            reason=s.reason,
        )
        for s in suggestions
    ]
