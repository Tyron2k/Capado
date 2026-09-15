"""Export and import routines for resource assignments.

Provides a CSV export of personal and infrastructure assignments and an
importer that resolves projects, work packages, and resources by name and
creates the matching personal or infrastructure assignments.
"""

import asyncio
import csv
import io
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .common import ImportResult, _parse_header, check_import_conflicts


async def _load_assignments_export_rows(session: AsyncSession) -> list[tuple]:
    """Load assignments with project, work package, and resource names for export.

    Each assignment produces one row with the project name, work package name,
    resource name, date range, and allocation.
    """
    from app.models.assignment import Assignment
    from app.models.project import Project, WorkPackage
    from app.models.resource import InfrastructureResource, PersonalResource

    # Personal assignments
    personal_stmt = (
        select(
            Project.name.label("project_name"),
            WorkPackage.name.label("wp_name"),
            PersonalResource.name.label("resource_name"),
            Assignment.start_date,
            Assignment.end_date,
            Assignment.allocation_percent,
            Assignment.resource_type,
        )
        .join(WorkPackage, Assignment.work_package_id == WorkPackage.id)
        .join(Project, WorkPackage.project_id == Project.id)
        .join(PersonalResource, Assignment.resource_id == PersonalResource.id)
        .where(Assignment.resource_type == "personal")
        .order_by(Project.name, WorkPackage.name, PersonalResource.name)
    )
    personal_result = await session.execute(personal_stmt)
    personal_rows = [
        (
            row.project_name,
            row.wp_name,
            row.resource_name,
            row.start_date.isoformat() if row.start_date else "",
            row.end_date.isoformat() if row.end_date else "",
            str(int(row.allocation_percent)) if row.allocation_percent else "100",
        )
        for row in personal_result.all()
    ]

    # Infrastructure assignments
    infra_stmt = (
        select(
            Project.name.label("project_name"),
            WorkPackage.name.label("wp_name"),
            InfrastructureResource.name.label("resource_name"),
            Assignment.start_at,
            Assignment.end_at,
            Assignment.resource_type,
        )
        .join(WorkPackage, Assignment.work_package_id == WorkPackage.id)
        .join(Project, WorkPackage.project_id == Project.id)
        .join(
            InfrastructureResource,
            Assignment.resource_id == InfrastructureResource.id,
        )
        .where(Assignment.resource_type == "infrastructure")
        .order_by(Project.name, WorkPackage.name, InfrastructureResource.name)
    )
    infra_result = await session.execute(infra_stmt)
    infra_rows = [
        (
            row.project_name,
            row.wp_name,
            row.resource_name,
            row.start_at.date().isoformat() if row.start_at else "",
            row.end_at.date().isoformat() if row.end_at else "",
            "100",
        )
        for row in infra_result.all()
    ]

    return personal_rows + infra_rows


async def export_assignments_csv(session: AsyncSession) -> str:
    """Export assignments as CSV (Project;Work Package;Resource;Start;End;Allocation)."""
    rows = await _load_assignments_export_rows(session)
    return await asyncio.to_thread(_build_assignments_csv, rows)


