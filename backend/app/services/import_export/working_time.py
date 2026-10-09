"""Complete CSV export and import of working-time data."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.schemas.transfer.calendar import HolidayTransfer, WorkWeekProfileTransfer
from app.schemas.transfer.site import SiteTransfer

from .common import ImportResult, resource_ids_for_groups
from .csv_format import CsvArea, CsvBatch, dump_area, entity, parse_area_rows
from .csv_storage import (
    ImportContext,
    id_batches,
    load_data,
    validate_single_flag,
    write_area,
)

CSV_AREA = CsvArea(
    "working-time",
    (
        entity(
            m.Site,
            "id name region_code is_default is_active created_at updated_at",
            validation_model=SiteTransfer,
        ),
        entity(
            m.WorkWeekProfile,
            "id name description monday_minutes tuesday_minutes wednesday_minutes thursday_minutes friday_minutes saturday_minutes sunday_minutes is_default created_at updated_at",
            validation_model=WorkWeekProfileTransfer,
        ),
        entity(
            m.Holiday,
            "id site_id day name working_minutes created_at updated_at",
            existing_by_id=True,
            validation_model=HolidayTransfer,
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
    """Check default calendars and holiday values in the planned state."""
    for table in ("sites", "work_week_profiles"):
        validate_single_flag(
            list(context.merged[table].values()), "is_default", table, context=context
        )


async def write_import(
    session: AsyncSession, batch: CsvBatch, context: ImportContext
) -> ImportResult:
    """Write this area's prepared records inside the caller's transaction."""
    await _track_calendar_resources(session, context)
    return await write_area(session, CSV_AREA.entities, batch.data, context)


async def _track_calendar_resources(
    session: AsyncSession, context: ImportContext
) -> None:
    """Scope exceptions/profile changes; a changed shared default affects all bookings."""
    profiles = context.data["work_week_profiles"]
    profile_ids = {row["id"] for row in profiles}
    old_profiles = [
        row
        for row in context.existing["work_week_profiles"]
        if row["id"] in profile_ids
    ]
    if any(row["is_default"] for row in profiles + old_profiles):
        context.refresh_all_conflicts = True
        return
    bindings: list[m.ResourceWorkProfile] = []
    for chunk in id_batches(profile_ids):
        bindings.extend(
            (
                await session.execute(
                    select(m.ResourceWorkProfile).where(
                        m.ResourceWorkProfile.profile_id.in_(chunk)
                    )
                )
            )
            .scalars()
            .all()
        )
    context.affected_resources.update(
        row.resource_id for row in bindings if row.resource_id is not None
    )
    groups = {row.group_id for row in bindings if row.group_id is not None}
    context.affected_resources.update(await resource_ids_for_groups(session, groups))
    sites = context.data["sites"]
    site_ids = {row["id"] for row in sites}
    holidays = context.data["holidays"]
    holiday_ids = {row["id"] for row in holidays}
    old_holidays = [
        row for row in context.existing["holidays"] if row["id"] in holiday_ids
    ]
    site_ids.update(row["site_id"] for row in holidays + old_holidays)
    old_sites = [row for row in context.existing["sites"] if row["id"] in site_ids]
    planned_sites = [
        row for row in context.merged["sites"].values() if row["id"] in site_ids
    ]
    include_default = any(row["is_default"] for row in planned_sites + old_sites)
    for model in (m.PersonalResource, m.InfrastructureResource):
        for chunk in id_batches(site_ids):
            context.affected_resources.update(
                (
                    await session.execute(
                        select(model.id).where(model.site_id.in_(chunk))
                    )
                )
                .scalars()
                .all()
            )
        if include_default:
            context.affected_resources.update(
                (await session.execute(select(model.id).where(model.site_id.is_(None))))
                .scalars()
                .all()
            )
