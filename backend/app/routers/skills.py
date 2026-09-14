"""Router for the unified skill system.

Skills and attributes are global — any authenticated leader can manage them.
Resource skill assignments are scoped:
- Personal: department manager (scope: department)
- Infrastructure: site manager (scope: location)
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.skill import (
    ResourceSearchResult,
    ResourceSkillAssignmentCreate,
    ResourceSkillAssignmentResponse,
    ResourceSkillBoundsUpdate,
    ResourceSkillBulkUpdate,
    SkillAttributeCreate,
    SkillAttributeResponse,
    SkillCreate,
    SkillResponse,
    SkillWithAttributesResponse,
)
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)
from app.services.qualification_update_service import (
    UNSET,
    QualificationUpdate,
    update_resource_skill,
)
from app.services.skill_service import SkillService

router = APIRouter(tags=["Skills"])


# --- Dependencies ---


def get_skill_service(
    session: AsyncSession = Depends(get_session),
) -> SkillService:
    """Dependency injection for SkillService."""
    return SkillService(session)


async def _get_personal_resource_department(
    session: AsyncSession, resource_id: UUID
) -> UUID | None:
    """Look up the group_id of a personal resource."""
    stmt = select(PersonalResource).where(PersonalResource.id == resource_id)
    result = await session.execute(stmt)
    resource = result.scalar_one_or_none()
    if resource is None:
        return None
    return resource.group_id


async def _get_infrastructure_resource_location(
    session: AsyncSession, resource_id: UUID
) -> UUID | None:
    """Look up the group_id of an infrastructure resource."""
    stmt = select(InfrastructureResource).where(
        InfrastructureResource.id == resource_id
    )
    result = await session.execute(stmt)
    resource = result.scalar_one_or_none()
    if resource is None:
        return None
    return resource.group_id


# --- Skill Endpoints (global) ---


@router.get(
    "/skills",
    response_model=PaginatedResponse[SkillResponse],
    summary="Retrieve all skills",
)
async def get_skills(
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    service: SkillService = Depends(get_skill_service),
    _current_user: User = Depends(get_current_user),
):
    """All skills sorted alphabetically with pagination."""
    items, total = await service.get_all_skills(limit=limit, offset=offset)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/skills/with-attributes",
    response_model=PaginatedResponse[SkillWithAttributesResponse],
    summary="Retrieve all skills with their attributes",
)
async def get_skills_with_attributes(
    resource_type: str | None = Query(
        default=None, description="Filter by type: personal or infrastructure"
    ),
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    service: SkillService = Depends(get_skill_service),
    _current_user: User = Depends(get_current_user),
):
    """All skills with nested attributes, optionally filtered by resource type, with pagination."""
    items, total = await service.get_all_skills_with_attributes(
        resource_type=resource_type, limit=limit, offset=offset
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/skills",
    response_model=SkillResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new skill",
)
async def create_skill(
    data: SkillCreate,
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Create a skill.

    Admin only: a skill is global, so there is no scope that could contain it, and
    renaming one redefines every requirement already pointing at it.
    """
    check_write_permission(current_user, EntityType.global_definition)
    return await service.create_skill(name=data.name, resource_type=data.resource_type)


