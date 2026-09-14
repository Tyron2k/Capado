"""When a maintenance job is due.

Capado had the maintenance logic and no way to run it. The audit-log retention has been set to
24 months on the live instance since deployment and **nothing has ever deleted a row** — there
is a script, but no operator ran it. A retention setting that deletes nothing is worse than no
setting, because the number in the compliance document is then a claim rather than a fact.

Deliberately no APScheduler. The whole requirement is "once a day, after a given hour", and
the schedule state has to survive a restart anyway — which means it has to live in the
database, not in a scheduler's memory. Once state is in the database, the scheduler is this
module plus a sleep loop, and a dependency would only hide where the decision is made.

The rules that could each plausibly go the other way:

**A missed day is not made up.** If the container was down for three days, the job runs ONCE
on return, not three times. Pruning older-than-X is not a per-day operation; running it three
times does the same work twice for nothing.

**Catch-up within the day, but no stampede.** A job configured for 02:00 on an instance that
starts at 14:00 having not run today runs immediately — the point of a nightly job is that it
happened, not that it happened at night. One that starts at 01:00 waits, because the hour has
not arrived and running early on the first day would shift the whole cadence.

**A failed run does not count as a run.** Otherwise a job that throws every night reports as
having run for a year while never completing, which is the specific failure this module exists
to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class JobSchedule:
    """When a job should run.

    Attributes:
        name: Stable identifier, used as the run-log key and the advisory-lock key. Renaming
            one makes the scheduler forget it ever ran, so these are not cosmetic.
        hour: Hour of day, 0-23, after which the job may run. Interpreted in the process's
            own clock, which in a container is normally UTC — an operator wanting 02:00 local
            has to account for that, and there is no timezone setting pretending otherwise.
        enabled: Whether to consider it at all.
    """

    name: str
    hour: int
    enabled: bool = True


def is_due(
    schedule: JobSchedule,
    now: datetime,
    last_success: datetime | None,
) -> bool:
    """Whether the job should start now.

    ``last_success`` is the last SUCCESSFUL completion, not the last attempt: a job that
    fails every night must keep being retried rather than counting as done.

    Returns False for a disabled job regardless of how overdue it looks, so switching one off
    is an off switch and not merely a delay.
    """
    if not schedule.enabled:
        return False
    if now.hour < schedule.hour:
        # The configured hour has not arrived today. Running early would shift the cadence
        # permanently on the first day.
        return False
    if last_success is None:
        return True
    # Compared by DATE, not by elapsed hours. "Once per calendar day after hour H" is what an
    # operator means; an elapsed-24h rule drifts the run time later every day until it walks
    # out of the maintenance window entirely.
    return last_success.date() < now.date()


def next_wake_seconds(interval_minutes: int) -> int:
    """How long to sleep between checks.

    A polling loop rather than a computed sleep-until-next-run: the configured hour can change
    while the process is running, and a loop that recomputed a long sleep would honour the old
    setting until it woke. Fifteen minutes of latency on a nightly job costs nothing.
    """
    return max(60, interval_minutes * 60)
