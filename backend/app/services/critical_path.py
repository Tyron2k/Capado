"""Critical path and float over the work package dependency graph.

Two passes, the standard shape: forwards to find the earliest each package can start and
finish, backwards from the project's deadline to find the latest it may. The gap between
them is float — how long a package can slip before the project does. Zero float means the
package is on the critical path, and delaying it delays everything.

Three decisions worth knowing before reading the numbers:

**Duration comes from the lead time when it exists, and from the entered dates otherwise.**
A package that states "34 working days" is describing how long the work takes; one that only
has a start and an end is describing when it was scheduled, which may be longer than the
work needs. Preferring the lead time means the analysis reflects the process rather than the
calendar somebody typed in — and where no lead time is recorded, the entered span is the
only evidence available.

**The backwards pass starts from the COMMITMENT when there is one**, otherwise from the
project's planned end. A critical path measured against a planned end that already misses
the customer date would report comfortable float on a project that is late.

**Everything is in working days.** Float of two means two working days, not two calendar
days that might both be a weekend.

All of it is pure over an ``is_working_day`` predicate and already-loaded rows, so the graph
arithmetic is testable without a database and the calendar stays the caller's choice.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from app.services.dependencies import DependencyEdge
from app.services.lead_time import add_working_days, count_working_days


@dataclass(frozen=True)
class ScheduleNode:
    """The scheduling inputs of one work package."""

    id: UUID
    name: str
    start_date: date
    end_date: date
    lead_time_working_days: int | None = None


@dataclass(frozen=True)
class ScheduleAnalysis:
    """Where one package sits in the schedule.

    Attributes:
        earliest_start: First day it could begin, given its predecessors.
        earliest_finish: First day it could be done.
        latest_start: Last day it may begin without pushing the deadline.
        latest_finish: Last day it may be done.
        float_working_days: Working days it can slip before the project does. Negative
            means the deadline is already unreachable through this package — the chain
            leading to it is longer than the time available.
        is_critical: Float of zero or less. Delaying this package delays the project.
    """

    id: UUID
    name: str
    earliest_start: date
    earliest_finish: date
    latest_start: date
    latest_finish: date
    float_working_days: int
    is_critical: bool


def duration_working_days(
    node: ScheduleNode, is_working_day: Callable[[date], bool]
) -> int:
    """How many working days the package occupies.

    The recorded lead time wins over the entered dates: it describes how long the work
    takes, while the dates describe when somebody scheduled it — which may be longer
    than the work needs and would then hide float that really exists.

    Falls back to the entered span, and to one day when that span contains no working
    day at all. Zero would let a package finish before it starts, which no downstream
    arithmetic expects.
    """
    if node.lead_time_working_days is not None and node.lead_time_working_days > 0:
        return node.lead_time_working_days
    span = count_working_days(node.start_date, node.end_date, is_working_day)
    return max(span, 1)


def _finish_from(
    start: date, duration: int, is_working_day: Callable[[date], bool]
) -> date | None:
    """The day a package of this duration finishes if it starts on ``start``."""
    return add_working_days(start, duration, is_working_day)


def analyse(
    nodes: list[ScheduleNode],
    edges: list[DependencyEdge],
    deadline: date,
    is_working_day: Callable[[date], bool],
) -> list[ScheduleAnalysis]:
    """Forward and backward pass over the graph.

    Args:
        nodes: Work packages to analyse. Packages referenced by an edge but absent here
            are ignored, so a link crossing a project boundary does not break the pass.
        edges: Finish-to-start links with their lags.
        deadline: The date the last package must be finished by — the commitment where
            one exists, otherwise the project's planned end.
        is_working_day: Whether a date grants working time.

    Returns:
        One entry per node, in the order given. Empty when the calendar defines no
        working days, because every date would then be unreachable and reporting float
        against nothing would be misleading.

    A cycle in the input cannot happen through the service, which refuses one at the
    write. If corrupt data contains one, the passes visit each node once and leave the
    unreachable part with its own start as its earliest — degraded, but terminating.
    """
    if not nodes:
        return []

    by_id = {n.id: n for n in nodes}
    known = set(by_id)
    relevant = [
        e for e in edges if e.predecessor_id in known and e.successor_id in known
    ]

    durations: dict[UUID, int] = {
        n.id: duration_working_days(n, is_working_day) for n in nodes
    }

    predecessors: dict[UUID, list[DependencyEdge]] = {n.id: [] for n in nodes}
    successors: dict[UUID, list[DependencyEdge]] = {n.id: [] for n in nodes}
    for edge in relevant:
        predecessors[edge.successor_id].append(edge)
        successors[edge.predecessor_id].append(edge)

    order = _topological(nodes, relevant)

    # --- forward pass ---
    earliest_start: dict[UUID, date] = {}
    earliest_finish: dict[UUID, date] = {}
    for node_id in order:
        node = by_id[node_id]
        candidates = [node.start_date]
        for edge in predecessors[node_id]:
            pred_finish = earliest_finish.get(edge.predecessor_id)
            if pred_finish is None:
                continue
            after = add_working_days(
                pred_finish + timedelta(days=1),
                edge.lag_working_days + 1,
                is_working_day,
            )
            if after is not None:
                candidates.append(after)
        start = max(candidates)
        finish = _finish_from(start, durations[node_id], is_working_day)
        if finish is None:
            # No working day within the lookahead bound: the calendar is unusable.
            return []
        earliest_start[node_id] = start
        earliest_finish[node_id] = finish

    # --- backward pass ---
    latest_finish: dict[UUID, date] = {}
    latest_start: dict[UUID, date] = {}
    for node_id in reversed(order):
        candidates = [deadline]
        for edge in successors[node_id]:
            succ_start = latest_start.get(edge.successor_id)
            if succ_start is None:
                continue
            # Inverse of the forward step. Forwards, the successor's earliest start is
            # the (lag + 1)-th working day at or after the predecessor's finish plus one
            # day. Backwards, the predecessor's latest finish is the (lag + 1)-th
            # working day at or BEFORE the successor's start minus one day. Anchoring on
            # the successor's start itself instead is the off-by-one that makes every
            # float one day too generous.
            candidates.append(
                _working_days_before(
                    succ_start - timedelta(days=1),
                    edge.lag_working_days + 1,
                    is_working_day,
                )
            )
        finish = min(candidates)
        # Counted INCLUSIVE of the finish day: a one-day package starts and finishes on
        # the same day, so a duration of n spans n working days ending on `finish`.
        start = _working_days_before(finish, durations[node_id], is_working_day)
        latest_finish[node_id] = finish
        latest_start[node_id] = start

    results: list[ScheduleAnalysis] = []
    for node in nodes:
        es = earliest_start[node.id]
        ls = latest_start[node.id]
        if ls >= es:
            slack = count_working_days(es, ls, is_working_day) - 1
        else:
            # The deadline is already unreachable through this package.
            slack = -(count_working_days(ls, es, is_working_day) - 1)
        results.append(
            ScheduleAnalysis(
                id=node.id,
                name=node.name,
                earliest_start=es,
                earliest_finish=earliest_finish[node.id],
                latest_start=ls,
                latest_finish=latest_finish[node.id],
                float_working_days=slack,
                is_critical=slack <= 0,
            )
        )
    return results


def _working_days_before(
    reference: date, working_days: int, is_working_day: Callable[[date], bool]
) -> date:
    """The date ``working_days`` working days before ``reference``, inclusive of it.

    Walks backwards rather than using arithmetic, because the calendar is arbitrary:
    holidays and designated working Saturdays mean no fixed offset is correct. Bounded
    the same way the forward walk is, so a calendar with no working days degrades to the
    reference date instead of looping.
    """
    if working_days <= 0:
        return reference
    remaining = working_days
    current = reference
    for _ in range(3660):
        if is_working_day(current):
            remaining -= 1
            if remaining == 0:
                return current
        current -= timedelta(days=1)
    return reference


def _topological(nodes: list[ScheduleNode], edges: list[DependencyEdge]) -> list[UUID]:
    """Node ids with every predecessor before its successors.

    Kahn's algorithm. Nodes still carrying an unmet predecessor when the queue empties
    are appended in their original order — that only happens for a cycle, which the
    service refuses, and appending beats dropping them from the analysis entirely.
    """
    indegree: dict[UUID, int] = {n.id: 0 for n in nodes}
    outgoing: dict[UUID, list[UUID]] = {n.id: [] for n in nodes}
    for edge in edges:
        indegree[edge.successor_id] += 1
        outgoing[edge.predecessor_id].append(edge.successor_id)

    queue = [n.id for n in nodes if indegree[n.id] == 0]
    order: list[UUID] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt in outgoing[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) < len(nodes):
        placed = set(order)
        order.extend(n.id for n in nodes if n.id not in placed)
    return order
