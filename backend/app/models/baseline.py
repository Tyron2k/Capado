"""SQLModel entities for plan baselines.

A baseline is a frozen snapshot of the schedule — projects, work packages and
assignments — against which the live plan can be compared. It answers "what did we
agree", where the audit trail answers "who changed it and why" (ADR-007).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel

# What a baseline captures. Absences and working-time configuration are
# deliberately absent: they are facts about the world rather than statements about
# the plan, and their effect surfaces as a conflict or as an assignment somebody
# moved. Requirements are scope rather than schedule and are the most likely first
# addition — adding them here needs no migration.
BASELINE_ENTITY_TYPES: tuple[str, ...] = (
    "projects",
    "work_packages",
    "assignments",
)


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Baseline(SQLModel, table=True):
    """A named, frozen state of the plan.

    Creating one does not lock anything. A hard freeze on a live production plan
    moves the next change into a spreadsheet instead of preventing it, and then
    plan and reality diverge invisibly — which is the failure a baseline exists to
    expose. The deliverable is the diff, not the prohibition (ADR-007).

    Attributes:
        name: What this baseline is, e.g. "Planstand KW 34".
        note: Optional context — why it was taken, what was agreed.
        created_by: The user who froze the plan, or NULL if taken by a script.
        is_current: Marks the baseline drift is shown against by default, so a
            user is never asked to pick a comparison point just to see whether the
            plan moved. At most one baseline carries it.
    """

    __tablename__ = "baselines"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255)
    note: str | None = Field(default=None, max_length=1000)
    created_by: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    is_current: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=_utcnow, index=True)


class BaselineEntry(SQLModel, table=True):
    """One captured entity inside a baseline.

    Rows are immutable. Nothing edits a snapshot: a wrong baseline is superseded by
    a new one rather than corrected, because correcting history would remove the
    only reason to keep it.

    Attributes:
        entity_type: Table name of the captured entity.
        entity_id: Primary key of the captured row.
        payload: The field values at freeze time. Generic JSON rather than typed
            columns so that widening what a baseline captures is a change to one
            function instead of a migration.
    """

    __tablename__ = "baseline_entries"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    baseline_id: UUID = Field(foreign_key="baselines.id", index=True)
    entity_type: str = Field(max_length=64, index=True)
    entity_id: UUID = Field(index=True)
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(sa.JSON, nullable=False)
    )
