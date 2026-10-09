"""Export and import routines for personal (people) resources.

Provides flat and skill-matrix Excel exports, a CSV export, and an importer
that creates or updates personal resources together with optional inline
skill assignments.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.models.resource import PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.skill import PersonalResourceSkill, Skill, SkillAttribute
from app.schemas.transfer.resource import (
    InfrastructureResourceTransfer,
    PersonalResourceTransfer,
)
from app.schemas.transfer.skill import PersonalResourceSkillTransfer

from .common import (
    RESOURCE_GROUP_CSV,
    RESOURCE_WORK_PROFILE_CSV,
    ImportResult,
    _build_flat_resource_xlsx,
    _build_skill_matrix_xlsx,
    _import_resources,
    _load_matrix_data,
    binding_resource_type,
    resource_csv_data,
    track_resource_csv,
    validate_resource_csv,
)
from .csv_format import CsvArea, CsvBatch, dump_area, entity, parse_area_rows
from .csv_storage import (
    ImportContext,
    load_data,
    write_area,
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
    """Export the complete area CSV also included verbatim in the all-data ZIP."""
    from .csv_transfer import export_area

    return (await export_area(session, "personnel")).decode("utf-8-sig")


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
    from .csv_format import is_area_csv
    from .csv_transfer import import_area_rows

    if is_area_csv(rows):
        return await import_area_rows(session, "personnel", rows)

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


CSV_AREA = CsvArea(
    "personnel",
    (
        RESOURCE_GROUP_CSV,
        entity(
            m.PersonalResource,
            "id name group_id site_id is_active created_at updated_at",
            validation_model=PersonalResourceTransfer,
        ),
        entity(
            m.PersonalResourceSkill,
            "id resource_id skill_attribute_id valid_from valid_until level created_at",
            existing_by_id=True,
            validation_model=PersonalResourceSkillTransfer,
        ),
        RESOURCE_WORK_PROFILE_CSV,
    ),
)


async def load_export(session: AsyncSession) -> dict[str, list[dict]]:
    """Read this area's approved data and the references needed by its exporter."""
    return await load_data(
        session,
        CSV_AREA.entities
        + (
            entity(
                m.InfrastructureResource,
                "id name group_id site_id is_active created_at updated_at",
                validation_model=InfrastructureResourceTransfer,
            ),
        ),
    )


def export_csv(data: dict[str, list[dict]]) -> bytes:
    """Produce the complete area CSV used by both downloads and ZIP exports."""
    return dump_area(CSV_AREA, resource_csv_data(data, "personal"))


def parse_csv(rows: list[tuple] | list[list[str]]) -> CsvBatch:
    """Decode and check the versioned CSV belonging to this domain."""
    batch = parse_area_rows(CSV_AREA, rows)
    for row in batch.data["resource_groups"]:
        if row["resource_type"] != "personal":
            number = batch.row_numbers[("resource_groups", row["id"])]
            raise ValueError(
                f"{CSV_AREA.name}.csv, row {number}, field resource_type: resource group belongs to another area."
            )
    return batch


def validate_import(context: ImportContext) -> None:
    """Check this domain's rules against the complete planned destination."""
    validate_resource_csv(context, "personal")
    batch = context.batches.get(CSV_AREA.name)
    if batch:
        for row in batch.data["resource_work_profiles"]:
            if binding_resource_type(row, context.merged) != "personal":
                context.fail(
                    "resource_work_profiles",
                    row,
                    "resource_id/group_id",
                    "Work-profile binding belongs to another CSV area.",
                )


async def write_import(
    session: AsyncSession, batch: CsvBatch, context: ImportContext
) -> ImportResult:
    """Write this area's prepared records inside the caller's transaction."""
    track_resource_csv(context, "personal")
    return await write_area(
        session,
        CSV_AREA.entities,
        batch.data,
        context,
        hierarchical=("resource_groups",),
    )
