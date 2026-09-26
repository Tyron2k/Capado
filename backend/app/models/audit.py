"""SQLModel entity for the audit trail.

One generic table rather than per-entity history, because the questions asked of
it cross entities — who changed anything on Friday, what did this user touch (see
ADR-006).
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel

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


class AuditLog(SQLModel, table=True):
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

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    entity_type: str = Field(max_length=64, index=True)
    entity_id: UUID = Field(index=True)
    action: AuditAction = Field(index=True)
    actor_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    reason: str | None = Field(default=None, max_length=500)
    changes: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(sa.JSON, nullable=False)
    )
    recorded_at: datetime = Field(default_factory=_utcnow, index=True)
