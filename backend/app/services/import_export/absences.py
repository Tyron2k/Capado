"""Complete CSV export and import of absences data."""

from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.schemas.transfer.absence import AbsenceTransfer

from .common import ImportResult
from .csv_format import CsvArea, CsvBatch, dump_area, entity, parse_area_rows
from .csv_storage import (
    ImportContext,
    load_data,
    validate_ranges,
    write_area,
)

CSV_AREA = CsvArea(
    "absences",
    (
        entity(
            m.Absence,
            "id resource_id resource_type reason start_date end_date allocation_percent status note created_at updated_at",
            reference_tables=("personal_resources", "infrastructure_resources"),
            existing_by_id=True,
            validation_model=AbsenceTransfer,
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
    """Check resource references, absence intervals and supported statuses."""
    validate_ranges(
        list(context.merged["absences"].values()), context=context, table="absences"
    )
    for row in context.merged["absences"].values():
        table = (
            "personal_resources"
            if row["resource_type"] == "personal"
            else "infrastructure_resources"
        )
        if row["resource_id"] not in context.merged[table]:
            context.fail("absences", row, "resource_id", "unknown resource.")
        if row["status"] not in {"provisional", "confirmed"}:
            context.fail("absences", row, "status", "Invalid absence status.")


async def write_import(
    session: AsyncSession, batch: CsvBatch, context: ImportContext
) -> ImportResult:
    """Write this area's prepared records inside the caller's transaction."""
    context.track_resources("absences")
    return await write_area(session, CSV_AREA.entities, batch.data, context)
