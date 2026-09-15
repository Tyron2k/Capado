"""Absences router: CRUD for resource unavailability.

GET    /api/absences?resource_id=...   List absences for a resource
POST   /api/absences                   Create an absence
PUT    /api/absences/{id}              Update an absence
DELETE /api/absences/{id}              Delete an absence
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.user import User
from app.schemas.absence import AbsenceCreate, AbsenceResponse, AbsenceUpdate
from app.schemas.pagination import PaginatedResponse
from app.services.absence_service import AbsenceService
from app.services.conflict_refresh import refresh_resources
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)

router = APIRouter(tags=["Absences"])


async def _get_resource_group_id(
    session: AsyncSession, resource_id: UUID, resource_type: ResourceType | None = None
) -> UUID | None:
    """Look up the group_id of a resource for scope-based permission checks.

    Args:
        session: Database session.
        resource_id: The UUID of the resource.
        resource_type: Optional hint to avoid extra lookups.

    Returns:
        The group_id of the resource, or None if not found.

    """
    if resource_type == ResourceType.personal or resource_type is None:
        stmt = select(PersonalResource).where(PersonalResource.id == resource_id)
        result = await session.execute(stmt)
        personal = result.scalar_one_or_none()
        if personal is not None:
            return personal.group_id

    if resource_type == ResourceType.infrastructure or resource_type is None:
        infra_stmt = select(InfrastructureResource).where(
            InfrastructureResource.id == resource_id
        )
        result = await session.execute(infra_stmt)
        infra = result.scalar_one_or_none()
        if infra is not None:
            return infra.group_id

    return None


@router.get(
    "/absences",
    response_model=PaginatedResponse[AbsenceResponse],
    summary="List absences for a resource",
)
async def list_absences(
    resource_id: UUID = Query(..., description="Resource ID to list absences for"),
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> PaginatedResponse[AbsenceResponse]:
    """List all absences for a given resource with pagination.

    Args:
        resource_id: The UUID of the resource to list absences for.
        limit: Maximum number of items to return.
        offset: Number of items to skip.
        session: Database session.

    Returns:
        Paginated list of absence records for the resource.

    """
    service = AbsenceService(session)
    absences, total = await service.get_for_resource(
        resource_id, limit=limit, offset=offset
    )
    items = [AbsenceResponse.model_validate(a) for a in absences]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/absences",
    response_model=AbsenceResponse,
    status_code=201,
    summary="Create an absence",
)
async def create_absence(
    body: AbsenceCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AbsenceResponse:
    """Create a new absence record for a resource.

    Args:
        body: Absence creation data including resource, dates, and reason.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The newly created absence record.

    """
    group_id = await _get_resource_group_id(
        session, body.resource_id, body.resource_type
    )
    check_write_permission(current_user, EntityType.resource, group_id=group_id)
    service = AbsenceService(session)
    absence = await service.create(
        resource_id=body.resource_id,
        resource_type=body.resource_type,
        reason=body.reason,
        start_date=body.start_date,
        end_date=body.end_date,
        allocation_percent=body.allocation_percent,
        status=body.status,
        note=body.note,
    )
    await session.commit()
    await refresh_resources(session, [absence.resource_id])
    return AbsenceResponse.model_validate(absence)


@router.put(
    "/absences/{absence_id}",
    response_model=AbsenceResponse,
    summary="Update an absence",
)
async def update_absence(
    absence_id: UUID,
    body: AbsenceUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AbsenceResponse:
    """Update an existing absence record.

    Args:
        absence_id: The UUID of the absence to update.
        body: Fields to update (reason, dates, allocation, note).
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The updated absence record.

    """
    service = AbsenceService(session)
    existing = await service.get_by_id(absence_id)
    group_id = await _get_resource_group_id(
        session, existing.resource_id, existing.resource_type
    )
    check_write_permission(current_user, EntityType.resource, group_id=group_id)
    absence = await service.update(
        absence_id=absence_id,
        reason=body.reason,
        start_date=body.start_date,
        end_date=body.end_date,
        allocation_percent=body.allocation_percent,
        status=body.status,
        note=body.note if body.note is not None else ...,
    )
    await session.commit()
    await refresh_resources(session, [absence.resource_id])
    return AbsenceResponse.model_validate(absence)


@router.delete(
    "/absences/{absence_id}",
    status_code=204,
    summary="Delete an absence",
)
async def delete_absence(
    absence_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete an absence record by ID.

    Args:
        absence_id: The UUID of the absence to delete.
        session: Database session.
        current_user: The authenticated user.

    """
    service = AbsenceService(session)
    existing = await service.get_by_id(absence_id)
    group_id = await _get_resource_group_id(
        session, existing.resource_id, existing.resource_type
    )
    check_write_permission(current_user, EntityType.resource, group_id=group_id)
    resource_id = existing.resource_id
    await service.delete(absence_id)
    await session.commit()
    await refresh_resources(session, [resource_id])
