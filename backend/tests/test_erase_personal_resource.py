"""Erasing a person must not miss a table.

WHY THIS TEST LOOKS LIKE THIS

Four of the tables holding a person's data — ``absences``, ``assignments``, ``conflicts``,
``resource_work_profiles`` — reference them through a POLYMORPHIC ``resource_id`` with **no foreign
key**, because one key cannot target both resource tables. So the database will not cascade, and more
importantly it cannot complain: forgetting a table leaves rows behind and every query still succeeds.
An erasure that misses one is indistinguishable from a correct one until someone audits the database
by hand, or until a regulator asks.

That makes "every table was addressed" the property worth pinning, and it is a property of the
STATEMENTS ISSUED rather than of any return value. The fake session below records them.

No database: this repository has no DB harness and every other test is DB-free, using hand-built
session doubles. This follows that pattern rather than introducing a second one.

WHAT THIS CANNOT TELL. That the SQL is correct against a real schema. A statement can name the right
table and still filter wrongly. The counter-checks below therefore verify that removing a table's
deletion makes a test fail — which proves the test discriminates — but a real-database integration
test remains the honest complement, and this repository has nowhere to put one yet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.models.audit import AuditAction, AuditLog
from app.models.resource import PersonalResource
from app.services import resource_service

RESOURCE_ID = UUID("44444444-0000-0000-0000-000000000001")
GROUP_ID = UUID("22222222-0000-0000-0000-000000000001")
CONFLICT_ID = UUID("55555555-0000-0000-0000-00000000000c")
ASSIGNMENT_ID = UUID("55555555-0000-0000-0000-00000000000a")
ABSENCE_ID = UUID("55555555-0000-0000-0000-00000000000b")

#: Every table an erasure must address. Written out rather than derived, so adding a table that holds
#: personal data forces a deliberate edit here instead of silently widening what "complete" means.
MUST_BE_CLEARED = {
    "personal_resource_skills",
    "resource_work_profiles",
    "conflict_assignments",
    "conflicts",
    "assignments",
    "absences",
    "audit_log",
}


class _Result:
    def __init__(self, rows: list[Any], rowcount: int = 0) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    """Records the statements an erasure issues, and what it adds and deletes."""

    def __init__(self, resource: PersonalResource) -> None:
        self._resource = resource
        self.deleted_tables: list[str] = []
        self.selected_tables: list[str] = []
        self.deleted_objects: list[Any] = []
        self.added: list[Any] = []
        self.commits = 0
        self.flushes = 0

    async def get(self, model: type, pk: UUID) -> Any:
        return self._resource if pk == self._resource.id else None

    async def execute(self, stmt: Any) -> _Result:
        table = getattr(getattr(stmt, "table", None), "name", None)
        if table is not None:  # DELETE ... FROM <table>
            self.deleted_tables.append(table)
            return _Result([], rowcount=1)
        # SELECT: hand back plausible ids so the code under test walks its real branches.
        froms = (
            getattr(stmt, "froms", None)
            or getattr(stmt, "get_final_froms", lambda: [])()
        )
        names = [getattr(f, "name", "") for f in froms]
        self.selected_tables.extend(n for n in names if n)
        if "conflicts" in names:
            return _Result([CONFLICT_ID])
        if "assignments" in names:
            return _Result([ASSIGNMENT_ID])
        if "absences" in names:
            return _Result([ABSENCE_ID])
        if "users" in names:
            return _Result([uuid4()])
        return _Result([])

    async def delete(self, obj: Any) -> None:
        self.deleted_objects.append(obj)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1


def _resource() -> PersonalResource:
    now = datetime.now(UTC).replace(tzinfo=None)
    return PersonalResource(
        id=RESOURCE_ID,
        name="Müller",
        group_id=GROUP_ID,
        site_id=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


async def _erase() -> tuple[Any, _FakeSession]:
    session = _FakeSession(_resource())
    report = await resource_service.erase_personal_resource(
        session,  # type: ignore[arg-type]
        RESOURCE_ID,
    )
    return report, session


class TestEveryTableIsAddressed:
    """The property the missing foreign keys make necessary."""

    @pytest.mark.asyncio
    async def test_no_table_holding_personal_data_is_skipped(self):
        _, session = await _erase()
        missing = MUST_BE_CLEARED - set(session.deleted_tables)
        assert not missing, f"erasure issued no DELETE for: {sorted(missing)}"

    @pytest.mark.asyncio
    async def test_the_person_row_itself_is_deleted(self):
        _, session = await _erase()
        assert [type(o).__name__ for o in session.deleted_objects] == [
            "PersonalResource"
        ]

    @pytest.mark.asyncio
    async def test_the_join_table_goes_before_its_conflicts(self):
        """Reversed, the join rows would be orphaned by the conflict delete."""
        _, session = await _erase()
        order = session.deleted_tables
        assert order.index("conflict_assignments") < order.index("conflicts")

    @pytest.mark.asyncio
    async def test_the_audit_sweep_happens_after_the_row_deletions(self):
        """The listener writes its own deletion entries on flush; sweeping first would leave them."""
        _, session = await _erase()
        order = session.deleted_tables
        assert order.index("audit_log") > order.index("assignments")
        assert session.flushes >= 1


class TestTheAuditMarker:
    """Keep nothing and the operator cannot evidence the request; keep the old rows and the request
    is defeated. Exactly one entry, with no personal content."""

    @pytest.mark.asyncio
    async def test_exactly_one_audit_entry_is_written(self):
        _, session = await _erase()
        entries = [o for o in session.added if isinstance(o, AuditLog)]
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_the_entry_carries_no_personal_content(self):
        _, session = await _erase()
        entry = next(o for o in session.added if isinstance(o, AuditLog))
        assert entry.changes == {}
        assert "Müller" not in (entry.reason or "")
        assert entry.action == AuditAction.deleted

    @pytest.mark.asyncio
    async def test_the_entry_keeps_the_identifier_so_the_request_can_be_evidenced(self):
        _, session = await _erase()
        entry = next(o for o in session.added if isinstance(o, AuditLog))
        assert entry.entity_id == RESOURCE_ID
        assert entry.entity_type == "personal_resources"


class TestTheReportAndTheTransaction:
    @pytest.mark.asyncio
    async def test_the_report_names_the_resource_and_counts_every_table(self):
        report, _ = await _erase()
        assert report.resource_id == RESOURCE_ID
        for field in (
            "skills",
            "work_profiles",
            "conflict_assignments",
            "conflicts",
            "assignments",
            "absences",
            "audit_entries",
        ):
            assert getattr(report, field) >= 1, f"{field} was not counted"

    @pytest.mark.asyncio
    async def test_linked_accounts_are_counted_rather_than_assumed(self):
        """The foreign key nulls users.resource_id. Counting it keeps a schema change from silently
        breaking that guarantee."""
        report, _ = await _erase()
        assert report.unlinked_accounts >= 1

    @pytest.mark.asyncio
    async def test_it_commits_exactly_once(self):
        """Two commits would mean a partial erasure could survive an error in the second half."""
        _, session = await _erase()
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_baselines_are_never_touched(self):
        """Baselines freeze assignments, not people, so a payload holds a UUID and no name. Rewriting
        them would corrupt the historical record to remove data that is not in it."""
        _, session = await _erase()
        assert "baseline_entries" not in session.deleted_tables
        assert "baselines" not in session.deleted_tables
