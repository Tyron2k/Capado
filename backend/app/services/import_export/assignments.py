"""CSV transfers of assignments, preserving intervals and resource identity."""

import math
from datetime import UTC, date, datetime
from typing import NotRequired, TypedDict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.models.assignment import Assignment
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.schemas.transfer.assignment import AssignmentTransfer
from app.services.assignment_service import is_identical_booking_violation
from app.services.time_zone import local_date, local_wall_time_to_utc, planning_zone

from .common import ImportResult, _parse_header, check_import_conflicts
from .csv_format import CsvArea, CsvBatch, dump_area, entity, parse_area_rows
from .csv_storage import (
    ImportContext,
    load_data,
    validate_ranges,
    write_area,
)


class AssignmentFields(TypedDict):
    """Only the five supported interval fields can reach persistence."""

    start_date: NotRequired[date]
    end_date: NotRequired[date]
    allocation_percent: NotRequired[float]
    start_at: NotRequired[datetime]
    end_at: NotRequired[datetime]


_HEADERS = (
    "Project",
    "Work Package",
    "Resource",
    "Start",
    "End",
    "Allocation",
    "Resource Type",
    "Resource Group",
)


def _stored_utc(value: datetime | None) -> datetime | None:
    """Normalize stored UTC values, including SQLite's offset-free test results.

    Production timestamps are timestamptz (migration 002). SQLite drops offsets
    on read; this fallback is only for stored values, never for CSV input.
    """
    if value is None:
        return None
    return (
        value.replace(tzinfo=UTC)
        if value.utcoffset() is None
        else value.astimezone(UTC)
    )


async def export_assignments_csv(session: AsyncSession) -> str:
    """Export the complete area CSV also included verbatim in the all-data ZIP."""
    from .csv_transfer import export_area

    return (await export_area(session, "assignments")).decode("utf-8-sig")


def _assignment_key(assignment: Assignment) -> tuple:
    """Only an identical interval and allocation is a duplicate booking."""
    return (
        assignment.resource_type,
        assignment.resource_id,
        assignment.work_package_id,
        assignment.start_date,
        assignment.end_date,
        assignment.allocation_percent,
        _stored_utc(assignment.start_at),
        _stored_utc(assignment.end_at),
    )


def _infrastructure_time(value: str, *, hour: int) -> datetime:
    """Accept offset-bearing timestamps, or the historical date-only format."""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        instant = datetime.fromisoformat(value)
        if instant.utcoffset() is None:
            raise ValueError(
                "Infrastructure timestamps must include a UTC offset."
            ) from None
        return instant.astimezone(UTC)
    return local_wall_time_to_utc(
        datetime.combine(day, datetime.min.time()).replace(hour=hour), planning_zone()
    )


