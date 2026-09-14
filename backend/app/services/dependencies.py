"""Dependencies between work packages, and when the dates violate them.

One relationship type: **finish to start**, with an optional lag in working days.

That is not a simplification for its own sake. Start-to-start and finish-to-finish are
expressible by reordering the pair, and start-to-finish is almost never what anybody
means. What a plant actually needs beyond finish-to-start is *waiting time* — paint has to
cure before the next step can begin — and a lag covers that without a second relationship
type. Working days rather than calendar days, for the same reason the rest of the schedule
uses them: a weekend is not curing time anybody planned.

A violated dependency is a **warning**, not a rejected edit. Enforcing it would mean the
system reschedules work on the planner's behalf, and a planner who cannot enter what they
actually intend to do goes back to the spreadsheet — the same failure a hard plan freeze
would cause (ADR-007).

Cycles are the exception: they are refused at the write, because a cycle has no valid
reading at all and every consumer would otherwise have to defend against it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from app.services.lead_time import add_working_days, count_working_days


@dataclass(frozen=True)
class DependencyEdge:
    """One finish-to-start link, independent of the ORM."""

    predecessor_id: UUID
    successor_id: UUID
    lag_working_days: int = 0


@dataclass(frozen=True)
class DependencyViolation:
    """A successor that starts before its predecessor allows."""

    predecessor_id: UUID
    successor_id: UUID
    predecessor_end: date
    successor_start: date
    lag_working_days: int
    earliest_start: date
    working_days_short: int


def successors_of(node_id: UUID, edges: list[DependencyEdge]) -> list[UUID]:
    """Direct successors of one work package."""
    return [e.successor_id for e in edges if e.predecessor_id == node_id]


def reaches(start_id: UUID, target_id: UUID, edges: list[DependencyEdge]) -> bool:
    """Whether following successors from ``start_id`` arrives at ``target_id``.

    Breadth-first with a visited set, so corrupt data containing a cycle terminates
    instead of looping. That matters even though cycles are refused at the write: a
    reader must not hang on data a previous version of the code let through.
    """
    if start_id == target_id:
        return True
    seen: set[UUID] = {start_id}
    queue: list[UUID] = [start_id]
    while queue:
        current = queue.pop(0)
        for nxt in successors_of(current, edges):
            if nxt == target_id:
                return True
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append(nxt)
    return False


def would_create_cycle(
    predecessor_id: UUID, successor_id: UUID, edges: list[DependencyEdge]
) -> bool:
    """Whether adding this link would close a loop.

    Checked before the write. A cycle has no valid reading — "A after B after A" cannot
    be scheduled at all — so unlike a date conflict it is not something to warn about
    and carry.
    """
    if predecessor_id == successor_id:
        return True
    # A cycle appears exactly when the successor already reaches the predecessor.
    return reaches(successor_id, predecessor_id, edges)


def earliest_successor_start(
    predecessor_end: date, lag_working_days: int, is_working_day: Callable[[date], bool]
) -> date | None:
    """The first day the successor may start.

    With no lag, that is the next working day after the predecessor ends — a successor
    starting the same day would mean the two overlap, which finish-to-start denies by
    definition.

    A lag of two means two further working days pass first, so curing time is not
    silently satisfied by a weekend.

    Returns None when no working day can be found within the lookahead bound, which
    means the calendar defines none at all.
    """
    if lag_working_days < 0:
        lag_working_days = 0
    return add_working_days(
        predecessor_end + timedelta(days=1), lag_working_days + 1, is_working_day
    )


def check_violation(
    edge: DependencyEdge,
    predecessor_end: date,
    successor_start: date,
    is_working_day: Callable[[date], bool],
) -> DependencyViolation | None:
    """Whether the successor starts too early for its predecessor.

    Returns None when the dates are consistent, or when the calendar cannot produce an
    earliest start — a broken calendar is not evidence of a scheduling mistake.

    The shortfall is the number of working days the successor would have to move,
    counted from the day after its current start. That is the number someone acts on;
    calendar days would include days nobody works and overstate the fix.
    """
    earliest = earliest_successor_start(
        predecessor_end, edge.lag_working_days, is_working_day
    )
    if earliest is None or successor_start >= earliest:
        return None

    shortfall = count_working_days(
        successor_start + timedelta(days=1), earliest, is_working_day
    )
    return DependencyViolation(
        predecessor_id=edge.predecessor_id,
        successor_id=edge.successor_id,
        predecessor_end=predecessor_end,
        successor_start=successor_start,
        lag_working_days=edge.lag_working_days,
        earliest_start=earliest,
        working_days_short=shortfall,
    )
