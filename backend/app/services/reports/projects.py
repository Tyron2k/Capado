"""The project status report: one row per project, one per work package.

Reports the same commitment and dependency assessments the project overview shows, by calling the
same functions (:func:`assess_commitment`, :func:`check_violation`). The whole value of a status
report is that it agrees with the screen the planner is looking at; a second implementation would
eventually disagree, and then a meeting spends its time deciding which number to believe.

The one thing this report does that the screen cannot: it puts every project side by side in a form
a controller can sort and filter. That is why the breach columns are numbers of working days rather
than badges — a badge cannot be sorted.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.customer import Customer
from app.models.project import Project, ProjectFolder, WorkPackage
from app.services.customer_resolution import FolderNode, resolve_customer_id
from app.services.dependencies import check_violation
from app.services.lead_time import assess_commitment
from app.services.reports.workbook import (
    Column,
    autosize,
    generated_subtitle,
    new_workbook,
    save,
    write_header,
    write_row,
    write_title,
)
from app.services.work_package_dependency_service import WorkPackageDependencyService
from app.services.working_time_service import WorkingTimeService

_NO_RESOURCE = UUID("00000000-0000-0000-0000-000000000000")

_PROJECT_COLUMNS = [
    Column("Ordner"),
    Column("Projekt"),
    Column("Kunde"),
    # The order number lives on the FOLDER as well as the project: an order number covers a
    # whole job, which is a folder here, while a project may carry its own reference.
    # Both are shown rather than one silently winning.
    Column("Auftragsnr. Ordner"),
    Column("Referenz Projekt"),
    Column("Priorität"),
    Column("Start", "DD.MM.YYYY"),
    Column("Geplantes Ende", "DD.MM.YYYY"),
    Column("Zugesagt", "DD.MM.YYYY"),
    # A number, not a badge: a controller sorts by this column, and "über Zusage" cannot be
    # sorted. Positive means past the commitment.
    Column("Arbeitstage über Zusage", "0"),
    Column("Arbeitspakete", "0"),
    Column("Abgeschlossen", "0"),
    Column("Fortschritt %", "0.0"),
]

_WP_COLUMNS = [
    Column("Projekt"),
    Column("Arbeitspaket"),
    Column("Start", "DD.MM.YYYY"),
    Column("Ende", "DD.MM.YYYY"),
    Column("Abgeschlossen am", "DD.MM.YYYY"),
    Column("Abhängigkeit verletzt (AT)", "0"),
]


async def build_project_report(session: AsyncSession) -> bytes:
    """Build the workbook covering every project."""
    projects = list((await session.execute(select(Project))).scalars().all())
    work_packages = list((await session.execute(select(WorkPackage))).scalars().all())
    folders = {
        folder.id: folder
        for folder in (await session.execute(select(ProjectFolder))).scalars().all()
    }
    # Customer names, and the folder tree needed to resolve inheritance. A project's own
    # customer_id is NULL in the normal case — the customer is typed once on the folder — so
    # reading the column directly would leave the column almost entirely empty.
    customer_names = {
        customer.id: customer.name
        for customer in (await session.execute(select(Customer))).scalars().all()
    }
    folder_nodes = {
        folder.id: FolderNode(
            folder_id=folder.id,
            parent_id=folder.parent_id,
            customer_id=folder.customer_id,
        )
        for folder in folders.values()
    }

    workbook = new_workbook()
    subtitle = generated_subtitle(f"{len(projects)} Projekte")

    if not projects:
        sheet = workbook.create_sheet("Projekte")
        write_title(sheet, "Projektstand", subtitle)
        sheet.cell(row=4, column=1, value="Keine Projekte vorhanden.")
        return save(workbook)

    # One calendar for the whole report. The commitment check asks whether a PROCESS fits, so it
    # runs against the plant calendar rather than any one person's contract — the same choice the
    # project overview makes.
    working_time = WorkingTimeService(session)
    span_start = min(project.start_date for project in projects)
    span_end = max(
        max((wp.end_date for wp in work_packages), default=span_start),
        max(project.end_date for project in projects),
    )
    await working_time.prepare([], span_start, span_end)

    def _is_working_day(day: date) -> bool:
        profile = working_time.profile_for(_NO_RESOURCE, day)
        return profile is not None and profile.minutes_for_weekday(day.weekday()) > 0

    wp_by_project: dict[UUID, list[WorkPackage]] = {}
    for wp in work_packages:
        wp_by_project.setdefault(wp.project_id, []).append(wp)

    sheet = workbook.create_sheet("Projekte")
    row = write_title(sheet, "Projektstand", subtitle)
    header_row = row
    row = write_header(sheet, _PROJECT_COLUMNS, row)

    for project in sorted(projects, key=lambda p: p.name):
        own = wp_by_project.get(project.id, [])
        done = [wp for wp in own if wp.completed_at is not None]
        breach = assess_commitment(
            project.committed_delivery_date,
            project.end_date,
            None,
            _is_working_day,
        )
        folder = folders.get(project.folder_id) if project.folder_id else None
        row = write_row(
            sheet,
            _PROJECT_COLUMNS,
            [
                folder.name if folder else None,
                project.name,
                customer_names.get(
                    resolve_customer_id(
                        project.customer_id, project.folder_id, folder_nodes
                    )
                    or UUID(int=0)
                ),
                folder.external_ref if folder else None,
                project.external_ref or None,
                project.priority,
                project.start_date,
                project.end_date,
                project.committed_delivery_date,
                breach.working_days_short if breach is not None else None,
                len(own),
                len(done),
                # None rather than 0 for a project with no work packages: 0% progress implies
                # work that has not started, which is a different statement from no work.
                round(len(done) / len(own) * 100, 1) if own else None,
            ],
            row,
        )
    autosize(sheet, _PROJECT_COLUMNS, header_row)

    # --- Work packages, with dependency violations ---
    dependency_service = WorkPackageDependencyService(session)
    wp_by_id = {wp.id: wp for wp in work_packages}
    violations: dict[UUID, int] = {}
    for project in projects:
        for edge in await dependency_service.edges_for_project(project.id):
            predecessor = wp_by_id.get(edge.predecessor_id)
            successor = wp_by_id.get(edge.successor_id)
            if predecessor is None or successor is None:
                continue
            violation = check_violation(
                edge, predecessor.end_date, successor.start_date, _is_working_day
            )
            if violation is not None:
                # Worst violation wins when a work package has several predecessors: that is
                # the number of days it actually has to move.
                violations[successor.id] = max(
                    violations.get(successor.id, 0), violation.working_days_short
                )

    wp_sheet = workbook.create_sheet("Arbeitspakete")
    row = write_title(
        wp_sheet,
        "Arbeitspakete",
        generated_subtitle(f"{len(work_packages)} Arbeitspakete"),
    )
    wp_header = row
    row = write_header(wp_sheet, _WP_COLUMNS, row)
    project_names = {project.id: project.name for project in projects}
    for wp in sorted(
        work_packages, key=lambda w: (project_names.get(w.project_id, ""), w.name)
    ):
        row = write_row(
            wp_sheet,
            _WP_COLUMNS,
            [
                project_names.get(wp.project_id),
                wp.name,
                wp.start_date,
                wp.end_date,
                wp.completed_at.date() if wp.completed_at else None,
                violations.get(wp.id) or None,
            ],
            row,
        )
    autosize(wp_sheet, _WP_COLUMNS, wp_header)

    return save(workbook)
