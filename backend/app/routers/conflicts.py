"""Router for conflict endpoints.

- GET /conflicts                        — All active conflicts
- GET /conflicts/{conflict_id}          — Single conflict with details
- GET /conflicts/resource/{resource_id} — Conflicts for a specific resource
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.database import get_session
from app.exceptions import NotFoundError
from app.models.conflict import Conflict
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.user import User
from app.schemas.capacity import ConflictResponse
from app.schemas.conflict_suggestion import ConflictSuggestionResponse
from app.schemas.pagination import PaginatedResponse
from app.services.conflict_enrichment import enrich_conflict, enrich_conflicts_batch
from app.services.conflict_suggestion_service import ConflictSuggestionService
from app.services.permissions import get_current_user

router = APIRouter(tags=["Conflicts"])


@router.get(
    "/conflicts/{conflict_id}/suggestions",
    response_model=list[ConflictSuggestionResponse],
    summary="Get resolution suggestions for a conflict",
)
async def get_conflict_suggestions(
    conflict_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> list[ConflictSuggestionResponse]:
    """Return resolution suggestions for a specific conflict.

    Args:
        conflict_id: The UUID of the conflict.
        session: Database session.

    Returns:
        List of suggested resolutions (shift, reduce, swap).

    """
    service = ConflictSuggestionService(session)
    suggestions = await service.get_suggestions(conflict_id)
    return [
        ConflictSuggestionResponse(
            type=s.type,
            assignment_id=s.assignment_id,
            description=s.description,
            shift_days=s.shift_days,
            new_allocation_percent=s.new_allocation_percent,
            target_resource_id=s.target_resource_id,
            target_resource_name=s.target_resource_name,
        )
        for s in suggestions
    ]


@router.get(
    "/conflicts/{conflict_id}",
    response_model=ConflictResponse,
    summary="Retrieve a single conflict",
)
async def get_conflict_by_id(
    conflict_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> ConflictResponse:
    """Return a single conflict entity with enriched details.

    Args:
        conflict_id: The UUID of the conflict.
        session: Database session.

    Returns:
        The enriched conflict record.

    Raises:
        NotFoundError: If the conflict does not exist.

    """
    conflict = await session.get(Conflict, conflict_id)
    if conflict is None:
        raise NotFoundError("Conflict", conflict_id)
    return await enrich_conflict(session, conflict)


@router.get(
    "/conflicts",
    response_model=PaginatedResponse[ConflictResponse],
    summary="List all active conflicts",
)
async def get_all_conflicts(
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return all active conflicts with pagination and enriched resource/assignment data.

    Args:
        limit: Maximum number of items to return.
        offset: Number of items to skip.
        session: Database session.

    Returns:
        Paginated list of enriched conflicts with total count.

    """
    total_result = await session.execute(select(func.count()).select_from(Conflict))
    total = total_result.scalar_one()

    statement = select(Conflict).offset(offset).limit(limit)
    result = await session.execute(statement)
    conflicts = list(result.scalars().all())
    enriched = await enrich_conflicts_batch(session, conflicts)
    return PaginatedResponse(items=enriched, total=total, limit=limit, offset=offset)


@router.get(
    "/conflicts/resource/{resource_id}",
    response_model=PaginatedResponse[ConflictResponse],
    summary="List conflicts for a resource",
)
async def get_conflicts_for_resource(
    resource_id: UUID,
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return all active conflicts for a specific resource with pagination.

    Args:
        resource_id: The UUID of the resource.
        limit: Maximum number of items to return.
        offset: Number of items to skip.
        session: Database session.

    Returns:
        Paginated list of enriched conflicts for the resource with total count.

    Raises:
        NotFoundError: If the resource does not exist.

    """
    personal = await session.get(PersonalResource, resource_id)
    infrastructure = await session.get(InfrastructureResource, resource_id)
    if personal is None and infrastructure is None:
        raise NotFoundError("Resource", resource_id)

    base_filter = select(Conflict).where(Conflict.resource_id == resource_id)

    total_result = await session.execute(
        select(func.count()).select_from(base_filter.subquery())
    )
    total = total_result.scalar_one()

    statement = base_filter.offset(offset).limit(limit)
    result = await session.execute(statement)
    conflicts = list(result.scalars().all())
    enriched = await enrich_conflicts_batch(session, conflicts)
    return PaginatedResponse(items=enriched, total=total, limit=limit, offset=offset)
