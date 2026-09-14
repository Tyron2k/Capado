"""API router for work package skill requirements.

Provides CRUD for requirements directly on work packages, plus a
convenience endpoint to copy requirements from a template.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.models.project import WorkPackage
from app.models.skill import Skill, SkillAttribute
from app.models.user import User
from app.models.work_package_requirement import (
    RequirementMode,
    WorkPackageRequirement,
)
from app.models.work_package_template import (
    WorkPackageTemplate,
    WorkPackageTemplateRequirement,
)
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)

router = APIRouter()


# --- Schemas ---


class WorkPackageRequirementCreate(BaseModel):
    """Request body for adding a requirement to a work package."""

    skill_id: UUID
    skill_attribute_id: UUID | None = None
    quantity: int = Field(default=1, ge=1)
    requirement_mode: RequirementMode = RequirementMode.headcount
    min_allocation_percent: float = Field(default=100.0, gt=0, le=100)


class WorkPackageRequirementResponse(BaseModel):
    """Response schema for a work package requirement with resolved names."""

    id: UUID
    skill_id: UUID
    skill_name: str
    skill_attribute_id: UUID | None
    skill_attribute_name: str | None
    quantity: int
    requirement_mode: RequirementMode
    min_allocation_percent: float

    model_config = {"from_attributes": True}


# --- Endpoints ---


@router.get(
    "/work-packages/{wp_id}/requirements",
    response_model=list[WorkPackageRequirementResponse],
    summary="List requirements of a work package",
)
async def list_requirements(
    wp_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> list[WorkPackageRequirementResponse]:
    """List all skill requirements for a work package.

    Args:
        wp_id: The UUID of the work package.
        session: Database session.

    Returns:
        List of skill requirements with resolved names.

    Raises:
        HTTPException: 404 if the work package does not exist.

    """
    wp = await session.get(WorkPackage, wp_id)
    if wp is None:
        raise HTTPException(status_code=404, detail="Work package not found")

    stmt = select(WorkPackageRequirement).where(
        WorkPackageRequirement.work_package_id == wp_id
    )
    result = await session.execute(stmt)
    requirements = list(result.scalars().all())

    responses: list[WorkPackageRequirementResponse] = []
    for req in requirements:
        skill = await session.get(Skill, req.skill_id)
        skill_name = skill.name if skill else "—"
        attr_name: str | None = None
        if req.skill_attribute_id:
            attr = await session.get(SkillAttribute, req.skill_attribute_id)
            attr_name = attr.name if attr else None
        responses.append(
            WorkPackageRequirementResponse(
                id=req.id,
                skill_id=req.skill_id,
                skill_name=skill_name,
                skill_attribute_id=req.skill_attribute_id,
                skill_attribute_name=attr_name,
                quantity=req.quantity,
                requirement_mode=req.requirement_mode,
                min_allocation_percent=req.min_allocation_percent,
            )
        )

    return responses


@router.post(
    "/work-packages/{wp_id}/requirements",
    response_model=WorkPackageRequirementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a requirement to a work package",
)
async def add_requirement(
    wp_id: UUID,
    data: WorkPackageRequirementCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkPackageRequirementResponse:
    """Add a skill requirement to a work package.

    Args:
        wp_id: The UUID of the work package.
        data: Requirement data (skill_id, optional attribute, quantity).
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The created requirement with resolved skill names.

    Raises:
        HTTPException: 404 if the work package does not exist.
        HTTPException: 400 if the skill or attribute does not exist.

    """
    wp = await session.get(WorkPackage, wp_id)
    if wp is None:
        raise HTTPException(status_code=404, detail="Work package not found")

    check_write_permission(
        current_user, EntityType.work_package, project_id=wp.project_id
    )

    # Validate skill exists
    skill = await session.get(Skill, data.skill_id)
    if skill is None:
        raise HTTPException(status_code=400, detail="Skill not found")

    # Validate attribute exists (if provided)
    attr_name: str | None = None
    if data.skill_attribute_id:
        attr = await session.get(SkillAttribute, data.skill_attribute_id)
        if attr is None:
            raise HTTPException(status_code=400, detail="Skill attribute not found")
        attr_name = attr.name

    requirement = WorkPackageRequirement(
        work_package_id=wp_id,
        skill_id=data.skill_id,
        skill_attribute_id=data.skill_attribute_id,
        quantity=data.quantity,
        requirement_mode=data.requirement_mode,
        min_allocation_percent=data.min_allocation_percent,
    )
    session.add(requirement)
    await session.commit()

    return WorkPackageRequirementResponse(
        id=requirement.id,
        skill_id=requirement.skill_id,
        skill_name=skill.name,
        skill_attribute_id=requirement.skill_attribute_id,
        skill_attribute_name=attr_name,
        quantity=requirement.quantity,
        requirement_mode=requirement.requirement_mode,
        min_allocation_percent=requirement.min_allocation_percent,
    )


@router.delete(
    "/work-packages/{wp_id}/requirements/{req_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a requirement from a work package",
)
async def remove_requirement(
    wp_id: UUID,
    req_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> None:
    """Remove a skill requirement from a work package.

    Args:
        wp_id: The UUID of the work package.
        req_id: The UUID of the requirement to remove.
        session: Database session.
        current_user: The authenticated user.

    Raises:
        HTTPException: 404 if the requirement does not exist.

    """
    wp = await session.get(WorkPackage, wp_id)
    if wp is None:
        raise HTTPException(status_code=404, detail="Work package not found")

    check_write_permission(
        current_user, EntityType.work_package, project_id=wp.project_id
    )

    stmt = select(WorkPackageRequirement).where(
        WorkPackageRequirement.id == req_id,
        WorkPackageRequirement.work_package_id == wp_id,
    )
    result = await session.execute(stmt)
    requirement = result.scalar_one_or_none()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")

    await session.delete(requirement)
    await session.commit()


@router.post(
    "/work-packages/{wp_id}/copy-from-template/{template_id}",
    response_model=list[WorkPackageRequirementResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Copy requirements from a template",
)
async def copy_from_template(
    wp_id: UUID,
    template_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[WorkPackageRequirementResponse]:
    """Copy all requirements from a template to a work package.

    Appends template requirements without removing existing ones.

    Args:
        wp_id: The UUID of the target work package.
        template_id: The UUID of the source template.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        List of newly created requirements with resolved skill names.

    Raises:
        HTTPException: 404 if the work package or template does not exist.

    """
    wp = await session.get(WorkPackage, wp_id)
    if wp is None:
        raise HTTPException(status_code=404, detail="Work package not found")

    check_write_permission(
        current_user, EntityType.work_package, project_id=wp.project_id
    )

    template = await session.get(WorkPackageTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Load template requirements
    stmt = select(WorkPackageTemplateRequirement).where(
        WorkPackageTemplateRequirement.template_id == template_id
    )
    result = await session.execute(stmt)
    template_reqs = list(result.scalars().all())

    created: list[WorkPackageRequirementResponse] = []
    for tr in template_reqs:
        req = WorkPackageRequirement(
            work_package_id=wp_id,
            skill_id=tr.skill_id,
            skill_attribute_id=tr.skill_attribute_id,
            quantity=tr.quantity,
            requirement_mode=tr.requirement_mode,
            min_allocation_percent=tr.min_allocation_percent,
        )
        session.add(req)
        await session.flush()

        skill = await session.get(Skill, req.skill_id)
        skill_name = skill.name if skill else "—"
        attr_name: str | None = None
        if req.skill_attribute_id:
            attr = await session.get(SkillAttribute, req.skill_attribute_id)
            attr_name = attr.name if attr else None

        created.append(
            WorkPackageRequirementResponse(
                id=req.id,
                skill_id=req.skill_id,
                skill_name=skill_name,
                skill_attribute_id=req.skill_attribute_id,
                skill_attribute_name=attr_name,
                quantity=req.quantity,
                requirement_mode=req.requirement_mode,
                min_allocation_percent=req.min_allocation_percent,
            )
        )

    await session.commit()
    return created