def _build_assignments_csv(rows: list[tuple]) -> str:
    """Build assignments CSV content (CPU-bound, runs in thread pool)."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        ["Project", "Work Package", "Resource", "Start", "End", "Allocation"]
    )
    for project, wp, resource, start, end, alloc in rows:
        writer.writerow([project, wp, resource, start, end, alloc])
    return output.getvalue()


async def import_assignments(session: AsyncSession, rows: list[tuple]) -> ImportResult:
    """Import assignments from CSV.

    Supports two CSV formats:
    - 6 columns: Project; Work Package; Resource; Start; End; Allocation
    - 5 columns: Project; Resource; Start; End; Allocation
      (work package is auto-resolved by finding the first WP in the project
      whose date range overlaps the assignment dates)

    Resources are looked up by name. If found as infrastructure, an
    infrastructure assignment (start_at/end_at) is created. If found as
    personal, a personal assignment (start_date/end_date/allocation_percent)
    is created. Duplicates (same resource + work package) are skipped.

    Args:
        session: Database session.
        rows: Parsed rows including header.

    Returns:
        Import result with counts.
    """
    from datetime import date as date_type
    from datetime import datetime as datetime_type

    from app.models.assignment import Assignment
    from app.models.project import Project, WorkPackage
    from app.models.resource import InfrastructureResource, PersonalResource

    result = ImportResult()

    if not rows:
        result.errors.append("File is empty.")
        return result

    header = _parse_header(rows[0])
    if len(header) < 5:
        result.errors.append(
            "Header must have at least: Project, Resource, Start, End, Allocation."
        )
        return result

    # Detect format: 6 columns (with Work Package) or 5 columns (without)
    has_wp_column = len(header) >= 6 and "work" in header[1].lower()

    # Pre-load caches
    project_stmt = select(Project)
    project_result = await session.execute(project_stmt)
    projects_by_name: dict[str, Project] = {
        p.name.lower(): p for p in project_result.scalars().all()
    }

    infra_stmt = select(InfrastructureResource).where(
        InfrastructureResource.is_active == True  # noqa: E712
    )
    infra_result = await session.execute(infra_stmt)
    infra_by_name: dict[str, InfrastructureResource] = {
        r.name.lower(): r for r in infra_result.scalars().all()
    }

    personal_stmt = select(PersonalResource).where(
        PersonalResource.is_active == True  # noqa: E712
    )
    personal_result = await session.execute(personal_stmt)
    personal_by_name: dict[str, PersonalResource] = {
        r.name.lower(): r for r in personal_result.scalars().all()
    }

    # Pre-load existing assignments for duplicate detection
    existing_stmt = select(Assignment)
    existing_result = await session.execute(existing_stmt)
    existing_assignments: set[tuple[UUID, UUID]] = {
        (a.resource_id, a.work_package_id) for a in existing_result.scalars().all()
    }

    affected: set[UUID] = set()
    for row_idx, row in enumerate(rows[1:], start=2):
        cells = [str(cell).strip() if cell else "" for cell in row]

        if has_wp_column:
            project_name = cells[0] if len(cells) > 0 else ""
            wp_name = cells[1] if len(cells) > 1 else ""
            resource_name = cells[2] if len(cells) > 2 else ""
            start_str = cells[3] if len(cells) > 3 else ""
            end_str = cells[4] if len(cells) > 4 else ""
            alloc_str = cells[5] if len(cells) > 5 else "100"
        else:
            project_name = cells[0] if len(cells) > 0 else ""
            wp_name = ""
            resource_name = cells[1] if len(cells) > 1 else ""
            start_str = cells[2] if len(cells) > 2 else ""
            end_str = cells[3] if len(cells) > 3 else ""
            alloc_str = cells[4] if len(cells) > 4 else "100"

        if not project_name or not resource_name:
            continue

        # Parse dates
        try:
            start_date = date_type.fromisoformat(start_str) if start_str else None
            end_date = date_type.fromisoformat(end_str) if end_str else None
        except ValueError:
            result.errors.append(
                f"Row {row_idx}: Invalid date format (use YYYY-MM-DD)."
            )
            continue

        if not start_date or not end_date:
            result.errors.append(f"Row {row_idx}: Start and End dates are required.")
            continue

        # Parse allocation
        try:
            allocation = float(alloc_str) if alloc_str else 100.0
        except ValueError:
            allocation = 100.0

        # Resolve project
        project = projects_by_name.get(project_name.lower())
        if project is None:
            result.errors.append(f"Row {row_idx}: Project '{project_name}' not found.")
            continue

        # Resolve work package
        wp: WorkPackage | None = None
        if wp_name:
            wp_stmt = select(WorkPackage).where(
                WorkPackage.project_id == project.id,
                func.lower(WorkPackage.name) == wp_name.lower(),
            )
            wp_result_db = await session.execute(wp_stmt)
            wp = wp_result_db.scalars().first()
            if wp is None:
                result.errors.append(
                    f"Row {row_idx}: Work package '{wp_name}' not found "
                    f"in project '{project_name}'."
                )
                continue
        else:
            # Auto-resolve: find the first work package whose dates overlap
            wp_stmt = (
                select(WorkPackage)
                .where(
                    WorkPackage.project_id == project.id,
                    WorkPackage.start_date <= end_date,
                    WorkPackage.end_date >= start_date,
                )
                .order_by(WorkPackage.start_date)
            )
            wp_result_db = await session.execute(wp_stmt)
            wp = wp_result_db.scalars().first()
            if wp is None:
                # Fallback: just take the first WP in the project
                wp_stmt = (
                    select(WorkPackage)
                    .where(WorkPackage.project_id == project.id)
                    .order_by(WorkPackage.start_date)
                )
                wp_result_db = await session.execute(wp_stmt)
                wp = wp_result_db.scalars().first()
            if wp is None:
                result.errors.append(
                    f"Row {row_idx}: No work package found for project "
                    f"'{project_name}'."
                )
                continue

        # Resolve resource (infrastructure first, then personal)
        infra_resource = infra_by_name.get(resource_name.lower())
        personal_resource = personal_by_name.get(resource_name.lower())

        if infra_resource:
            resource_id = infra_resource.id
            resource_type = "infrastructure"
        elif personal_resource:
            resource_id = personal_resource.id
            resource_type = "personal"
        else:
            result.errors.append(
                f"Row {row_idx}: Resource '{resource_name}' not found."
            )
            continue

        affected.add(resource_id)

        # Check for duplicate
        assign_key = (resource_id, wp.id)
        if assign_key in existing_assignments:
            result.skipped += 1
            continue

        # Create the assignment
        if resource_type == "infrastructure":
            assignment = Assignment(
                resource_id=resource_id,
                resource_type=resource_type,
                work_package_id=wp.id,
                start_at=datetime_type(
                    start_date.year, start_date.month, start_date.day, 6, 0, 0
                ),
                end_at=datetime_type(
                    end_date.year, end_date.month, end_date.day, 18, 0, 0
                ),
            )
        else:
            assignment = Assignment(
                resource_id=resource_id,
                resource_type=resource_type,
                work_package_id=wp.id,
                start_date=start_date,
                end_date=end_date,
                allocation_percent=allocation,
            )

        session.add(assignment)
        existing_assignments.add(assign_key)
        result.created += 1

    await session.commit()
    await check_import_conflicts(session, result, affected)
    return result
