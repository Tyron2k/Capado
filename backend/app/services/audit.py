"""Audit recording: a session listener plus the pure function it delegates to.

The listener fires on ``before_flush`` and adds :class:`AuditLog` rows to the same
flush, so a rolled-back transaction takes its audit entries with it (ADR-006).

The change-collecting logic is a module-level function over already-inspected
values rather than a method on the listener, so it can be tested without a
database — matching how the rest of this project tests services.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models.audit import UNAUDITED_TABLES, AuditAction, AuditLog

# Columns whose change is noise: every update touches updated_at, and recording
# "updated_at moved" alongside the field that actually changed doubles the size of
# every entry for no information.
IGNORED_FIELDS = frozenset({"updated_at", "created_at"})

# Columns whose CHANGE is worth recording but whose VALUE is not. The fact that a password was
# replaced is audit-relevant — who did it and when is exactly what this log is for — while the
# bcrypt hashes on either side are material an attacker can work on offline.
#
# Without this, every password change wrote both hashes into audit_log.changes, a table readable
# by any admin through GET /api/audit and retained for 24 months by default. That turned the audit
# trail into a hash dump, which is the opposite of a safeguard.
#
# The key still appears, so a reader sees that the field changed and consumers keep the same shape.
REDACTED_FIELDS = frozenset({"password_hash", "smtp_password"})
_REDACTED = "<redacted>"

_ACTOR_KEY = "audit_actor_id"
_REASON_KEY = "audit_reason"


def set_actor(session: Any, actor_id: UUID | None) -> None:
    """Record who is responsible for the writes on this session.

    Called once per request by the authenticated dependency. ``session.info`` is
    used rather than a ContextVar because in FastAPI the session is already
    request-scoped, so the lifetimes match without any reset discipline.
    """
    session.info[_ACTOR_KEY] = actor_id


def set_reason(session: Any, reason: str | None) -> None:
    """Attach intent to the writes of the next flush.

    A listener can see that an assignment moved; only the caller knows whether it
    moved to resolve a conflict or because a customer changed a date.
    """
    session.info[_REASON_KEY] = reason


def _jsonable(value: Any) -> Any:
    """Reduce a column value to something JSON can carry."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        # Logo blobs and the like: record that it changed, never the payload.
        return f"<{len(value)} bytes>"
    return str(value)


def collect_changes(state: Any) -> dict[str, dict[str, Any]]:
    """Per-attribute before/after for a modified instance.

    Args:
        state: A SQLAlchemy instance state, as returned by ``inspect(obj)``.

    Returns:
        ``{"field": {"from": old, "to": new}}``, skipping attributes that did not
        change and the timestamp columns that change on every write. Fields in
        :data:`REDACTED_FIELDS` are reported as having changed, with both values replaced —
        the event is the audit record, the secret is not.

    An attribute with no loaded history yields nothing rather than a
    ``{"from": None, "to": ...}`` entry that would misreport an unloaded value as
    having been empty.
    """
    changes: dict[str, dict[str, Any]] = {}
    for attr in state.attrs:
        if attr.key in IGNORED_FIELDS:
            continue
        history = attr.history
        if not history.has_changes():
            continue
        deleted = history.deleted
        added = history.added
        if not deleted and not added:
            continue
        if attr.key in REDACTED_FIELDS:
            changes[attr.key] = {"from": _REDACTED, "to": _REDACTED}
            continue
        changes[attr.key] = {
            "from": _jsonable(deleted[0]) if deleted else None,
            "to": _jsonable(added[0]) if added else None,
        }
    return changes


def _auditable(obj: Any) -> tuple[str, UUID] | None:
    """Table name and row id, or None when this object is not audited.

    Checked BEFORE inspecting the instance: a conflict row would otherwise have
    its full attribute diff computed and then thrown away, and every
    `refresh_conflicts` call rewrites all conflicts of a resource.
    """
    table = getattr(obj, "__tablename__", None)
    if not isinstance(table, str) or table in UNAUDITED_TABLES:
        return None
    entity_id = getattr(obj, "id", None)
    if not isinstance(entity_id, UUID):
        return None
    return table, entity_id


def _entries_for_flush(session: Session) -> list[AuditLog]:
    """Build the audit rows for everything pending in this flush."""
    actor_id = session.info.get(_ACTOR_KEY)
    reason = session.info.get(_REASON_KEY)
    entries: list[AuditLog] = []

    def entry(
        table: str, entity_id: UUID, action: AuditAction, changes: dict[str, Any]
    ) -> None:
        entries.append(
            AuditLog(
                entity_type=table,
                entity_id=entity_id,
                action=action,
                actor_id=actor_id,
                reason=reason,
                changes=changes,
            )
        )

    for obj in session.new:
        target = _auditable(obj)
        if target is None:
            continue
        entry(*target, AuditAction.created, collect_changes(inspect(obj)))

    for obj in session.dirty:
        target = _auditable(obj)
        if target is None:
            continue
        state = inspect(obj)
        if not state.modified:
            continue
        changes = collect_changes(state)
        if not changes:
            # Touched but unchanged — recording it would be noise.
            continue
        entry(*target, AuditAction.updated, changes)

    for obj in session.deleted:
        target = _auditable(obj)
        if target is None:
            continue
        # The row is the information; a field-by-field diff of a deletion adds
        # nothing a reader needs.
        entry(*target, AuditAction.deleted, {})

    return entries


def _before_flush(session: Session, _flush_context: Any, _instances: Any) -> None:
    """Add audit rows for this flush, then clear the one-shot reason."""
    entries = _entries_for_flush(session)
    for entry in entries:
        session.add(entry)
    # The reason describes one operation, not the whole request: leaving it set
    # would stamp it onto every later flush on the same session.
    session.info.pop(_REASON_KEY, None)


def register_audit_listener() -> None:
    """Attach the listener to every session, once.

    Registered against the Session class rather than an instance so it covers the
    request sessions, the scripts and anything a future entry point opens.
    """
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
