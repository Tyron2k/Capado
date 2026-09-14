"""The week a team actually works: one row per person, one column per day.

This is deliberately not the resource Gantt. A Gantt answers "when does this work package run",
grouped by project and drawn as bars over a timeline; a shift list answers "who does what on
Tuesday", and the two are different enough that reshaping one into the other would produce a
worse version of both. The Gantt is for a planner at a screen; this is for a sheet on a wall.

Pure over already-loaded values, so the layout rules are testable without a database.

The rules that matter, and what each one refuses:

**A day shows every assignment, not the largest one.** Somebody split across two work packages
has two entries in that cell, because a shift list that silently shows one of them is worse than
one that looks crowded — the person would turn up for half their day.

**Absence and work are shown together, not exclusively.** A 50% absence still leaves half a day
of work, and suppressing the assignment because "they are away" is how somebody ends up not
being told about work that is still planned.

**Days with no calendar time are marked, not blank.** A blank cell reads as "nothing planned",
which is indistinguishable from "the plant is closed". A works holiday and an empty Tuesday are
different messages to somebody reading the sheet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID


@dataclass(frozen=True)
class DayEntry:
    """One thing a person does on one day."""

    work_package_name: str
    project_name: str
    allocation_percent: float


@dataclass
class DayCell:
    """One person on one day.

    Attributes:
        day: The date.
        entries: Everything assigned that day, in the order given. Empty is a valid answer.
        absence_percent: How much of the day is blocked, 0-100.
        provisional_percent: How much of that block is still only requested — the part a
            foreman could still renegotiate.
        is_working_day: Whether the calendar grants any time at all. False for a weekend or a
            works holiday, which is a different message from "nothing planned".
    """

    day: date
    entries: list[DayEntry] = field(default_factory=list)
    absence_percent: float = 0.0
    provisional_percent: float = 0.0
    is_working_day: bool = True

    @property
    def assigned_percent(self) -> float:
        """Total allocation asked of this person that day."""
        return sum(entry.allocation_percent for entry in self.entries)

    @property
    def is_overbooked(self) -> bool:
        """Whether the day asks for more than what is left after absences.

        Computed here rather than server-side-only because the sheet is the place a foreman
        would notice it, and a row that quietly asks for 130% of somebody teaches the reader
        to distrust the sheet.
        """
        if not self.is_working_day:
            return self.assigned_percent > 0
        return self.assigned_percent > (100.0 - self.absence_percent) + 0.01


@dataclass
class PersonRow:
    """One person's week."""

    resource_id: UUID
    name: str
    cells: list[DayCell]

    @property
    def has_anything(self) -> bool:
        """Whether this row carries any information at all.

        Used to decide whether to print an empty row rather than to drop it: somebody with
        nothing planned all week is exactly what a foreman needs to see, so the caller keeps
        the row and the sheet says "free".
        """
        return any(cell.entries or cell.absence_percent > 0 for cell in self.cells)


def week_days(anchor: date) -> list[date]:
    """The seven days of the ISO week containing ``anchor``, Monday first.

    Always seven, including the weekend. A shift list that omits Saturday cannot show weekend
    work, and weekend work is exactly the thing somebody needs warning about.
    """
    monday = anchor - timedelta(days=anchor.weekday())
    return [monday + timedelta(days=offset) for offset in range(7)]


def build_rows(
    days: list[date],
    people: list[tuple[UUID, str]],
    entries_by_person_day: dict[tuple[UUID, date], list[DayEntry]],
    absence_by_person_day: dict[tuple[UUID, date], tuple[float, float]],
    working_day_by_person_day: dict[tuple[UUID, date], bool],
) -> list[PersonRow]:
    """Assemble the grid.

    Every person gets a row and every row gets a cell per day, even when empty. A sparse
    structure would push "is this person free or missing from the data" onto whoever reads it.

    People are returned in the order given, so the caller decides the sort — a sheet posted on
    a wall is read by name, and re-sorting by workload would move rows week to week.
    """
    rows: list[PersonRow] = []
    for resource_id, name in people:
        cells: list[DayCell] = []
        for day in days:
            absence, provisional = absence_by_person_day.get(
                (resource_id, day), (0.0, 0.0)
            )
            cells.append(
                DayCell(
                    day=day,
                    entries=list(entries_by_person_day.get((resource_id, day), ())),
                    absence_percent=absence,
                    provisional_percent=provisional,
                    is_working_day=working_day_by_person_day.get(
                        (resource_id, day), True
                    ),
                )
            )
        rows.append(PersonRow(resource_id=resource_id, name=name, cells=cells))
    return rows