async def import_assignments(session: AsyncSession, rows: list[tuple]) -> ImportResult:
    """Import precise or legacy assignments, refusing ambiguous references.

    New exports append Resource Type and Resource Group to the six-column
    format. Legacy five-column files omit Work Package; automatic resolution
    succeeds only if one overlapping work package (or one total) is available.
    Date-only infrastructure intervals retain the historical 06:00/18:00
    planning-zone defaults. Explicit timestamps must include their UTC offset.
    """
    from .csv_format import is_area_csv
    from .csv_transfer import import_area_rows

    if is_area_csv(rows):
        return await import_area_rows(session, "assignments", rows)

    result = ImportResult()
    if not rows:
        result.errors.append("File is empty.")
        return result

    header = [cell.lower() for cell in _parse_header(rows[0])]
    required = {"project", "resource", "start", "end", "allocation"}
    if not required.issubset(header) or len(header) != len(set(header)):
        result.errors.append(
            "Header must have unique columns including: Project, Resource, Start, End, Allocation."
        )
        return result
    columns = {name: index for index, name in enumerate(header)}

    projects = (await session.execute(select(Project))).scalars().all()
    infra = (
        (
            await session.execute(
                select(InfrastructureResource).where(
                    InfrastructureResource.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    personal = (
        (
            await session.execute(
                select(PersonalResource).where(PersonalResource.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    existing = (await session.execute(select(Assignment))).scalars().all()
    existing_keys = {_assignment_key(assignment) for assignment in existing}
    projects_by_name: dict[str, list[Project]] = {}
    for project in projects:
        projects_by_name.setdefault(project.name.lower(), []).append(project)
    resources_by_name: dict[
        str, list[tuple[InfrastructureResource | PersonalResource, ResourceType]]
    ] = {}
    for resources, resource_type in (
        (infra, ResourceType.infrastructure),
        (personal, ResourceType.personal),
    ):
        for resource in resources:
            resources_by_name.setdefault(resource.name.lower(), []).append(
                (resource, resource_type)
            )
    groups: dict[UUID, str] = {}
    if "resource group" in columns:
        groups = {
            g.id: g.name.lower()
            for g in (await session.execute(select(ResourceGroup))).scalars().all()
        }

    affected: set[UUID] = set()
    for row_idx, row in enumerate(rows[1:], start=2):
        cells = [str(cell).strip() if cell is not None else "" for cell in row]

        def cell(name: str, cells: list[str] = cells) -> str:
            index = columns.get(name)
            return cells[index] if index is not None and index < len(cells) else ""

        if not any(cells):
            continue
        project_name, resource_name = cell("project"), cell("resource")
        if not project_name or not resource_name:
            result.errors.append(f"Row {row_idx}: Project and Resource are required.")
            continue
        if not cell("start") or not cell("end"):
            result.errors.append(f"Row {row_idx}: Start and End dates are required.")
            continue

        matches = projects_by_name.get(project_name.lower(), [])
        if len(matches) != 1:
            reason = (
                "not found" if not matches else "ambiguous; use a unique project name"
            )
            result.errors.append(f"Row {row_idx}: Project '{project_name}' {reason}.")
            continue
        project = matches[0]

        kind, group_name = cell("resource type").lower(), cell("resource group").lower()
        if "resource type" in columns and kind not in {"personal", "infrastructure"}:
            result.errors.append(
                f"Row {row_idx}: Resource Type must be personal or infrastructure."
            )
            continue
        if "resource group" in columns and not group_name:
            result.errors.append(
                f"Row {row_idx}: Resource Group is required when its column is present."
            )
            continue
        candidates = [
            (resource, resource_type)
            for resource, resource_type in resources_by_name.get(
                resource_name.lower(), []
            )
            if (not kind or kind == resource_type)
            and (not group_name or groups.get(resource.group_id) == group_name)
        ]
        if len(candidates) != 1:
            if not candidates:
                reason = "not found among active resources"
            elif kind and group_name:
                reason = (
                    "ambiguous even with type/group; use unique resource or group names"
                )
            else:
                reason = "ambiguous; specify Resource Type and Resource Group"
            result.errors.append(f"Row {row_idx}: Resource '{resource_name}' {reason}.")
            continue
        resource, resource_type = candidates[0]

        fields: AssignmentFields
        try:
            if resource_type == ResourceType.infrastructure:
                start_at = _infrastructure_time(cell("start"), hour=6)
                end_at = _infrastructure_time(cell("end"), hour=18)
                if end_at <= start_at:
                    raise ValueError("End time must be after Start time.")
                start_date, end_date = (
                    local_date(start_at, planning_zone()),
                    local_date(end_at, planning_zone()),
                )
                fields = {"start_at": start_at, "end_at": end_at}
            else:
                start_date, end_date = (
                    date.fromisoformat(cell("start")),
                    date.fromisoformat(cell("end")),
                )
                if end_date < start_date:
                    raise ValueError("End date must not be before Start date.")
                allocation = float(cell("allocation") or "100")
                if not math.isfinite(allocation) or not 0 < allocation <= 100:
                    raise ValueError(
                        "Allocation must be a finite number greater than 0 and at most 100."
                    )
                fields = {
                    "start_date": start_date,
                    "end_date": end_date,
                    "allocation_percent": allocation,
                }
        except ValueError as exc:
            result.errors.append(
                f"Row {row_idx}: Invalid date, time or allocation: {exc} (use YYYY-MM-DD or an ISO timestamp with a UTC offset)."
            )
            continue

        wp_name = cell("work package")
        wp_stmt = select(WorkPackage).where(WorkPackage.project_id == project.id)
        if wp_name:
            wp_stmt = wp_stmt.where(func.lower(WorkPackage.name) == wp_name.lower())
        else:
            wp_stmt = wp_stmt.where(
                WorkPackage.start_date <= end_date, WorkPackage.end_date >= start_date
            )
        work_packages = (await session.execute(wp_stmt)).scalars().all()
        if not wp_name and not work_packages:
            work_packages = (
                (
                    await session.execute(
                        select(WorkPackage).where(WorkPackage.project_id == project.id)
                    )
                )
                .scalars()
                .all()
            )
        if len(work_packages) != 1:
            reason = (
                "not found"
                if not work_packages
                else "ambiguous; specify a unique Work Package name"
            )
            result.errors.append(
                f"Row {row_idx}: Work package '{wp_name}' {reason} in project '{project_name}'."
            )
            continue

        assignment = Assignment(
            resource_id=resource.id,
            resource_type=resource_type,
            work_package_id=work_packages[0].id,
            **fields,
        )
        # An unchanged re-import also repairs missing/stale conflict records.
        affected.add(resource.id)
        key = _assignment_key(assignment)
        if key in existing_keys:
            result.skipped += 1
            continue
        session.add(assignment)
        existing_keys.add(key)
        result.created += 1

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if not is_identical_booking_violation(exc):
            raise
        result.created = 0
        result.errors.append(
            "An identical booking was saved concurrently. No new rows were imported; retry the import."
        )
        return result
    await check_import_conflicts(session, result, affected)
    return result


CSV_AREA = CsvArea(
    "assignments",
    (
        entity(
            m.Assignment,
            "id resource_id resource_type work_package_id start_date end_date allocation_percent start_at end_at created_at updated_at",
            reference_tables=("personal_resources", "infrastructure_resources"),
            existing_by_id=True,
            validation_model=AssignmentTransfer,
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
    """Validate resource references and the distinct personal/infrastructure shapes."""
    by_id = context.merged
    validate_ranges(
        list(by_id["assignments"].values()), context=context, table="assignments"
    )
    identities: set[tuple] = set()
    for row in by_id["assignments"].values():
        identity = tuple(
            row[field]
            for field in (
                "resource_type",
                "resource_id",
                "work_package_id",
                "start_date",
                "end_date",
                "allocation_percent",
                "start_at",
                "end_at",
            )
        )
        if identity in identities:
            context.fail(
                "assignments",
                row,
                "resource_id/work_package_id/start_date/start_at",
                "An identical booking already exists.",
            )
        identities.add(identity)
        personal = row["resource_type"] == "personal"
        table = "personal_resources" if personal else "infrastructure_resources"
        if row["resource_id"] not in by_id[table]:
            context.fail("assignments", row, "resource_id", "unknown resource.")
        required = (
            ("start_date", "end_date", "allocation_percent")
            if personal
            else ("start_at", "end_at")
        )
        forbidden = (
            ("start_at", "end_at")
            if personal
            else ("start_date", "end_date", "allocation_percent")
        )
        if any(row[key] is None for key in required) or any(
            row[key] is not None for key in forbidden
        ):
            context.fail(
                "assignments",
                row,
                "resource_type/start_date/end_date/start_at/end_at/allocation_percent",
                "Assignment date/time fields do not match its resource type.",
            )
        if not personal and row["end_at"] <= row["start_at"]:
            context.fail(
                "assignments",
                row,
                "end_at",
                "Assignment end time must follow start time.",
            )


async def write_import(
    session: AsyncSession, batch: CsvBatch, context: ImportContext
) -> ImportResult:
    """Write this area's prepared records inside the caller's transaction."""
    context.track_resources("assignments")
    return await write_area(session, CSV_AREA.entities, batch.data, context)
