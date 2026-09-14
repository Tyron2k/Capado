"""Tests for :mod:`app.services.audit_retention`.

Retention is a deletion feature, so the tests are written around the ways it could
delete the wrong thing: a cutoff in the future, month arithmetic that lands on an
invalid date, and a disabled period that is mistaken for "delete everything".

No database: the session is a hand-written double. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from app.services.audit_retention import (
    DELETE_BATCH_SIZE,
    MAX_BATCHES_PER_RUN,
    cutoff_for,
    months_before,
    prune_audit_log,
)

NOW = datetime(2026, 8, 25, 13, 30)


class _FakeSession:
    """Session double counting deletions and answering the dry-run count."""

    def __init__(self, rows_over_cutoff: int) -> None:
        self.remaining = rows_over_cutoff
        self.commits = 0
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> Any:
        text = str(statement)
        self.statements.append(text)
        if text.strip().upper().startswith("SELECT"):
            count = self.remaining
            return type("R", (), {"scalar_one": lambda _s: count})()
        batch = min(params["size"], self.remaining)
        self.remaining -= batch
        return type("R", (), {"rowcount": batch})()

    async def commit(self) -> None:
        self.commits += 1


class TestMonthsBefore:
    """Whole months, because a period is agreed in months and 730 days drifts."""

    def test_simple_case(self):
        assert months_before(date(2026, 8, 25), 24) == date(2024, 8, 25)

    def test_crossing_a_year_boundary(self):
        assert months_before(date(2026, 2, 15), 3) == date(2025, 11, 15)

    def test_a_single_month(self):
        assert months_before(date(2026, 8, 25), 1) == date(2026, 7, 25)

    def test_the_day_is_clamped_to_a_valid_date(self):
        """31 March minus one month is 28 February, not an invalid date."""
        assert months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)

    def test_clamping_respects_a_leap_year(self):
        assert months_before(date(2024, 3, 31), 1) == date(2024, 2, 29)

    def test_zero_months_is_the_same_day(self):
        assert months_before(date(2026, 8, 25), 0) == date(2026, 8, 25)


class TestCutoff:
    """The boundary, and the two ways of asking for no boundary at all."""

    def test_a_period_yields_a_past_cutoff(self):
        cutoff = cutoff_for(24, NOW)
        assert cutoff is not None
        assert cutoff < NOW
        assert cutoff.date() == date(2024, 8, 25)

    def test_zero_disables_retention(self):
        assert cutoff_for(0, NOW) is None

    def test_a_negative_period_is_refused_not_inverted(self):
        """A negative period would put the cutoff in the FUTURE.

        Computed naively that deletes the entire log, which is the worst possible
        failure mode for this feature. It must read as "disabled", not as "delete
        everything".
        """
        assert cutoff_for(-12, NOW) is None


class TestPrune:
    """What actually gets deleted."""

    @pytest.mark.asyncio
    async def test_disabled_retention_deletes_nothing(self):
        session = _FakeSession(rows_over_cutoff=10_000)
        result = await prune_audit_log(session, 0, now=NOW)  # type: ignore[arg-type]
        assert result.deleted == 0
        assert result.cutoff is None
        assert session.statements == []
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_a_dry_run_counts_and_changes_nothing(self):
        session = _FakeSession(rows_over_cutoff=1_234)
        result = await prune_audit_log(session, 24, now=NOW, dry_run=True)  # type: ignore[arg-type]
        assert result.deleted == 1_234
        assert session.remaining == 1_234
        assert session.commits == 0
        assert all(s.strip().upper().startswith("SELECT") for s in session.statements)

    @pytest.mark.asyncio
    async def test_a_short_backlog_is_deleted_in_one_batch(self):
        session = _FakeSession(rows_over_cutoff=42)
        result = await prune_audit_log(session, 24, now=NOW)  # type: ignore[arg-type]
        assert result.deleted == 42
        assert result.truncated is False
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_a_long_backlog_is_deleted_in_batches(self):
        """Bounded batches so a first run degrades throughput, not availability."""
        session = _FakeSession(rows_over_cutoff=DELETE_BATCH_SIZE * 3 + 7)
        result = await prune_audit_log(session, 24, now=NOW)  # type: ignore[arg-type]
        assert result.deleted == DELETE_BATCH_SIZE * 3 + 7
        assert result.truncated is False
        # One commit per batch: an interrupted run keeps the work it already did.
        assert session.commits == 4

    @pytest.mark.asyncio
    async def test_the_batch_ceiling_reports_that_rows_remain(self):
        session = _FakeSession(
            rows_over_cutoff=DELETE_BATCH_SIZE * (MAX_BATCHES_PER_RUN + 5)
        )
        result = await prune_audit_log(session, 24, now=NOW)  # type: ignore[arg-type]
        assert result.truncated is True
        assert result.deleted == DELETE_BATCH_SIZE * MAX_BATCHES_PER_RUN
        assert session.remaining > 0

    @pytest.mark.asyncio
    async def test_an_empty_log_is_not_an_error(self):
        session = _FakeSession(rows_over_cutoff=0)
        result = await prune_audit_log(session, 24, now=NOW)  # type: ignore[arg-type]
        assert result.deleted == 0
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_the_cutoff_is_passed_to_the_delete(self):
        session = _FakeSession(rows_over_cutoff=1)
        result = await prune_audit_log(session, 24, now=NOW)  # type: ignore[arg-type]
        assert result.cutoff is not None
        assert result.cutoff.date() == date(2024, 8, 25)
        assert any("DELETE" in s.upper() for s in session.statements)
