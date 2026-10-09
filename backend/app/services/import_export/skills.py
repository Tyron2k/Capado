"""Complete CSV export and import of skills data."""

from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.schemas.transfer.skill import SkillAttributeTransfer, SkillTransfer

from .common import ImportResult
from .csv_format import CsvArea, CsvBatch, dump_area, entity, parse_area_rows
from .csv_storage import (
    ImportContext,
    load_data,
    write_area,
)

CSV_AREA = CsvArea(
    "skills",
    (
        entity(
            m.Skill, "id name resource_type created_at", validation_model=SkillTransfer
        ),
        entity(
            m.SkillAttribute,
            "id skill_id name created_at",
            validation_dependents=(
                "work_package_requirements",
                "work_package_template_requirements",
            ),
            validation_model=SkillAttributeTransfer,
        ),
    ),
)


async def load_export(session: AsyncSession) -> dict[str, list[dict]]:
    """Read this area's approved data and the references needed by its exporter."""
    return await load_data(session, CSV_AREA.entities)


def export_csv(data: dict[str, list[dict]]) -> bytes:
    """Produce the complete area CSV used by both downloads and ZIP exports."""
    return dump_area(CSV_AREA, data)


def parse_csv(rows: list[tuple] | list[list[str]]) -> CsvBatch:
    """Decode and check the versioned CSV belonging to this domain."""
    return parse_area_rows(CSV_AREA, rows)


def validate_import(context: ImportContext) -> None:
    """Keep catalogue resource types explicit, including unused skills."""
    for row in context.merged["skills"].values():
        if row["resource_type"] not in {"personal", "infrastructure"}:
            context.fail("skills", row, "resource_type", "Invalid resource type.")


async def write_import(
    session: AsyncSession, batch: CsvBatch, context: ImportContext
) -> ImportResult:
    """Write this area's prepared records inside the caller's transaction."""
    return await write_area(session, CSV_AREA.entities, batch.data, context)
