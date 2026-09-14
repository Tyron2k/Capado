"""Tests for the audit read endpoint and the capacity overview handler.

Both call the route handler directly with a mocked ``AsyncSession``, which is how
this project tests routers (see tests/test_settings.py). No HTTP client, no
dependency overrides, no database.

The capacity tests exist because mypy found two live 500s in that handler on its
first run and nothing prevented a regression: the response schema was built without
its required ``overbooked`` field, and the handler read ``res.department`` from a
model that has no such attribute since ResourceGroup replaced the free-text fields.

All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditAction, AuditLog
from app.models.resource import ResourceType
from app.routers.audit import (
    MAX_PAGE_SIZE,
    _apply_filters,
    entity_history,
    list_audit_entries,
)
from app.routers.capacity import get_capacity_overview
from app.services.capacity_service import WeeklyUtilization

ENTITY = UUID("11111111-0000-0000-0000-000000000001")
ACTOR = UUID("22222222-0000-0000-0000-000000000001")


def _session_returning(rows: list) -> AsyncMock:
    """Mocked AsyncSession whose every execute yields the same rows.

    Specced against the real AsyncSession so the mock cannot accidentally expose
    the SQLModel-only ``.exec()`` API.
    """
    session = AsyncMock(spec=AsyncSession)
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    result.all = MagicMock(return_value=rows)
    session.execute = AsyncMock(return_value=result)
    return session


def _audit_entry(action: AuditAction = AuditAction.updated) -> AuditLog:
    """Fictional audit row."""
    return AuditLog(
        id=uuid4(),
        entity_type="assignments",
        entity_id=ENTITY,
        action=action,
        actor_id=ACTOR,
        reason="shifted to resolve a conflict",
        changes={"start_date": {"from": "2026-06-01", "to": "2026-06-08"}},
        recorded_at=datetime(2026, 6, 2, 9, 0),
    )


# ---------------------------------------------------------------------------
# Audit filters
# ---------------------------------------------------------------------------


class _FakeStatement:
    """Records the where-clauses applied to it."""

    def __init__(self) -> None:
        self.wheres: list[object] = []

    def where(self, clause: object) -> _FakeStatement:
        self.wheres.append(clause)
        return self


class TestApplyFilters:
    """Each supplied filter narrows the query; each omitted one does not."""

    def test_no_filters_adds_nothing(self):
        """An unfiltered request must not accidentally constrain anything."""
        stmt = _FakeStatement()
        _apply_filters(stmt, None, None, None, None, None, None)
        assert stmt.wheres == []

    def test_each_filter_adds_one_clause(self):
        stmt = _FakeStatement()
        _apply_filters(
            stmt,
            "assignments",
            ENTITY,
            ACTOR,
            AuditAction.updated,
            datetime(2026, 6, 1),
            datetime(2026, 6, 30),
        )
        assert len(stmt.wheres) == 6

    def test_partial_filters_add_only_what_was_given(self):
        stmt = _FakeStatement()
        _apply_filters(stmt, "assignments", None, None, None, None, None)
        assert len(stmt.wheres) == 1


class TestAuditEndpoint:
    """The read surface over the trail."""

    async def test_entries_are_returned(self):
        session = _session_returning([_audit_entry()])
        entries = await list_audit_entries(
            entity_type=None,
            entity_id=None,
            actor_id=None,
            action=None,
            recorded_from=None,
            recorded_to=None,
            limit=50,
            offset=0,
            session=session,
            _admin=MagicMock(),
        )
        assert len(entries) == 1
        assert entries[0].entity_type == "assignments"
        assert entries[0].reason == "shifted to resolve a conflict"
        assert entries[0].changes["start_date"]["to"] == "2026-06-08"

    async def test_empty_trail_is_not_an_error(self):
        session = _session_returning([])
        entries = await list_audit_entries(
            entity_type=None,
            entity_id=None,
            actor_id=None,
            action=None,
            recorded_from=None,
            recorded_to=None,
            limit=50,
            offset=0,
            session=session,
            _admin=MagicMock(),
        )
        assert entries == []

    async def test_entity_history_returns_entries(self):
        session = _session_returning([_audit_entry(AuditAction.created)])
        entries = await entity_history(
            entity_type="assignments",
            entity_id=ENTITY,
            limit=50,
            session=session,
            _admin=MagicMock(),
        )
        assert entries[0].action == AuditAction.created

    def test_page_size_is_bounded(self):
        """A caller must not be able to pull the entire trail in one request.

        The bound is disclosure control as much as performance: the trail is a
        record of individual conduct.
        """
        assert MAX_PAGE_SIZE == 200


# ---------------------------------------------------------------------------
# Capacity overview — regression cover for the two bugs mypy found
# ---------------------------------------------------------------------------


def _week(overbooked: float = 0.0) -> WeeklyUtilization:
    """Fictional weekly utilization row."""
    return WeeklyUtilization(
        week_start=date(2026, 6, 1),
        total_available=500.0,
        total_assigned=400.0,
        utilization=80.0,
        overbooked=overbooked,
        color="yellow",
        available_minutes=2400,
        assigned_minutes=1920,
        working_days=5,
    )


class _Resource:
    """Fictional resource row as the joined query returns it."""

    def __init__(self, name: str = "Thomas Ahlfeld"):
        self.id = uuid4()
        self.name = name


class TestCapacityOverview:
    """The handler that shipped two live 500s until mypy was added."""

    async def test_weekly_rows_carry_overbooked(self, monkeypatch):
        """The response schema requires it; omitting it was a ValidationError.

        This is the regression guard for the first of the two bugs.
        """
        resource = _Resource()
        session = _session_returning([(resource, "Service Regio")])

        async def _weeks(self, *_args, **_kwargs):
            return [_week(overbooked=12.5)]

        monkeypatch.setattr(
            "app.services.capacity_service.CapacityService.get_weekly_utilization",
            _weeks,
        )

        result = await get_capacity_overview(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            resource_type=ResourceType.personal,
            department=None,
            project_ids=None,
            session=session,
            _current_user=MagicMock(),
        )
        assert result.resources[0].weeks[0].overbooked == 12.5

    async def test_group_name_comes_from_the_join(self, monkeypatch):
        """PersonalResource has no `department`; the name is joined.

        This is the regression guard for the second bug: free-text department and
        location were replaced by ResourceGroup, so reading res.department raised
        AttributeError.
        """
        resource = _Resource()
        session = _session_returning([(resource, "Service Regio")])

        async def _weeks(self, *_args, **_kwargs):
            return [_week()]

        monkeypatch.setattr(
            "app.services.capacity_service.CapacityService.get_weekly_utilization",
            _weeks,
        )

        result = await get_capacity_overview(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            resource_type=ResourceType.personal,
            department=None,
            project_ids=None,
            session=session,
            _current_user=MagicMock(),
        )
        assert result.resources[0].department_or_location == "Service Regio"

    async def test_missing_group_becomes_empty_string(self, monkeypatch):
        """An outer join yields NULL for an ungrouped resource, not a crash."""
        resource = _Resource()
        session = _session_returning([(resource, None)])

        async def _weeks(self, *_args, **_kwargs):
            return [_week()]

        monkeypatch.setattr(
            "app.services.capacity_service.CapacityService.get_weekly_utilization",
            _weeks,
        )

        result = await get_capacity_overview(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            resource_type=ResourceType.personal,
            department=None,
            project_ids=None,
            session=session,
            _current_user=MagicMock(),
        )
        assert result.resources[0].department_or_location == ""
