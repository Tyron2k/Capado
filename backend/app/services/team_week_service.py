"""Load one team's week for the printable sheet.

Separate from :mod:`app.services.team_week`, which holds the layout rules and is pure. This file
queries and hands over; it decides nothing.

Availability comes from :class:`WorkingTimeService`, the same service the capacity screens use, so
a works holiday or a part-time profile shows up on the sheet exactly as it does in the
arithmetic. Re-deriving "does this person work on Tuesday" here would create a second answer to a
question that already has one, and the sheet would drift from the plan it is supposed to
communicate.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.assignment import Assignment, ResourceType
from app.models.project import Project, WorkPackage
from app.models.resource import PersonalResource
from app.models.resource_group import ResourceGroup
from app.services.team_week import DayEntry, PersonRow, build_rows, week_days
from app.services.working_time_service import WorkingTimeService


async def group_name(session: AsyncSession, group_id: UUID) -> str:
    """The group's name, for the sheet's heading."""
    result = await session.execute(
        select(ResourceGroup).where(ResourceGroup.id == group_id)
    )
    group = result.scalars().first()
    return group.name if group else ""


async def build_team_week(
    session: AsyncSession,
    group_id: UUID,
    anchor: date,
) -> tuple[list[date], list[PersonRow]]:
    """The week's grid for one resource group.

    Returns the days and the rows. People are sorted by name, because a sheet posted on a wall
    is read by name and any workload-based order would move rows from week to week.
    """
    days = week_days(anchor)
    window_start, window_end = days[0], days[-1]

    people_result = await session.execute(
        select(PersonalResource)
        .where(PersonalResource.group_id == group_id)
        .order_by(PersonalResource.name.asc())
    )
    people = list(people_result.scalars().all())
    if not people:
        return days, []

    resource_ids = [person.id for person in people]

    # Assignments overlapping the week. Only personal rows: this is a shift list for people, and
    # an infrastructure booking has no person to put in a row.
    assignment_result = await session.execute(
        select(Assignment, WorkPackage, Project)
        .join(WorkPackage, Assignment.work_package_id == WorkPackage.id)
        .join(Project, WorkPackage.project_id == Project.id)
        .where(
            Assignment.resource_id.in_(resource_ids),
            Assignment.resource_type == ResourceType.personal,
            Assignment.start_date <= window_end,
            Assignment.end_date >= window_start,
        )
    )

    entries: dict[tuple[UUID, date], list[DayEntry]] = {}
    for assignment, work_package, project in assignment_result.all():
        if assignment.start_date is None or assignment.end_date is None:
            continue
        entry = DayEntry(
            work_package_name=work_package.name,
            project_name=project.name,
            allocation_percent=assignment.allocation_percent or 0.0,
        )
        # Expanded per day rather than stored as a span: the sheet is a grid, and every
        # consumer would otherwise have to redo this expansion, including the print CSS.
        for day in days:
            if assignment.start_date <= day <= assignment.end_date:
                entries.setdefault((assignment.resource_id, day), []).append(entry)

    working_time = WorkingTimeService(session)
    await working_time.prepare(resource_ids, window_start, window_end)

    absences: dict[tuple[UUID, date], tuple[float, float]] = {}
    working_days: dict[tuple[UUID, date], bool] = {}
    for resource_id in resource_ids:
        for day in days:
            absence = working_time.absence_percent(resource_id, day)
            if absence > 0:
                absences[(resource_id, day)] = (
                    absence,
                    working_time.provisional_percent(resource_id, day),
                )
            working_days[(resource_id, day)] = working_time.is_working_day(
                resource_id, day
            )

    rows = build_rows(
        days=days,
        people=[(person.id, person.name) for person in people],
        entries_by_person_day=entries,
        absence_by_person_day=absences,
        working_day_by_person_day=working_days,
    )
    return days, rows