@router.put(
    "/skills/{skill_id}",
    response_model=SkillResponse,
    summary="Update a skill",
)
async def update_skill(
    skill_id: UUID,
    data: SkillCreate,
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Update a skill's name.

    Admin only, and this is the endpoint the restriction exists for. Requirements
    reference the skill by UUID, so a rename breaks nothing — it silently changes what
    every existing requirement MEANS, across every group, with no error raised. It also
    invalidates stored import files, which resolve skills by name.
    """
    check_write_permission(current_user, EntityType.global_definition)
    return await service.update_skill(skill_id=skill_id, name=data.name)


@router.delete(
    "/skills/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a skill",
)
async def delete_skill(
    skill_id: UUID,
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Delete a skill (409 when assignments exist).

    Admin only: a skill is global, so there is no scope that could contain it, and
    renaming one redefines every requirement already pointing at it.
    """
    check_write_permission(current_user, EntityType.global_definition)
    await service.delete_skill(skill_id=skill_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Skill Attribute Endpoints (global, nested under skill) ---


@router.get(
    "/skills/{skill_id}/attributes",
    response_model=list[SkillAttributeResponse],
    summary="Retrieve attributes of a skill",
)
async def get_skill_attributes(
    skill_id: UUID,
    service: SkillService = Depends(get_skill_service),
    _current_user: User = Depends(get_current_user),
):
    """All attributes of a skill sorted alphabetically."""
    return await service.get_skill_attributes(skill_id)


@router.post(
    "/skills/{skill_id}/attributes",
    response_model=SkillAttributeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a skill attribute",
)
async def create_skill_attribute(
    skill_id: UUID,
    data: SkillAttributeCreate,
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Create an attribute for a skill.

    Admin only, for the same reason as the skill itself: an attribute is global and
    carries no group.
    """
    check_write_permission(current_user, EntityType.global_definition)
    return await service.create_skill_attribute(skill_id=skill_id, name=data.name)


@router.put(
    "/skills/attributes/{attribute_id}",
    response_model=SkillAttributeResponse,
    summary="Update a skill attribute",
)
async def update_skill_attribute(
    attribute_id: UUID,
    data: SkillAttributeCreate,
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Update an attribute's name.

    Admin only. Same as renaming a skill: the reference is by UUID, so nothing breaks
    and every requirement pointing at it quietly means something else.
    """
    check_write_permission(current_user, EntityType.global_definition)
    return await service.update_skill_attribute(
        attribute_id=attribute_id, name=data.name
    )


@router.delete(
    "/skills/attributes/{attribute_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a skill attribute",
)
async def delete_skill_attribute(
    attribute_id: UUID,
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Delete a skill attribute (409 when assignments exist).

    Admin only: an attribute is global and carries no group.
    """
    check_write_permission(current_user, EntityType.global_definition)
    await service.delete_skill_attribute(attribute_id=attribute_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Personal Resource Skill Endpoints ---


@router.get(
    "/personal-resources/search",
    response_model=list[ResourceSearchResult],
    summary="Search personal resources by skills",
)
async def search_personal_resources(
    skill_id: UUID | None = Query(default=None, description="Filter by skill ID"),
    skill_attribute_id: UUID | None = Query(
        default=None, description="Filter by skill attribute ID"
    ),
    service: SkillService = Depends(get_skill_service),
    _current_user: User = Depends(get_current_user),
):
    """Search active personal resources by skill or attribute."""
    return await service.search_personal_by_skills(
        skill_id=skill_id, skill_attribute_id=skill_attribute_id
    )


@router.get(
    "/personal-resources/{resource_id}/skills",
    response_model=list[ResourceSkillAssignmentResponse],
    summary="Retrieve skills of a personal resource",
)
async def get_personal_resource_skills(
    resource_id: UUID,
    service: SkillService = Depends(get_skill_service),
    _current_user: User = Depends(get_current_user),
):
    """All skill assignments of a personal resource."""
    return await service.get_personal_resource_skills(resource_id=resource_id)


@router.post(
    "/personal-resources/{resource_id}/skills",
    response_model=ResourceSkillAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a skill to a personal resource",
)
async def add_personal_resource_skill(
    resource_id: UUID,
    data: ResourceSkillAssignmentCreate,
    session: AsyncSession = Depends(get_session),
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Assign a skill attribute to a personal resource (department scope)."""
    group_id = await _get_personal_resource_department(session, resource_id)
    check_write_permission(current_user, EntityType.skill, group_id=group_id)
    return await service.add_personal_resource_skill(
        resource_id=resource_id,
        skill_attribute_id=data.skill_attribute_id,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        level=data.level,
    )


@router.put(
    "/personal-resources/{resource_id}/skills",
    response_model=list[ResourceSkillAssignmentResponse],
    summary="Replace all skills of a personal resource",
)
async def replace_personal_resource_skills(
    resource_id: UUID,
    data: ResourceSkillBulkUpdate,
    session: AsyncSession = Depends(get_session),
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Atomically replace all skill assignments (department scope)."""
    group_id = await _get_personal_resource_department(session, resource_id)
    check_write_permission(current_user, EntityType.skill, group_id=group_id)
    return await service.replace_personal_resource_skills(
        resource_id=resource_id,
        entries=data.entries,
    )


@router.delete(
    "/personal-resources/{resource_id}/skills/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a skill from a personal resource",
)
async def remove_personal_resource_skill(
    resource_id: UUID,
    assignment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Remove a skill assignment (department scope)."""
    group_id = await _get_personal_resource_department(session, resource_id)
    check_write_permission(current_user, EntityType.skill, group_id=group_id)
    await service.remove_personal_resource_skill(
        resource_id=resource_id, assignment_id=assignment_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Infrastructure Resource Skill Endpoints ---


@router.get(
    "/infrastructure-resources/{resource_id}/skills",
    response_model=list[ResourceSkillAssignmentResponse],
    summary="Retrieve skills of an infrastructure resource",
)
async def get_infrastructure_resource_skills(
    resource_id: UUID,
    service: SkillService = Depends(get_skill_service),
    _current_user: User = Depends(get_current_user),
):
    """All skill assignments of an infrastructure resource."""
    return await service.get_infrastructure_resource_skills(resource_id=resource_id)


@router.post(
    "/infrastructure-resources/{resource_id}/skills",
    response_model=ResourceSkillAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a skill to an infrastructure resource",
)
async def add_infrastructure_resource_skill(
    resource_id: UUID,
    data: ResourceSkillAssignmentCreate,
    session: AsyncSession = Depends(get_session),
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Assign a skill attribute to an infrastructure resource (location scope)."""
    group_id = await _get_infrastructure_resource_location(session, resource_id)
    check_write_permission(current_user, EntityType.skill, group_id=group_id)
    return await service.add_infrastructure_resource_skill(
        resource_id=resource_id,
        skill_attribute_id=data.skill_attribute_id,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        level=data.level,
    )


@router.put(
    "/infrastructure-resources/{resource_id}/skills",
    response_model=list[ResourceSkillAssignmentResponse],
    summary="Replace all skills of an infrastructure resource",
)
async def replace_infrastructure_resource_skills(
    resource_id: UUID,
    data: ResourceSkillBulkUpdate,
    session: AsyncSession = Depends(get_session),
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Atomically replace all skill assignments (location scope)."""
    group_id = await _get_infrastructure_resource_location(session, resource_id)
    check_write_permission(current_user, EntityType.skill, group_id=group_id)
    return await service.replace_infrastructure_resource_skills(
        resource_id=resource_id,
        entries=data.entries,
    )


@router.delete(
    "/infrastructure-resources/{resource_id}/skills/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a skill from an infrastructure resource",
)
async def remove_infrastructure_resource_skill(
    resource_id: UUID,
    assignment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: SkillService = Depends(get_skill_service),
    current_user: User = Depends(get_current_user),
):
    """Remove a skill assignment (location scope)."""
    group_id = await _get_infrastructure_resource_location(session, resource_id)
    check_write_permission(current_user, EntityType.skill, group_id=group_id)
    await service.remove_infrastructure_resource_skill(
        resource_id=resource_id, assignment_id=assignment_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _bounds_update(data: ResourceSkillBoundsUpdate) -> QualificationUpdate:
    """Translate the request into an update that distinguishes omitted from cleared.

    Only fields the client actually sent are forwarded; everything else stays UNSET and is
    left as stored. An explicit null therefore clears, and silence leaves alone.
    """
    sent = data.model_fields_set
    return QualificationUpdate(
        valid_from=data.valid_from if "valid_from" in sent else UNSET,
        valid_until=data.valid_until if "valid_until" in sent else UNSET,
        level=data.level if "level" in sent else UNSET,
    )


@router.patch(
    "/personal-resources/{resource_id}/skills/{assignment_id}",
    response_model=ResourceSkillAssignmentResponse,
    summary="Update the validity or level of a held qualification",
)
async def update_personal_resource_skill(
    resource_id: UUID,
    assignment_id: UUID,
    data: ResourceSkillBoundsUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Change expiry or level without losing the assignment (department scope)."""
    group_id = await _get_personal_resource_department(session, resource_id)
    check_write_permission(current_user, EntityType.skill, group_id=group_id)
    return await update_resource_skill(
        session=session,
        resource_id=resource_id,
        assignment_id=assignment_id,
        update=_bounds_update(data),
        kind="personal",
    )


@router.patch(
    "/infrastructure-resources/{resource_id}/skills/{assignment_id}",
    response_model=ResourceSkillAssignmentResponse,
    summary="Update the validity or level of a machine qualification",
)
async def update_infrastructure_resource_skill(
    resource_id: UUID,
    assignment_id: UUID,
    data: ResourceSkillBoundsUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Change expiry or level for an infrastructure qualification (location scope)."""
    group_id = await _get_infrastructure_resource_location(session, resource_id)
    check_write_permission(current_user, EntityType.skill, group_id=group_id)
    return await update_resource_skill(
        session=session,
        resource_id=resource_id,
        assignment_id=assignment_id,
        update=_bounds_update(data),
        kind="infrastructure",
    )
