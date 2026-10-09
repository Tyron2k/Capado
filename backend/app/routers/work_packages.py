"""HTTP routes for work packages; retain existing auth and scopes."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.project import (
    WorkPackageCreate,
    WorkPackageCreateResponse,
    WorkPackageResponse,
    WorkPackageUpdate,
    WorkPackageUpdateResponse,
)
from app.services.partial_update import UNSET
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)
from app.services.work_package_service import WorkPackageService

router = APIRouter()


@router.get(
    "/projects/{project_id}/work-packages",
    response_model=PaginatedResponse[WorkPackageResponse],
    summary="List work packages of a project",
)
async def get_work_packages(
    project_id: UUID,
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve work packages belonging to a project with pagination.

    Args:
        project_id: The UUID of the project.
        limit: Maximum number of items to return.
        offset: Number of items to skip.
        session: Database session.

    Returns:
        Paginated list of work packages for the project.

    """
    service = WorkPackageService(session)
    work_packages, total = await service.get_by_project(
        project_id, limit=limit, offset=offset
    )
    return PaginatedResponse(
        items=work_packages, total=total, limit=limit, offset=offset
    )


@router.post(
    "/projects/{project_id}/work-packages",
    response_model=WorkPackageCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a work package",
)
async def create_work_package(
    project_id: UUID,
    data: WorkPackageCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new work package within a project.

    Args:
        project_id: The UUID of the parent project.
        data: Work package creation data (name, start_date, end_date).
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The created work package with any warnings.

    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageService(session)
    work_package, warnings = await service.create(
        lead_time_working_days=data.lead_time_working_days,
        project_id=project_id,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    return WorkPackageCreateResponse(
        work_package=WorkPackageResponse.model_validate(work_package),
        warnings=warnings,
    )


@router.get(
    "/projects/{project_id}/work-packages/{work_package_id}",
    response_model=WorkPackageResponse,
    summary="Retrieve a single work package",
)
async def get_work_package(
    project_id: UUID,
    work_package_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve a single work package by its ID.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The UUID of the work package.
        session: Database session.

    Returns:
        The work package record.

    Raises:
        NotFoundError: If the work package does not exist.

    """
    service = WorkPackageService(session)
    work_package = await service.get_by_id(work_package_id)
    return work_package


@router.put(
    "/projects/{project_id}/work-packages/{work_package_id}",
    response_model=WorkPackageUpdateResponse,
    summary="Update a work package",
)
async def update_work_package(
    project_id: UUID,
    work_package_id: UUID,
    data: WorkPackageUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update a work package's name or date range.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The UUID of the work package to update.
        data: Fields to update (name, start_date, end_date).
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The updated work package with any warnings.

    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageService(session)
    wp_sent = data.model_fields_set
    work_package, warnings = await service.update(
        lead_time_working_days=data.lead_time_working_days,
        completed_at=data.completed_at if "completed_at" in wp_sent else UNSET,
        work_package_id=work_package_id,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    return WorkPackageUpdateResponse(
        work_package=WorkPackageResponse.model_validate(work_package),
        warnings=warnings,
    )


@router.delete(
    "/projects/{project_id}/work-packages/{work_package_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a work package",
)
async def delete_work_package(
    project_id: UUID,
    work_package_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a work package and cascade-delete its assignments.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The UUID of the work package to delete.
        session: Database session.
        current_user: The authenticated user.

    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageService(session)
    await service.delete(work_package_id)
