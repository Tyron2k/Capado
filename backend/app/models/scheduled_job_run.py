"""Record of what the scheduler actually did.

This table is the point of the whole feature. The failure being fixed is not "there is no
scheduler" but "the retention setting says 24 months and nobody can tell whether anything was
ever deleted". A scheduler whose runs cannot be inspected reproduces that failure one level up:
it would be a new claim rather than a new fact.

So every attempt is written, including failures, and the row is written BEFORE the job runs
(status ``running``) and updated after. A job that hangs or a container killed mid-run therefore
leaves a visible ``running`` row rather than no trace at all — the one state that is otherwise
indistinguishable from "never started".
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """UTC timestamp as naive datetime (for TIMESTAMP WITHOUT TIME ZONE)."""
    return datetime.now(UTC).replace(tzinfo=None)


class JobRunStatus(StrEnum):
    """Outcome of one scheduled run.

    ``running`` is a real persisted state, not a transient one: it is what a killed container
    leaves behind, and treating it as impossible is how a hung job becomes invisible.
    """

    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class ScheduledJobRun(SQLModel, table=True):
    """One attempt at one scheduled job.

    Attributes:
        job_name: Which job. Matches JobSchedule.name; renaming one makes the scheduler
            forget it ever ran, so the names are part of the contract.
        started_at: When the attempt began.
        finished_at: When it ended, or NULL while running / after an unclean stop.
        status: See JobRunStatus.
        items_affected: How many rows the job touched. 0 is a meaningful answer (nothing was
            old enough yet) and is deliberately distinguished from NULL (the job did not get
            far enough to know).
        detail: Human-readable outcome or error message. Truncated rather than unbounded: a
            stack trace belongs in the log, and an unbounded column here would let a
            repeating failure grow the table without limit.
    """

    __tablename__ = "scheduled_job_runs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_name: str = Field(max_length=100, index=True, nullable=False)
    started_at: datetime = Field(default_factory=_utcnow, index=True)
    finished_at: datetime | None = Field(default=None)
    status: str = Field(default=JobRunStatus.running, max_length=20, nullable=False)
    items_affected: int | None = Field(default=None)
    detail: str = Field(default="", max_length=1000, nullable=False)
