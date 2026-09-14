"""Tests for :mod:`app.services.audit`.

The listener itself needs a flush to fire, and this project uses no database in
tests, so the two functions it delegates to are tested directly: change collection
over an inspected instance state, and entry building over a session-like double.

That split is why those functions are module-level rather than inlined into the
listener (ADR-006).

All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from app.models.assignment import Assignment
from app.models.audit import UNAUDITED_TABLES, AuditAction
from app.models.conflict import Conflict
from app.models.resource import ResourceType
from app.services.audit import (
    _auditable,
    _entries_for_flush,
    _jsonable,
    collect_changes,
    set_actor,
    set_reason,
)

ACTOR = UUID("aaaaaaaa-1111-1111-1111-111111111111")
ENTITY = UUID("bbbbbbbb-2222-2222-2222-222222222222")


class _FakeHistory:
    """Stand-in for SQLAlchemy's attribute history."""

    def __init__(self, deleted: list[Any], added: list[Any], changed: bool = True):
        self.deleted = deleted
        self.added = added
        self._changed = changed

    def has_changes(self) -> bool:
        return self._changed


class _FakeAttr:
    """Stand-in for one inspected attribute."""

    def __init__(self, key: str, history: _FakeHistory):
        self.key = key
        self.history = history


class _FakeState:
    """Stand-in for ``inspect(obj)``."""

    def __init__(self, attrs: list[_FakeAttr], modified: bool = True):
        self.attrs = attrs
        self.modified = modified


class _FakeSession:
    """Session double exposing only what the entry builder reads."""

    def __init__(
        self,
        new: list[Any] | None = None,
        dirty: list[Any] | None = None,
        deleted: list[Any] | None = None,
    ):
        self.info: dict[str, Any] = {}
        self.new = new or []
        self.dirty = dirty or []
        self.deleted = deleted or []


class _Row:
    """Plain object for exercising the pure auditability check."""

    def __init__(self, table: Any, row_id: Any = ENTITY):
        self.__tablename__ = table
        self.id = row_id


def _assignment(row_id: UUID = ENTITY) -> Assignment:
    """Fictional personal assignment, unattached to any session."""
    return Assignment(
        id=row_id,
        resource_id=uuid4(),
        resource_type=ResourceType.personal,
        work_package_id=uuid4(),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        allocation_percent=50.0,
    )


def _conflict() -> Conflict:
    """Fictional conflict — a derived row, which must not be audited."""
    return Conflict(
        id=uuid4(),
        resource_id=uuid4(),
        resource_type=ResourceType.personal,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        total_assigned_percent=150.0,
        available_percent=100.0,
    )


# ---------------------------------------------------------------------------
# _auditable — the gate, checked before any inspection
# ---------------------------------------------------------------------------


class TestAuditable:
    """Which objects are recorded at all."""

    def test_audited_table_with_uuid_id_passes(self):
        assert _auditable(_Row("assignments")) == ("assignments", ENTITY)

    def test_derived_tables_are_rejected(self):
        """Conflicts are recomputed on every assignment change, not decided.

        Auditing them would add dozens of rows per user action and bury the
        entries someone is actually looking for.
        """
        assert "conflicts" in UNAUDITED_TABLES
        for table in ("conflicts", "conflict_assignments", "audit_log"):
            assert _auditable(_Row(table)) is None

    def test_object_without_a_table_is_rejected(self):
        assert _auditable(_Row(None)) is None

    def test_non_uuid_id_is_rejected(self):
        """A composite-key join row has no single id to point at."""
        assert _auditable(_Row("assignments", row_id="not-a-uuid")) is None
        assert _auditable(_Row("assignments", row_id=None)) is None


# ---------------------------------------------------------------------------
# Entry building, against real mapped instances
# ---------------------------------------------------------------------------


class TestEntriesForFlush:
    """What ends up in the log for one flush."""

    def test_new_object_yields_a_created_entry(self):
        session = _FakeSession(new=[_assignment()])
        entries = _entries_for_flush(session)  # type: ignore[arg-type]
        assert len(entries) == 1
        assert entries[0].action == AuditAction.created
        assert entries[0].entity_type == "assignments"
        assert entries[0].entity_id == ENTITY

    def test_created_entry_carries_the_new_values(self):
        """An insert records what the row started as."""
        entries = _entries_for_flush(_FakeSession(new=[_assignment()]))  # type: ignore[arg-type]
        assert entries[0].changes["allocation_percent"] == {"from": None, "to": 50.0}
        assert entries[0].changes["start_date"]["to"] == "2026-06-01"

    def test_deleted_object_yields_an_empty_diff(self):
        """The row is the information; a field-by-field diff adds nothing."""
        session = _FakeSession(deleted=[_assignment()])
        entries = _entries_for_flush(session)  # type: ignore[arg-type]
        assert entries[0].action == AuditAction.deleted
        assert entries[0].changes == {}

    def test_derived_tables_produce_no_entries(self):
        """And crucially without inspecting them first."""
        session = _FakeSession(new=[_conflict()])
        assert _entries_for_flush(session) == []  # type: ignore[arg-type]

    def test_actor_is_taken_from_the_session(self):
        """Stamped once by the authenticated dependency, read here."""
        session = _FakeSession(new=[_assignment()])
        set_actor(session, ACTOR)
        entries = _entries_for_flush(session)  # type: ignore[arg-type]
        assert entries[0].actor_id == ACTOR

    def test_missing_actor_is_null_not_an_error(self):
        """Setup and login write before there is an actor."""
        entries = _entries_for_flush(_FakeSession(new=[_assignment()]))  # type: ignore[arg-type]
        assert entries[0].actor_id is None

    def test_reason_is_attached_when_set(self):
        """A listener sees that an assignment moved; only the caller knows why."""
        session = _FakeSession(new=[_assignment()])
        set_reason(session, "shifted to resolve a conflict")
        entries = _entries_for_flush(session)  # type: ignore[arg-type]
        assert entries[0].reason == "shifted to resolve a conflict"

    def test_several_objects_yield_several_entries(self):
        session = _FakeSession(
            new=[_assignment(uuid4()), _assignment(uuid4())],
            deleted=[_assignment(uuid4())],
        )
        entries = _entries_for_flush(session)  # type: ignore[arg-type]
        assert len(entries) == 3
        assert {e.action for e in entries} == {
            AuditAction.created,
            AuditAction.deleted,
        }


