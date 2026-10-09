"""HTTP routes for work package dependencies; retain existing auth and scopes."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.project import (
    WorkPackageDependenciesResponse,
    WorkPackageDependencyCreate,
    WorkPackageDependencyResponse,
    WorkPackageDependencyUpdate,
)
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)
from app.services.work_package_dependency_service import (
    WorkPackageDependencyService,
)

router = APIRouter()


@router.get(
    "/projects/{project_id}/work-packages/{work_package_id}/dependencies",
    response_model=WorkPackageDependenciesResponse,
    summary="List dependencies of a work package",
)
async def get_work_package_dependencies(
    project_id: UUID,
    work_package_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return links in both directions for one work package.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The work package to inspect.
        session: Database session.
        _current_user: Authenticated user.

    Returns:
        Predecessors and successors as separate lists.
    """
    service = WorkPackageDependencyService(session)
    predecessors, successors = await service.list_for_work_package(work_package_id)
    return WorkPackageDependenciesResponse(
        predecessors=[
            WorkPackageDependencyResponse.model_validate(d) for d in predecessors
        ],
        successors=[
            WorkPackageDependencyResponse.model_validate(d) for d in successors
        ],
    )


@router.post(
    "/projects/{project_id}/work-packages/{work_package_id}/dependencies",
    response_model=WorkPackageDependencyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a dependency to a work package",
)
async def create_work_package_dependency(
    project_id: UUID,
    work_package_id: UUID,
    data: WorkPackageDependencyCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Record that another work package has to finish before this one starts.

    A link that would close a cycle is refused: "A after B after A" cannot be scheduled
    at all. Dates that merely contradict the link are accepted and reported as a
    warning, because that is an ordinary intermediate state on the way to a fixed plan.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The successor — the package that waits.
        data: The predecessor and the lag in working days.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        The created link.
    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageDependencyService(session)
    return await service.create(
        predecessor_id=data.predecessor_id,
        successor_id=work_package_id,
        lag_working_days=data.lag_working_days,
    )


@router.put(
    "/projects/{project_id}/work-packages/{work_package_id}/dependencies/{dependency_id}",
    response_model=WorkPackageDependencyResponse,
    summary="Change the lag on a dependency",
)
async def update_work_package_dependency(
    project_id: UUID,
    work_package_id: UUID,
    dependency_id: UUID,
    data: WorkPackageDependencyUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Change the waiting time between two linked work packages.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The successor the link hangs on.
        dependency_id: The link to change.
        data: The new lag in working days.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        The updated link.
    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageDependencyService(session)
    return await service.update_lag(dependency_id, data.lag_working_days)


@router.delete(
    "/projects/{project_id}/work-packages/{work_package_id}/dependencies/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a dependency",
)
async def delete_work_package_dependency(
    project_id: UUID,
    work_package_id: UUID,
    dependency_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Remove a link. Neither work package is touched.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The successor the link hangs on.
        dependency_id: The link to remove.
        session: Database session.
        current_user: Authenticated user.
    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageDependencyService(session)
    await service.delete(dependency_id)
