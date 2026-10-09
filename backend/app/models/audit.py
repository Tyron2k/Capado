"""SQLAlchemy entity for the audit trail.

One generic table rather than per-entity history, because the questions asked of
it cross entities — who changed anything on Friday, what did this user touch (see
ADR-006).
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.utils.utc_datetime import UTCDateTime

# Entities deliberately NOT audited: they are recomputed rather than edited, so a
# log of them would describe derivations instead of decisions. `refresh_conflicts`
# deletes and re-inserts every conflict for a resource on each assignment change,
# which would bury the entries someone is actually looking for.
UNAUDITED_TABLES = frozenset(
    {
        "conflicts",
        "conflict_assignments",
        "audit_log",
        # A baseline writes one entry per assignment, work package and project —
        # thousands of immutable snapshot rows per freeze. Auditing them would bury
        # every other entry. The `baselines` header IS audited: who froze the plan
        # and when is the decision, and exactly the kind of thing that gets
        # disputed.
        "baseline_entries",
    }
)


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class AuditAction(StrEnum):
    """What happened to the entity."""

    created = "created"
    updated = "updated"
    deleted = "deleted"


class AuditLog(ORMModel, kw_only=True, eq=False):
    """One recorded change to one entity.

    Written by the ``before_flush`` listener in :mod:`app.services.audit`, inside
    the same transaction as the change itself. An entry outside the transaction
    would survive a rollback and describe something that never happened.

    Attributes:
        entity_type: Table name of the changed entity, e.g. ``assignments``.
        entity_id: Primary key of the changed row.
        action: created, updated or deleted.
        actor_id: The user who made the change, or NULL for unauthenticated
            writes (initial setup, a login storing a refresh token) and for
            scripts writing through the session factory directly. NULL is
            accurate there rather than missing — there is no actor.
        reason: Optional intent, set by a service on the session before flushing.
            A listener can see that an assignment moved; only the caller knows
            whether it moved to resolve a conflict or because a customer changed
            a date.
        changes: Per-attribute ``{"field": {"from": ..., "to": ...}}``. Empty for
            a delete, where the row itself is the information. Values are
            JSON-encoded, so a date arrives back as a string.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        sa.Index(
            "ix_audit_log_entity_history", "entity_type", "entity_id", "recorded_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    entity_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    entity_id: Mapped[UUID] = mapped_column(sa.Uuid(), nullable=False, index=True)
    action: Mapped[AuditAction] = mapped_column(
        sa.Enum(
            AuditAction,
            name="auditaction",
            native_enum=True,
            length=7,
            create_constraint=False,
        ),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id"), nullable=True, index=True, default=None
    )
    reason: Mapped[str | None] = mapped_column(
        sa.String(500), nullable=True, default=None
    )
    changes: Mapped[dict[str, Any]] = mapped_column(
        sa.JSON, nullable=False, default_factory=dict, insert_default=dict
    )
    recorded_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        index=True,
        default_factory=_utcnow,
        insert_default=_utcnow,
    )
