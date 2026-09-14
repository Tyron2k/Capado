"""Lead time in working days, and the lateness warning it produces.

The templates already state their duration in *working* days — "34 Arbeitstage
Durchlaufzeit" appears dozens of times in the reference set — and until the calendar
existed there was no way to honour that. Planning 34 working days as 34 calendar
days compresses roughly seven weeks into five, which is a two-week underestimate
per unit hiding in data that was already there.

The entered end date stays authoritative. A derived date that lands later does not
overwrite it; it raises a warning, because the plan is then late and someone has to
act. Silently moving the date would hide exactly the fact worth surfacing — the same
reason a baseline marks rather than locks (ADR-007).

Everything here is pure over an ``is_working_day`` predicate, so the arithmetic is
testable without a database and the calendar source stays the caller's choice.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

# A guard against walking forever when the predicate never returns True — a site
# whose calendar marks every day non-working, or a profile of all zeros. Ten years
# is far past any plausible lead time, so hitting it means the data is wrong, not
# that the answer was just far away.
MAX_LOOKAHEAD_DAYS = 3660


@dataclass(frozen=True)
class ScheduleWarning:
    """A work package whose working-day lead time does not fit its dates."""

    derived_end: date
    entered_end: date
    working_days_short: int


def add_working_days(
    start: date, working_days: int, is_working_day: Callable[[date], bool]
) -> date | None:
    """The date on which the given number of working days is completed.

    Args:
        start: First candidate day. Counted if it is a working day, because a job
            starting on a Monday spends that Monday on the work.
        working_days: How many working days the process takes. One means the work
            finishes on the first working day at or after ``start``.
        is_working_day: Whether a date grants working time.

    Returns:
        The date the last working day falls on, or None when ``working_days`` is
        below one, or when no calendar of working days can be found within
        :data:`MAX_LOOKAHEAD_DAYS`.

    Inclusive of the start day rather than exclusive: a one-day job beginning on a
    working Monday finishes that Monday, and an off-by-one here would shift every
    computed end date by a day.
    """
    if working_days < 1:
        return None

    remaining = working_days
    current = start
    for _ in range(MAX_LOOKAHEAD_DAYS):
        if is_working_day(current):
            remaining -= 1
            if remaining == 0:
                return current
        current += timedelta(days=1)
    return None


def count_working_days(
    start: date, end: date, is_working_day: Callable[[date], bool]
) -> int:
    """Working days in an inclusive range, or 0 when the range is inverted."""
    if end < start:
        return 0
    total = 0
    current = start
    while current <= end:
        if is_working_day(current):
            total += 1
        current += timedelta(days=1)
    return total


@dataclass(frozen=True)
class CommitmentBreach:
    """A committed delivery date the plan does not meet.

    Attributes:
        committed: What was promised.
        planned_end: What the plan currently says.
        derived_end: Where the working-day lead times actually land, when they are
            recorded. None when no work package claims a duration.
        working_days_short: The gap against the commitment, in working days.
        hidden: True when the PLANNED dates meet the commitment and only the lead
            times do not. That is the dangerous case — the plan looks fine on every
            report, and the overrun only appears once the work is under way.
    """

    committed: date
    planned_end: date
    derived_end: date | None
    working_days_short: int
    hidden: bool


def assess_commitment(
    committed: date | None,
    planned_end: date,
    derived_end: date | None,
    is_working_day: Callable[[date], bool],
) -> CommitmentBreach | None:
    """Whether a promised delivery date is still met.

    Two different failures, deliberately reported as one type with a discriminator
    rather than as two, because the recipient acts the same way and only the urgency
    differs:

    - The plan itself already ends after the commitment. Visible to anyone reading the
      dates, and usually already known.
    - The plan ends in time but the recorded working-day lead times do not support it.
      Nothing on a date-based report shows this, which is why ``hidden`` exists.

    Returns None when there is no commitment to miss, or when both the plan and the
    durations fit. A project with no committed date is not a project running late; it
    is a project nobody promised anything about.

    The commitment is never adjusted. It is the one date in the system that belongs to
    somebody outside it.
    """
    if committed is None:
        return None

    late_by_plan = planned_end > committed
    late_by_lead_time = derived_end is not None and derived_end > committed
    if not late_by_plan and not late_by_lead_time:
        return None

    # Measure against whichever end is later: reporting the smaller gap would
    # understate a project that is late on both counts.
    effective_end = planned_end
    if derived_end is not None and derived_end > effective_end:
        effective_end = derived_end

    shortfall = count_working_days(
        committed + timedelta(days=1), effective_end, is_working_day
    )
    return CommitmentBreach(
        committed=committed,
        planned_end=planned_end,
        derived_end=derived_end,
        working_days_short=shortfall,
        hidden=not late_by_plan,
    )


def schedule_warning(
    start: date,
    entered_end: date,
    lead_time_working_days: int | None,
    is_working_day: Callable[[date], bool],
) -> ScheduleWarning | None:
    """Whether a working-day lead time overruns the entered end date.

    Returns None when there is nothing to check — no lead time recorded — or when
    the work fits. A warning carries the shortfall in working days, because that is
    the unit the process is expressed in and the number someone can act on: "three
    working days short" says what to recover, where "three days late" does not.

    The entered end is never adjusted. It is a commitment, and a computation that
    silently rewrote it would remove the discrepancy instead of reporting it.
    """
    if lead_time_working_days is None or lead_time_working_days < 1:
        return None

    derived_end = add_working_days(start, lead_time_working_days, is_working_day)
    if derived_end is None or derived_end <= entered_end:
        return None

    # The gap is measured in working days from the day after the commitment, so a
    # weekend between the two dates does not inflate it.
    shortfall = count_working_days(
        entered_end + timedelta(days=1), derived_end, is_working_day
    )
    return ScheduleWarning(
        derived_end=derived_end,
        entered_end=entered_end,
        working_days_short=shortfall,
    )
