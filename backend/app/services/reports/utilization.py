"""The utilization report: weeks across, people down.

Calls :meth:`CapacityService.get_weekly_utilization` per resource — the same method the dashboard
charts use, so a number in this file and the same number on screen come from one implementation.
Recomputing here would give the two a chance to disagree, and a spreadsheet that contradicts the
dashboard is worse than no spreadsheet: somebody has to decide which one lies.

Two sheets, because two different people read this. The wide sheet is for looking at: one row per
person, one column per week, percentages. The long sheet is for working with: one row per
person-week, which is the shape a pivot table needs — a wide sheet cannot be pivoted, and asking a
controller to unpivot it by hand is how the numbers get retyped and go wrong.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from openpyxl.styles import PatternFill
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.resource import PersonalResource
from app.models.resource_group import ResourceGroup
from app.services.capacity_service import CapacityService, WeeklyUtilization
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

# Only the overbooked case is filled. Shading every cell by utilization turns the sheet into a
# heat map nobody can read in print and hides the one state that needs acting on.
_OVER_FILL = PatternFill("solid", fgColor="FFC7CE")

_LONG_COLUMNS = [
    Column("Gruppe"),
    Column("Person"),
    Column("Woche ab", "DD.MM.YYYY"),
    Column("Kalenderjahr-KW"),
    Column("Verfügbar (h)", "0.0"),
    Column("Verplant (h)", "0.0"),
    Column("Auslastung %", "0.0"),
    Column("Überbuchung %", "0.0"),
    Column("Arbeitstage", "0"),
]


def _mondays(start: date, end: date) -> list[date]:
    """Mondays from the week containing ``start`` to the week containing ``end``."""
    current = start - timedelta(days=start.weekday())
    last = end - timedelta(days=end.weekday())
    weeks: list[date] = []
    while current <= last:
        weeks.append(current)
        current += timedelta(days=7)
    return weeks


async def build_utilization_report(
    session: AsyncSession,
    start: date,
    end: date,
    group_id: UUID | None = None,
) -> bytes:
    """Build the workbook.

    ``group_id`` narrows to one group; omitted, the report covers everybody. Not defaulted to a
    group, because "the whole works" is the question a management report is usually asked.
    """
    weeks = _mondays(start, end)

    statement = select(PersonalResource, ResourceGroup).join(
        ResourceGroup, PersonalResource.group_id == ResourceGroup.id
    )
    if group_id is not None:
        statement = statement.where(PersonalResource.group_id == group_id)
    statement = statement.order_by(
        ResourceGroup.name.asc(), PersonalResource.name.asc()
    )
    people = list((await session.execute(statement)).all())

    capacity = CapacityService(session)
    # resource_id -> week_start -> the weekly figures. Typed concretely rather than as
    # object: the attribute accesses below are the whole point of the dict, and object
    # silences exactly the check that would catch a renamed field.
    per_person: dict[UUID, dict[date, WeeklyUtilization]] = {}
    for person, _group in people:
        rows = await capacity.get_weekly_utilization(person.id, start, end)
        per_person[person.id] = {row.week_start: row for row in rows}

    workbook = new_workbook()
    covers = f"{start.isoformat()} bis {end.isoformat()}"
    if group_id is not None and people:
        covers = f"{people[0][1].name}, {covers}"

    # --- Wide sheet: for reading ---
    wide = workbook.create_sheet("Auslastung")
    row = write_title(
        wide, "Auslastung je Person und Woche", generated_subtitle(covers)
    )
    wide_columns = [Column("Gruppe"), Column("Person")] + [
        Column(f"KW {week.isocalendar().week}", "0.0") for week in weeks
    ]
    header_row = row
    row = write_header(wide, wide_columns, row)
    for person, group in people:
        values: list[object] = [group.name, person.name]
        for week in weeks:
            weekly = per_person[person.id].get(week)
            # None rather than 0 for a week with no data: an empty cell says "not computed",
            # a 0 says "idle", and printing 0 for the former would invent idleness.
            values.append(round(weekly.utilization, 1) if weekly is not None else None)
        written_row = row
        row = write_row(wide, wide_columns, values, row)
        for index, week in enumerate(weeks, start=3):
            weekly = per_person[person.id].get(week)
            if weekly is not None and weekly.overbooked > 0:
                wide.cell(row=written_row, column=index).fill = _OVER_FILL
    autosize(wide, wide_columns, header_row)

    # --- Long sheet: for pivoting ---
    long = workbook.create_sheet("Auslastung (Pivot)")
    row = write_title(
        long,
        "Auslastung, eine Zeile je Person und Woche",
        generated_subtitle(covers),
    )
    long_header = row
    row = write_header(long, _LONG_COLUMNS, row)
    for person, group in people:
        for week in weeks:
            weekly = per_person[person.id].get(week)
            if weekly is None:
                continue
            row = write_row(
                long,
                _LONG_COLUMNS,
                [
                    group.name,
                    person.name,
                    week,
                    # Written as text on purpose: "2026-35" is a label, and Excel would read
                    # 2026-35 as a date or a subtraction.
                    f"{week.isocalendar().year}-{week.isocalendar().week:02d}",
                    round(weekly.available_minutes / 60, 1),
                    round(weekly.assigned_minutes / 60, 1),
                    round(weekly.utilization, 1),
                    round(weekly.overbooked, 1),
                    weekly.working_days,
                ],
                row,
            )
    autosize(long, _LONG_COLUMNS, long_header)

    return save(workbook)
