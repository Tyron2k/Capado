"""SQLAlchemy entities for plan baselines.

A baseline is a frozen snapshot of the schedule — projects, work packages and
assignments — against which the live plan can be compared. It answers "what did we
agree", where the audit trail answers "who changed it and why" (ADR-007).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.utils.utc_datetime import UTCDateTime

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


class Baseline(ORMModel, kw_only=True, eq=False):
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

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(
        sa.String(1000), nullable=True, default=None
    )
    created_by: Mapped[UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id"), nullable=True, index=True, default=None
    )
    is_current: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, index=True, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        index=True,
        default_factory=_utcnow,
        insert_default=_utcnow,
    )


class BaselineEntry(ORMModel, kw_only=True, eq=False):
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
    __table_args__ = (
        sa.UniqueConstraint(
            "baseline_id", "entity_type", "entity_id", name="uq_baseline_entries_entity"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    baseline_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "baselines.id", name="baseline_entries_baseline_id_fkey", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    entity_id: Mapped[UUID] = mapped_column(sa.Uuid(), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        sa.JSON, nullable=False, default_factory=dict, insert_default=dict
    )
