"""Router for work package templates and their skill requirements."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.database import get_session
from app.exceptions import NotFoundError
from app.models.skill import Skill, SkillAttribute
from app.models.user import User
from app.models.work_package_template import (
    WorkPackageTemplate,
    WorkPackageTemplateRequirement,
)
from app.schemas.pagination import PaginatedResponse
from app.schemas.work_package_template import (
    RequirementCreate,
    RequirementResponse,
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)

router = APIRouter(tags=["Templates"])


async def _build_requirement_response(
    session: AsyncSession, req: WorkPackageTemplateRequirement
) -> RequirementResponse:
    """Resolve skill and attribute names for a requirement."""
    skill = await session.get(Skill, req.skill_id)
    skill_name = skill.name if skill else "?"
    attr_name = None
    if req.skill_attribute_id:
        attr = await session.get(SkillAttribute, req.skill_attribute_id)
        attr_name = attr.name if attr else "?"
    return RequirementResponse(
        id=req.id,
        skill_id=req.skill_id,
        skill_name=skill_name,
        skill_attribute_id=req.skill_attribute_id,
        skill_attribute_name=attr_name,
        quantity=req.quantity,
    )


async def _build_template_response(
    session: AsyncSession, template: WorkPackageTemplate
) -> TemplateResponse:
    """Build a full template response with resolved requirements."""
    stmt = select(WorkPackageTemplateRequirement).where(
        WorkPackageTemplateRequirement.template_id == template.id
    )
    result = await session.execute(stmt)
    reqs = list(result.scalars().all())
    requirements = [await _build_requirement_response(session, r) for r in reqs]
    return TemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        requirements=requirements,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.get(
    "/templates",
    response_model=PaginatedResponse[TemplateListResponse],
    summary="List all templates",
)
async def list_templates(
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """All work package templates sorted by name with pagination."""
    total_result = await session.execute(
        select(func.count()).select_from(WorkPackageTemplate)
    )
    total = total_result.scalar_one()

    stmt = (
        select(WorkPackageTemplate)
        .order_by(WorkPackageTemplate.name.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    templates = list(result.scalars().all())

    responses = []
    for t in templates:
        count_stmt = select(func.count()).where(
            WorkPackageTemplateRequirement.template_id == t.id
        )
        count_result = await session.execute(count_stmt)
        count = count_result.scalar_one()
        responses.append(
            TemplateListResponse(
                id=t.id,
                name=t.name,
                description=t.description,
                requirement_count=count,
                created_at=t.created_at,
            )
        )
    return PaginatedResponse(items=responses, total=total, limit=limit, offset=offset)


@router.get(
    "/templates/{template_id}",
    response_model=TemplateResponse,
    summary="Get template with requirements",
)
async def get_template(
    template_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Single template with all its skill requirements."""
    template = await session.get(WorkPackageTemplate, template_id)
    if template is None:
        raise NotFoundError("WorkPackageTemplate", template_id)
    return await _build_template_response(session, template)


@router.post(
    "/templates",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a template",
)
async def create_template(
    data: TemplateCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new work package template with optional requirements.

    Admin only. A template is global — it has no group, so no editor scope can contain
    it, and the skill requirements it carries are inherited by every work package
    created from it.
    """
    check_write_permission(current_user, EntityType.global_definition)
    template = WorkPackageTemplate(
        name=data.name.strip(),
        description=data.description,
    )
    session.add(template)
    await session.flush()

    for req in data.requirements:
        session.add(
            WorkPackageTemplateRequirement(
                template_id=template.id,
                skill_id=req.skill_id,
                skill_attribute_id=req.skill_attribute_id,
                quantity=req.quantity,
            )
        )

    await session.commit()
    return await _build_template_response(session, template)


@router.put(
    "/templates/{template_id}",
    response_model=TemplateResponse,
    summary="Update a template",
)
async def update_template(
    template_id: UUID,
    data: TemplateUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update template name or description.

    Admin only: a template is global and carries no group.
    """
    check_write_permission(current_user, EntityType.global_definition)
    template = await session.get(WorkPackageTemplate, template_id)
    if template is None:
        raise NotFoundError("WorkPackageTemplate", template_id)
    if data.name is not None:
        template.name = data.name.strip()
    if data.description is not None:
        template.description = data.description
    template.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(template)
    await session.commit()
    return await _build_template_response(session, template)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a template",
)
async def delete_template(
    template_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a template and all its requirements.

    Admin only: a template is global and carries no group.
    """
    check_write_permission(current_user, EntityType.global_definition)
    template = await session.get(WorkPackageTemplate, template_id)
    if template is None:
        raise NotFoundError("WorkPackageTemplate", template_id)
    # CASCADE deletes requirements
    await session.delete(template)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Requirements ---


@router.post(
    "/templates/{template_id}/requirements",
    response_model=RequirementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a requirement",
)
async def add_requirement(
    template_id: UUID,
    data: RequirementCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Add a skill requirement to a template.

    Admin only: the requirement belongs to a global template, so it carries no group
    either, and it is inherited by every work package created from that template.
    """
    check_write_permission(current_user, EntityType.global_definition)
    template = await session.get(WorkPackageTemplate, template_id)
    if template is None:
        raise NotFoundError("WorkPackageTemplate", template_id)

    req = WorkPackageTemplateRequirement(
        template_id=template_id,
        skill_id=data.skill_id,
        skill_attribute_id=data.skill_attribute_id,
        quantity=data.quantity,
    )
    session.add(req)
    await session.commit()
    return await _build_requirement_response(session, req)


@router.delete(
    "/templates/{template_id}/requirements/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a requirement",
)
async def remove_requirement(
    template_id: UUID,
    requirement_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Remove a skill requirement from a template.

    Admin only: the requirement belongs to a global template and carries no group.
    """
    check_write_permission(current_user, EntityType.global_definition)
    stmt = select(WorkPackageTemplateRequirement).where(
        WorkPackageTemplateRequirement.id == requirement_id,
        WorkPackageTemplateRequirement.template_id == template_id,
    )
    result = await session.execute(stmt)
    req = result.scalars().first()
    if req is None:
        raise NotFoundError("WorkPackageTemplateRequirement", requirement_id)
    await session.delete(req)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
