"""Export and import routines for personal (people) resources.

Provides flat and skill-matrix Excel exports, a CSV export, and an importer
that creates or updates personal resources together with optional inline
skill assignments.
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.resource import PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.skill import PersonalResourceSkill, Skill, SkillAttribute

from .common import (
    ImportResult,
    _build_flat_resource_csv,
    _build_flat_resource_xlsx,
    _build_skill_matrix_xlsx,
    _import_resources,
    _load_matrix_data,
)


async def export_personnel_xlsx(session: AsyncSession) -> bytes:
    """Export active personal resources with skill assignments as Excel.

    The workbook generation is offloaded to a thread pool to avoid blocking
    the async event loop with CPU-bound openpyxl operations.
    """
    rows = await _load_personal_export_rows(session)
    return await asyncio.to_thread(_build_flat_resource_xlsx, rows, "Personnel")


async def export_personnel_matrix_xlsx(session: AsyncSession) -> bytes:
    """Export active personal resources as a skill matrix Excel file.

    Produces a pivot-table layout with a two-row header:
    - Row 1: Skill names (merged across their attributes)
    - Row 2: Attribute names
    - Data rows: resource name, group, then "X" per matching attribute

    The workbook generation is offloaded to a thread pool.
    """
    data = await _load_matrix_data(session, resource_type="personal")
    return await asyncio.to_thread(_build_skill_matrix_xlsx, data, "Personnel")


async def export_personnel_csv(session: AsyncSession) -> str:
    """Export active personal resources with skill assignments as CSV."""
    rows = await _load_personal_export_rows(session)
    return await asyncio.to_thread(_build_flat_resource_csv, rows)


async def import_personnel(session: AsyncSession, rows: list[tuple]) -> ImportResult:
    """Import personal resources with optional skill assignments.

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
        resource_model=PersonalResource,
        skill_model=PersonalResourceSkill,
        resource_type=ResourceType.personal,
    )


async def _load_personal_export_rows(
    session: AsyncSession,
) -> list[tuple[str, str, str | None, str | None, str | None]]:
    """Load personal resources with group and skill assignments for export.

    A resource with no skills gets one row with empty Skill/Attribute.
    A resource with N skill assignments gets N rows (Name and Group repeated).
    """
    stmt = (
        select(
            PersonalResource.name,
            ResourceGroup.name.label("group_name"),
            Skill.name.label("skill_name"),
            SkillAttribute.name.label("attr_name"),
            Site.name.label("site_name"),
        )
        .join(ResourceGroup, PersonalResource.group_id == ResourceGroup.id)
        .outerjoin(Site, PersonalResource.site_id == Site.id)
        .outerjoin(
            PersonalResourceSkill,
            PersonalResourceSkill.resource_id == PersonalResource.id,
        )
        .outerjoin(
            SkillAttribute,
            PersonalResourceSkill.skill_attribute_id == SkillAttribute.id,
        )
        .outerjoin(Skill, SkillAttribute.skill_id == Skill.id)
        .where(PersonalResource.is_active == True)  # noqa: E712
        .order_by(
            PersonalResource.name.asc(), Skill.name.asc(), SkillAttribute.name.asc()
        )
    )
    result = await session.execute(stmt)
    return [
        (row.name, row.group_name, row.skill_name, row.attr_name, row.site_name)
        for row in result.all()
    ]
