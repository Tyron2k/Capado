"""Project CRUD routes and registration of the focused project HTTP areas."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.routers import (
    project_analysis,
    project_folders,
    work_package_dependencies,
    work_packages,
)
from app.schemas.pagination import PaginatedResponse
from app.schemas.project import (
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.partial_update import UNSET
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)
from app.services.project_enrichment import enrich_project, enrich_projects
from app.services.project_service import ProjectService

router = APIRouter()
# Static /projects/overview must precede /projects/{project_id}.
router.include_router(project_analysis.router)
router.include_router(project_folders.router)


def _parse_folder(value: str | None) -> UUID | Literal["unfiled"] | None:
    """Turn the folder_id query parameter into a filter.

    Accepts a folder id, the literal "unfiled", or nothing. A malformed id is a client
    error rather than a silently ignored filter — quietly returning the unfiltered
    list would look like the folder simply being empty.
    """
    if value is None:
        return None
    if value.strip().lower() == "unfiled":
        return "unfiled"
    try:
        return UUID(value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="folder_id must be a folder id or the literal 'unfiled'.",
        ) from exc


@router.get(
    "/projects",
    response_model=PaginatedResponse[ProjectResponse],
    summary="List all projects",
)
async def get_projects(
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    folder_id: str | None = Query(
        default=None,
        description=(
            "A folder id to list the projects filed under it, or 'unfiled' for "
            "projects in no folder. Omit for everything."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve projects with pagination.

    Args:
        limit: Maximum number of items to return.
        offset: Number of items to skip.
        folder_id: A folder id to list the projects filed under it, or "unfiled" for
            projects in no folder. Omitted returns everything.
        session: Database session.

    Returns:
        Paginated list of projects matching the filter.

    """
    service = ProjectService(session)
    projects, total = await service.get_all(
        limit=limit, offset=offset, folder_filter=_parse_folder(folder_id)
    )
    # Enriched rather than returned raw: the resolved customer is a computed field,
    # and a raw ORM object would serialise it as empty.
    return PaginatedResponse(
        items=await enrich_projects(session, projects),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
)
async def create_project(
    data: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new project.

    Admins can always create projects. Editors with at least one project
    in their scope can also create new projects — the new project is
    automatically added to their scope_project_ids.

    Args:
        data: Project creation data.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The newly created project.

    Raises:
        HTTPException: 403 if the user is a viewer or an editor without
            any project scope.

    """
    from app.models.user import UserRole

    if current_user.role == UserRole.viewer:
        check_write_permission(current_user, EntityType.project, project_id=None)

    if current_user.role == UserRole.editor and not current_user.scope_project_ids:
        # Editors need at least one project in their scope to create new ones
        check_write_permission(current_user, EntityType.project, project_id=None)

    service = ProjectService(session)
    project = await service.create(
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
        folder_id=data.folder_id,
        position=data.position,
        external_ref=data.external_ref,
        committed_delivery_date=data.committed_delivery_date,
        customer_id=data.customer_id,
        priority=data.priority,
    )

    # Auto-scope: add the new project to the editor's scope_project_ids
    if current_user.role == UserRole.editor:
        existing_ids = list(current_user.scope_project_ids or [])
        existing_ids.append(project.id)
        current_user.scope_project_ids = existing_ids
        session.add(current_user)
        await session.commit()

    return await enrich_project(session, project)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Retrieve a single project",
)
async def get_project(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve a single project by its ID.

    Args:
        project_id: The UUID of the project.
        session: Database session.

    Returns:
        The project record.

    Raises:
        NotFoundError: If the project does not exist.

    """
    service = ProjectService(session)
    project = await service.get_by_id(project_id)
    return await enrich_project(session, project)


@router.put(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Update a project",
)
async def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update a project's name or date range.

    Args:
        project_id: The UUID of the project to update.
        data: Fields to update (name, start_date, end_date).
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The updated project record.

    """
    check_write_permission(current_user, EntityType.project, project_id=project_id)
    service = ProjectService(session)
    # Only fields the client actually SENT are forwarded. folder_id and external_ref
    # are nullable, so an explicit null has to mean "take out of the folder" / "clear
    # it" — which a plain None default cannot express.
    sent = data.model_fields_set
    project = await service.update(
        project_id=project_id,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
        folder_id=data.folder_id if "folder_id" in sent else UNSET,
        position=data.position,
        external_ref=data.external_ref if "external_ref" in sent else UNSET,
        committed_delivery_date=(
            data.committed_delivery_date if "committed_delivery_date" in sent else UNSET
        ),
        customer_id=data.customer_id if "customer_id" in sent else UNSET,
        priority=data.priority,
    )
    return await enrich_project(session, project)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
)
async def delete_project(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a project and its associated work packages.

    Args:
        project_id: The UUID of the project to delete.
        session: Database session.
        current_user: The authenticated user.

    """
    check_write_permission(current_user, EntityType.project, project_id=project_id)
    service = ProjectService(session)
    await service.delete(project_id)


router.include_router(work_packages.router)
router.include_router(work_package_dependencies.router)
