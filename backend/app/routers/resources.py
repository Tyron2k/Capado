"""Resources router: API endpoints for resource groups, personal and infrastructure resources.

Applies RBAC permission checks on all write endpoints using the unified
group-based scope model.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.database import get_session
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.resource_group import ResourceGroup
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.resource import (
    ErasureResponse,
    InfrastructureResourceCreate,
    InfrastructureResourceResponse,
    InfrastructureResourceUpdate,
    PersonalResourceCreate,
    PersonalResourceResponse,
    PersonalResourceUpdate,
    ResourceGroupCreate,
    ResourceGroupResponse,
    ResourceGroupUpdate,
    ResourceListItemResponse,
)
from app.services import resource_names, resource_service
from app.services.hierarchy_service import (
    get_infrastructure_tree,
    get_personal_tree,
)
from app.services.partial_update import UNSET
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
    require_admin,
)

router = APIRouter()


# --- Resource Groups ---


@router.get(
    "/resource-groups",
    response_model=PaginatedResponse[ResourceGroupResponse],
    summary="List resource groups, optionally filtered by resource type",
)
async def get_groups(
    resource_type: str | None = Query(
        default=None,
        description="Filter by resource type: 'personal' or 'infrastructure'",
    ),
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Resource groups sorted alphabetically with optional type filter and pagination."""
    base_filter = select(ResourceGroup)
    count_filter = select(func.count()).select_from(ResourceGroup)

    if resource_type is not None:
        base_filter = base_filter.where(ResourceGroup.resource_type == resource_type)
        count_filter = count_filter.where(ResourceGroup.resource_type == resource_type)

    total_result = await session.execute(count_filter)
    total = total_result.scalar_one()

    stmt = base_filter.order_by(ResourceGroup.name.asc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    items = list(result.scalars().all())
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/resource-groups",
    response_model=ResourceGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a resource group",
)
async def create_group(
    data: ResourceGroupCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new resource group scoped to a resource type."""
    check_write_permission(current_user, EntityType.resource, group_id=None)
    group = ResourceGroup(
        name=data.name.strip(),
        resource_type=data.resource_type,
        parent_id=data.parent_id,
    )
    session.add(group)
    await session.commit()
    return group


@router.put(
    "/resource-groups/{group_id}",
    response_model=ResourceGroupResponse,
    summary="Update a resource group",
)
async def update_group(
    group_id: UUID,
    data: ResourceGroupUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update a resource group's name or its parent.

    The parent is not cosmetic: a work-profile binding on the parent group is inherited by this one.
    """
    check_write_permission(current_user, EntityType.resource, group_id=group_id)
    group = await session.get(ResourceGroup, group_id)
    if group is None:
        from app.exceptions import NotFoundError

        raise NotFoundError("ResourceGroup", group_id)
    if data.name is not None:
        group.name = data.name.strip()
    if data.parent_id is not None:
        group.parent_id = data.parent_id
    session.add(group)
    await session.commit()
    return group


@router.delete(
    "/resource-groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a resource group",
)
async def delete_group(
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a resource group (only if no resources reference it)."""
    check_write_permission(current_user, EntityType.resource, group_id=group_id)
    group = await session.get(ResourceGroup, group_id)
    if group is None:
        from app.exceptions import NotFoundError

        raise NotFoundError("ResourceGroup", group_id)

    # Check if any resources still reference this group
    from sqlalchemy import func as sa_func

    personal_count = (
        await session.execute(
            select(sa_func.count()).where(PersonalResource.group_id == group_id)
        )
    ).scalar_one()
    infra_count = (
        await session.execute(
            select(sa_func.count()).where(InfrastructureResource.group_id == group_id)
        )
    ).scalar_one()
    if personal_count + infra_count > 0:
        from app.exceptions import ConflictError

        raise ConflictError(
            f"Cannot delete: {personal_count + infra_count} resources still belong to this group."
        )

    await session.delete(group)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Personal Resources ---


@router.get(
    "/resources/personal/tree",
    response_model=list[ResourceListItemResponse],
    summary="Retrieve personal resources as flat list with group names",
)
async def get_personal_tree_endpoint(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Complete personal resource list with group names and conflict counts."""
    return await get_personal_tree(session)


@router.get(
    "/resources/personal",
    response_model=PaginatedResponse[PersonalResourceResponse],
    summary="Retrieve all active personal resources",
)
async def get_personal_resources(
    group_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """List of all active personal resources, optionally filtered by group, with pagination."""
    resources, total = await resource_service.get_all_personal_resources(
        session, group_id=group_id, limit=limit, offset=offset
    )
    items = await resource_names.to_responses(session, resources)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/resources/personal",
    response_model=PersonalResourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new personal resource",
)
async def create_personal_resource(
    data: PersonalResourceCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create and persist a personal resource."""
    check_write_permission(current_user, EntityType.resource, group_id=data.group_id)
    resource = await resource_service.create_personal_resource(
        session=session,
        name=data.name,
        group_id=data.group_id,
        site_id=data.site_id,
    )
    return await resource_names.to_response(session, resource)


@router.get(
    "/resources/personal/{resource_id}",
    response_model=PersonalResourceResponse,
    summary="Retrieve a single personal resource",
)
async def get_personal_resource(
    resource_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve a single resource by ID."""
    resource = await resource_service.get_personal_resource_by_id(session, resource_id)
    return await resource_names.to_response(session, resource)


@router.put(
    "/resources/personal/{resource_id}",
    response_model=PersonalResourceResponse,
    summary="Update a personal resource",
)
async def update_personal_resource(
    resource_id: UUID,
    data: PersonalResourceUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Persist changed data."""
    existing = await resource_service.get_personal_resource_by_id(session, resource_id)
    check_write_permission(
        current_user, EntityType.resource, group_id=existing.group_id
    )
    sent = data.model_dump(exclude_unset=True)
    resource = await resource_service.update_personal_resource(
        session=session,
        resource_id=resource_id,
        name=data.name,
        group_id=data.group_id,
        site_id=data.site_id if "site_id" in sent else UNSET,
    )
    return await resource_names.to_response(session, resource)


@router.delete(
    "/resources/personal/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a personal resource (soft delete)",
)
async def delete_personal_resource(
    resource_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Mark resource as inactive."""
    existing = await resource_service.get_personal_resource_by_id(session, resource_id)
    check_write_permission(
        current_user, EntityType.resource, group_id=existing.group_id
    )
    await resource_service.soft_delete_personal_resource(session, resource_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/resources/personal/{resource_id}/erase",
    response_model=ErasureResponse,
    summary="Erase a person and all their planning data (irreversible)",
)
async def erase_personal_resource(
    resource_id: UUID,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    """Permanently delete a person and every planning row referring to them.

    ADMIN ONLY, and not by analogy with the other admin-only endpoints. An editor scoped to a group
    may deactivate someone in it, which is reversible; this is not, it reaches rows outside that
    group's scope (the audit trail), and it is the technical execution of a legal request. None of
    that is a group-scoped decision.

    A SEPARATE ENDPOINT rather than a flag on the deactivate route. "Stop scheduling this person" and
    "erase this person" are different intents with different consequences, and a boolean would let the
    irreversible one be reached by a typo in a query string.

    Returns per-table counts rather than 204. The operator answering an erasure request needs to
    evidence what was removed, and a bare 204 gives them nothing to file.
    """
    return await resource_service.erase_personal_resource(session, resource_id)


# --- Infrastructure Resources ---


@router.get(
    "/resources/infrastructure/tree",
    response_model=list[ResourceListItemResponse],
    summary="Retrieve infrastructure resources as flat list with group names",
)
async def get_infrastructure_tree_endpoint(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Complete infrastructure resource list with group names and conflict counts."""
    return await get_infrastructure_tree(session)


@router.get(
    "/resources/infrastructure",
    response_model=PaginatedResponse[InfrastructureResourceResponse],
    summary="Retrieve all active infrastructure resources",
)
async def get_infrastructure_resources(
    group_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """List active resources, optionally filtered by group, with pagination."""
    resources, total = await resource_service.get_all_infrastructure_resources(
        session, group_id=group_id, limit=limit, offset=offset
    )
    items = await resource_names.to_responses(session, resources)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/resources/infrastructure",
    response_model=InfrastructureResourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new infrastructure resource",
)
async def create_infrastructure_resource(
    data: InfrastructureResourceCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create and persist an infrastructure resource."""
    check_write_permission(current_user, EntityType.resource, group_id=data.group_id)
    resource = await resource_service.create_infrastructure_resource(
        session=session,
        name=data.name,
        group_id=data.group_id,
        site_id=data.site_id,
    )
    return await resource_names.to_response(session, resource)


@router.get(
    "/resources/infrastructure/{resource_id}",
    response_model=InfrastructureResourceResponse,
    summary="Retrieve a single infrastructure resource",
)
async def get_infrastructure_resource(
    resource_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve a single resource by ID."""
    resource = await resource_service.get_infrastructure_resource_by_id(
        session, resource_id
    )
    return await resource_names.to_response(session, resource)


@router.put(
    "/resources/infrastructure/{resource_id}",
    response_model=InfrastructureResourceResponse,
    summary="Update an infrastructure resource",
)
async def update_infrastructure_resource(
    resource_id: UUID,
    data: InfrastructureResourceUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Persist changed data."""
    existing = await resource_service.get_infrastructure_resource_by_id(
        session, resource_id
    )
    check_write_permission(
        current_user, EntityType.resource, group_id=existing.group_id
    )
    sent = data.model_dump(exclude_unset=True)
    resource = await resource_service.update_infrastructure_resource(
        session=session,
        resource_id=resource_id,
        name=data.name,
        group_id=data.group_id,
        site_id=data.site_id if "site_id" in sent else UNSET,
    )
    return await resource_names.to_response(session, resource)


@router.delete(
    "/resources/infrastructure/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate an infrastructure resource (soft delete)",
)
async def delete_infrastructure_resource(
    resource_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Mark resource as inactive."""
    existing = await resource_service.get_infrastructure_resource_by_id(
        session, resource_id
    )
    check_write_permission(
        current_user, EntityType.resource, group_id=existing.group_id
    )
    await resource_service.soft_delete_infrastructure_resource(session, resource_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
