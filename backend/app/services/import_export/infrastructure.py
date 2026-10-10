"""Export and import routines for infrastructure resources.

Provides flat and skill-matrix Excel exports, a CSV export, and an importer
that creates or updates infrastructure resources together with optional
inline skill assignments.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.models.resource import InfrastructureResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.skill import InfrastructureResourceSkill, Skill, SkillAttribute
from app.schemas.transfer.calendar import InfrastructureAvailabilityWindowTransfer
from app.schemas.transfer.resource import (
    InfrastructureResourceTransfer,
    PersonalResourceTransfer,
)
from app.schemas.transfer.skill import InfrastructureResourceSkillTransfer

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


async def export_infrastructure_xlsx(session: AsyncSession) -> bytes:
    """Export active infrastructure resources with skill assignments as Excel."""
    rows = await _load_infra_export_rows(session)
    return await asyncio.to_thread(_build_flat_resource_xlsx, rows, "Infrastructure")


async def export_infrastructure_matrix_xlsx(session: AsyncSession) -> bytes:
    """Export active infrastructure resources as a skill matrix Excel file."""
    data = await _load_matrix_data(session, resource_type="infrastructure")
    return await asyncio.to_thread(_build_skill_matrix_xlsx, data, "Infrastructure")


async def export_infrastructure_csv(session: AsyncSession) -> str:
    """Export the complete area CSV also included verbatim in the all-data ZIP."""
    from .csv_transfer import export_area

    return (await export_area(session, "infrastructure")).decode("utf-8-sig")


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
    from .csv_format import is_area_csv
    from .csv_transfer import import_area_rows

    if is_area_csv(rows):
        return await import_area_rows(session, "infrastructure", rows)

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


CSV_AREA = CsvArea(
    "infrastructure",
    (
        RESOURCE_GROUP_CSV,
        entity(
            m.InfrastructureResource,
            "id name group_id site_id is_active created_at updated_at",
            validation_model=InfrastructureResourceTransfer,
        ),
        entity(
            m.InfrastructureResourceSkill,
            "id resource_id skill_attribute_id valid_from valid_until level created_at",
            existing_by_id=True,
            validation_model=InfrastructureResourceSkillTransfer,
        ),
        RESOURCE_WORK_PROFILE_CSV,
        entity(
            m.InfrastructureAvailabilityWindow,
            "id resource_id weekday start_time end_time created_at updated_at",
            existing_by_id=True,
            validation_model=InfrastructureAvailabilityWindowTransfer,
        ),
    ),
)


async def load_export(session: AsyncSession) -> dict[str, list[dict]]:
    """Read this area's approved data and the references needed by its exporter."""
    return await load_data(
        session,
        CSV_AREA.entities
        + (
            entity(
                m.PersonalResource,
                "id name group_id site_id is_active created_at updated_at",
                validation_model=PersonalResourceTransfer,
            ),
        ),
    )


def export_csv(data: dict[str, list[dict]]) -> bytes:
    """Produce the complete area CSV used by both downloads and ZIP exports."""
    return dump_area(CSV_AREA, resource_csv_data(data, "infrastructure"))


def parse_csv(rows: list[tuple] | list[list[str]]) -> CsvBatch:
    """Decode and check the versioned CSV belonging to this domain."""
    batch = parse_area_rows(CSV_AREA, rows)
    for row in batch.data["resource_groups"]:
        if row["resource_type"] != "infrastructure":
            number = batch.row_numbers[("resource_groups", row["id"])]
            raise ValueError(
                f"{CSV_AREA.name}.csv, row {number}, field resource_type: resource group belongs to another area."
            )
    return batch


def validate_import(context: ImportContext) -> None:
    """Check this domain's rules against the complete planned destination."""
    batch = context.batches.get(CSV_AREA.name)
    if batch:
        for row in batch.data["resource_work_profiles"]:
            if binding_resource_type(row, context.merged) != "infrastructure":
                context.fail(
                    "resource_work_profiles",
                    row,
                    "resource_id/group_id",
                    "Work-profile binding belongs to another CSV area.",
                )
    for row in context.merged["infrastructure_availability_windows"].values():
        if row["start_time"] == row["end_time"]:
            context.fail(
                "infrastructure_availability_windows",
                row,
                "end_time",
                "Availability window start/end must differ.",
            )
    validate_resource_csv(context, "infrastructure")


async def write_import(
    session: AsyncSession, batch: CsvBatch, context: ImportContext
) -> ImportResult:
    """Write this area's prepared records inside the caller's transaction."""
    track_resource_csv(context, "infrastructure")
    context.track_resources("infrastructure_availability_windows")
    return await write_area(
        session,
        CSV_AREA.entities,
        batch.data,
        context,
        hierarchical=("resource_groups",),
    )
