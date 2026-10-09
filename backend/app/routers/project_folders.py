"""HTTP routes for project folders; retain existing auth and scopes."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.project import (
    ProjectFolderCreate,
    ProjectFolderDeleteResponse,
    ProjectFolderResponse,
    ProjectFolderUpdate,
)
from app.services.partial_update import UNSET
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)
from app.services.project_folder_service import ProjectFolderService

router = APIRouter()


@router.get(
    "/project-folders",
    response_model=list[ProjectFolderResponse],
    summary="List all project folders",
)
async def get_project_folders(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return every folder, ordered by position then name.

    Unpaginated: folders are a navigation aid maintained by hand, so the count stays
    small, and a tree delivered one page at a time cannot be rendered as a tree.

    Args:
        session: Database session.
        _current_user: Authenticated user.

    Returns:
        All folders in a stable order.
    """
    return await ProjectFolderService(session).get_all()


@router.post(
    "/project-folders",
    response_model=ProjectFolderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project folder",
)
async def create_project_folder(
    data: ProjectFolderCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a folder, optionally inside another.

    Args:
        data: Name, optional parent, optional position.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        The created folder.
    """
    check_write_permission(current_user, EntityType.project)
    return await ProjectFolderService(session).create(
        name=data.name,
        parent_id=data.parent_id,
        position=data.position,
        external_ref=data.external_ref,
        customer_id=data.customer_id,
    )


@router.put(
    "/project-folders/{folder_id}",
    response_model=ProjectFolderResponse,
    summary="Update a project folder",
)
async def update_project_folder(
    folder_id: UUID,
    data: ProjectFolderUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Rename, move, or reorder a folder.

    Sending ``parent_id`` as null moves it to the top level; omitting the field
    leaves the parent unchanged. A move that would place a folder inside its own
    subtree is refused.

    Args:
        folder_id: The folder to update.
        data: Fields to change.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        The updated folder.
    """
    check_write_permission(current_user, EntityType.project)
    sent = data.model_fields_set
    return await ProjectFolderService(session).update(
        folder_id=folder_id,
        name=data.name,
        parent_id=data.parent_id if "parent_id" in sent else UNSET,
        position=data.position,
        external_ref=data.external_ref if "external_ref" in sent else UNSET,
        customer_id=data.customer_id if "customer_id" in sent else UNSET,
    )


@router.delete(
    "/project-folders/{folder_id}",
    response_model=ProjectFolderDeleteResponse,
    summary="Delete a project folder",
)
async def delete_project_folder(
    folder_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a folder without deleting anything that was in it.

    Projects inside become unfiled and sub-folders move up one level. Nothing is
    cascaded, because a project carries work packages and assignments and removing a
    grouping must never be able to remove a plan.

    Args:
        folder_id: The folder to delete.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        How many projects were unfiled and how many sub-folders moved up.
    """
    check_write_permission(current_user, EntityType.project)
    unfiled, moved = await ProjectFolderService(session).delete(folder_id)
    return ProjectFolderDeleteResponse(projects_unfiled=unfiled, subfolders_moved=moved)