# ---------------------------------------------------------------------------
# _jsonable
# ---------------------------------------------------------------------------


class TestJsonable:
    """Column values are reduced to something JSON can carry."""

    def test_primitives_pass_through(self):
        """Numbers, strings, booleans and None are already JSON."""
        assert _jsonable(None) is None
        assert _jsonable(42) == 42
        assert _jsonable(1.5) == 1.5
        assert _jsonable(True) is True
        assert _jsonable("Bay 76") == "Bay 76"

    def test_dates_become_iso_strings(self):
        """A date has to survive a round-trip through JSON."""
        assert _jsonable(date(2026, 6, 1)) == "2026-06-01"
        assert _jsonable(datetime(2026, 6, 1, 14, 30)) == "2026-06-01T14:30:00"

    def test_uuid_becomes_a_string(self):
        """Foreign keys are readable in the log."""
        assert _jsonable(ACTOR) == str(ACTOR)

    def test_bytes_record_only_their_size(self):
        """A logo blob must never be copied into the audit trail."""
        assert _jsonable(b"\x89PNG" + b"\x00" * 100) == "<104 bytes>"


# ---------------------------------------------------------------------------
# collect_changes
# ---------------------------------------------------------------------------


class TestCollectChanges:
    """Per-attribute before and after, minus the noise."""

    def test_changed_attribute_is_recorded(self):
        """The point of the whole exercise."""
        state = _FakeState(
            [_FakeAttr("allocation_percent", _FakeHistory([50.0], [80.0]))]
        )
        assert collect_changes(state) == {
            "allocation_percent": {"from": 50.0, "to": 80.0}
        }

    def test_unchanged_attribute_is_skipped(self):
        """No history, no entry."""
        state = _FakeState([_FakeAttr("name", _FakeHistory([], [], changed=False))])
        assert collect_changes(state) == {}

    def test_timestamps_are_skipped(self):
        """updated_at changes on every write and would double every entry."""
        state = _FakeState(
            [
                _FakeAttr("updated_at", _FakeHistory([1], [2])),
                _FakeAttr("created_at", _FakeHistory([1], [2])),
                _FakeAttr("name", _FakeHistory(["a"], ["b"])),
            ]
        )
        assert list(collect_changes(state)) == ["name"]

    def test_password_hash_is_recorded_but_not_disclosed(self):
        """The change is the audit record; the hash is material for an offline attack.

        audit_log is readable by any admin through GET /api/audit and retained for months, so
        writing both bcrypt hashes into it would turn the safeguard into a hash dump.
        """
        state = _FakeState(
            [_FakeAttr("password_hash", _FakeHistory(["$2b$12$old"], ["$2b$12$new"]))]
        )
        result = collect_changes(state)
        assert result == {"password_hash": {"from": "<redacted>", "to": "<redacted>"}}
        assert "$2b$12$old" not in str(result)
        assert "$2b$12$new" not in str(result)

    def test_smtp_password_is_redacted_too(self):
        """Same reasoning: a relay password is a credential, and the change is what matters."""
        state = _FakeState(
            [_FakeAttr("smtp_password", _FakeHistory(["s3cret"], ["n3w"]))]
        )
        assert collect_changes(state) == {
            "smtp_password": {"from": "<redacted>", "to": "<redacted>"}
        }

    def test_a_redacted_field_still_appears(self):
        """Redacting must not become hiding — a reader has to see that it changed."""
        state = _FakeState(
            [
                _FakeAttr("password_hash", _FakeHistory(["a"], ["b"])),
                _FakeAttr("name", _FakeHistory(["x"], ["y"])),
            ]
        )
        assert sorted(collect_changes(state)) == ["name", "password_hash"]

    def test_attribute_with_no_values_yields_nothing(self):
        """An unloaded attribute must not be reported as having been empty.

        Recording {"from": None} for an attribute whose old value was simply not
        loaded would be a false statement about the data.
        """
        state = _FakeState([_FakeAttr("note", _FakeHistory([], [], changed=True))])
        assert collect_changes(state) == {}

    def test_creation_records_only_the_new_value(self):
        """On an insert there is nothing to have changed from."""
        state = _FakeState([_FakeAttr("name", _FakeHistory([], ["Bay 76"]))])
        assert collect_changes(state) == {"name": {"from": None, "to": "Bay 76"}}

    def test_values_are_json_reduced(self):
        """Dates in the diff are strings, not date objects."""
        state = _FakeState(
            [
                _FakeAttr(
                    "start_date", _FakeHistory([date(2026, 6, 1)], [date(2026, 6, 8)])
                )
            ]
        )
        assert collect_changes(state) == {
            "start_date": {"from": "2026-06-01", "to": "2026-06-08"}
        }
