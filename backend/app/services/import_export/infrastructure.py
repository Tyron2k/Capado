"""Export and import routines for infrastructure resources.

Provides flat and skill-matrix Excel exports, a CSV export, and an importer
that creates or updates infrastructure resources together with optional
inline skill assignments.
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.resource import InfrastructureResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.skill import InfrastructureResourceSkill, Skill, SkillAttribute

from .common import (
    ImportResult,
    _build_flat_resource_csv,
    _build_flat_resource_xlsx,
    _build_skill_matrix_xlsx,
    _import_resources,
    _load_matrix_data,
)


async def export_infrastructure_xlsx(session: AsyncSession) -> bytes:
    """Export active infrastructure resources with skill assignments as Excel."""
    rows = await _load_infra_export_rows(session)
    return await asyncio.to_thread(_build_flat_resource_xlsx, rows, "Infrastructure")


async def export_infrastructure_matrix_xlsx(session: AsyncSession) -> bytes:
    """Export active infrastructure resources as a skill matrix Excel file."""
    data = await _load_matrix_data(session, resource_type="infrastructure")
    return await asyncio.to_thread(_build_skill_matrix_xlsx, data, "Infrastructure")


async def export_infrastructure_csv(session: AsyncSession) -> str:
    """Export active infrastructure resources with skill assignments as CSV."""
    rows = await _load_infra_export_rows(session)
    return await asyncio.to_thread(_build_flat_resource_csv, rows)


async def import_infrastructure(
    session: AsyncSession, rows: list[tuple]
) -> ImportResult:
    """Import infrastructure resources with optional skill assignments.

    Each row must have at least Name and Group. Optionally, Skill and
    Attribute columns can be provided to create skill assignments inline.
    Skills and SkillAttributes are auto-created if they don't exist.

    Args:
        session: Database session.
        rows: Parsed rows including header.

    Returns:
        Import result with counts.

    """
    return await _import_resources(
        session,
        rows,
        resource_model=InfrastructureResource,
        skill_model=InfrastructureResourceSkill,
        resource_type=ResourceType.infrastructure,
    )


async def _load_infra_export_rows(
    session: AsyncSession,
) -> list[tuple[str, str, str | None, str | None, str | None]]:
    """Load infrastructure resources with group and skill assignments for export.

    A resource with no skills gets one row with empty Skill/Attribute.
    A resource with N skill assignments gets N rows (Name and Group repeated).
    """
    stmt = (
        select(
            InfrastructureResource.name,
            ResourceGroup.name.label("group_name"),
            Skill.name.label("skill_name"),
            SkillAttribute.name.label("attr_name"),
            Site.name.label("site_name"),
        )
        .join(ResourceGroup, InfrastructureResource.group_id == ResourceGroup.id)
        .outerjoin(Site, InfrastructureResource.site_id == Site.id)
        .outerjoin(
            InfrastructureResourceSkill,
            InfrastructureResourceSkill.resource_id == InfrastructureResource.id,
        )
        .outerjoin(
            SkillAttribute,
            InfrastructureResourceSkill.skill_attribute_id == SkillAttribute.id,
        )
        .outerjoin(Skill, SkillAttribute.skill_id == Skill.id)
        .where(InfrastructureResource.is_active == True)  # noqa: E712
        .order_by(
            InfrastructureResource.name.asc(),
            Skill.name.asc(),
            SkillAttribute.name.asc(),
        )
    )
    result = await session.execute(stmt)
    return [
        (row.name, row.group_name, row.skill_name, row.attr_name, row.site_name)
        for row in result.all()
    ]
