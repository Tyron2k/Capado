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


@router.get("/conflicts/check-status")
async def get_conflict_check_status(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Only check health, not administrative maintenance details."""
    from datetime import UTC, datetime, timedelta

    from app.models.organization_settings import OrganizationSettings
    from app.models.scheduled_job_run import JobRunStatus, ScheduledJobRun
    from app.services.conflict_refresh import (
        CONFLICT_CHECK_INTERVAL_MINUTES,
        CONFLICT_CHECK_JOB,
    )

    latest = (
        (
            await session.execute(
                select(ScheduledJobRun)
                .where(ScheduledJobRun.job_name == CONFLICT_CHECK_JOB)
                .order_by(ScheduledJobRun.started_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    success = (
        (
            await session.execute(
                select(ScheduledJobRun)
                .where(
                    ScheduledJobRun.job_name == CONFLICT_CHECK_JOB,
                    ScheduledJobRun.status == JobRunStatus.succeeded,
                )
                .order_by(ScheduledJobRun.finished_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    settings = (
        (await session.execute(select(OrganizationSettings).limit(1))).scalars().first()
    )
    last_checked = success.finished_at if success else None
    now = datetime.now(UTC).replace(tzinfo=None)
    # Allow one polling cycle of scheduling jitter; a crashed running row must
    # eventually show as overdue rather than claiming a check is still healthy.
    stale = last_checked is None or now - last_checked > timedelta(
        minutes=CONFLICT_CHECK_INTERVAL_MINUTES * 2
    )
    if last_checked is None and latest and latest.status == JobRunStatus.running:
        stale = now - latest.started_at > timedelta(
            minutes=CONFLICT_CHECK_INTERVAL_MINUTES * 2
        )
    return {
        "last_checked_at": last_checked.isoformat() + "Z" if last_checked else None,
        "status": latest.status if latest else "never",
        "stale": stale,
        "enabled": settings.scheduler_enabled if settings else True,
        "interval_minutes": CONFLICT_CHECK_INTERVAL_MINUTES,
    }


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
            new_start_at=s.new_start_at,
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
