"""Tests for :mod:`app.services.baseline_retention`.

The behaviour worth pinning is not the arithmetic — that is shared with the audit log —
but the two decisions that make baseline retention different from it: the default is
disabled, and the current baseline is never deleted.

No database: the session is a hand-written double. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from app.models.organization_settings import OrganizationSettings
from app.services.baseline_retention import cutoff_for, prune_baselines

NOW = datetime(2026, 8, 25, 14, 0)


class _FakeSession:
    """Counts eligible and current-but-old baselines, records the delete."""

    def __init__(self, eligible: int, old_current: int = 0) -> None:
        self.eligible = eligible
        self.old_current = old_current
        self.deletes = 0
        self.commits = 0
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> Any:
        text = " ".join(str(statement).split())
        self.statements.append(text)
        if text.upper().startswith("DELETE"):
            self.deletes += 1
            return type("R", (), {"rowcount": self.eligible})()
        # Two counts: eligible (is_current = false) and kept (is_current = true).
        value = self.old_current if "is_current = true" in text else self.eligible
        return type("R", (), {"scalar_one": lambda _s: value})()

    async def commit(self) -> None:
        self.commits += 1


class TestDefaultIsDisabled:
    """The decision that separates this from audit retention."""

    def test_the_shipped_default_keeps_everything(self):
        """A baseline is a record somebody chose to create.

        Losing the state a sign-off was measured against by omission would be worse
        than keeping it, so an operator has to opt in.
        """
        assert OrganizationSettings().baseline_retention_months == 0

    def test_the_audit_default_is_deliberately_different(self):
        """Stated as a test so the asymmetry is not read as an oversight."""
        settings = OrganizationSettings()
        assert settings.audit_retention_months == 24
        assert settings.baseline_retention_months == 0

    def test_zero_yields_no_cutoff(self):
        assert cutoff_for(0, NOW) is None

    def test_a_negative_period_is_refused_not_inverted(self):
        """It would otherwise put the cutoff in the FUTURE and delete every baseline."""
        assert cutoff_for(-6, NOW) is None

    def test_a_real_period_yields_a_past_cutoff(self):
        cutoff = cutoff_for(12, NOW)
        assert cutoff is not None
        assert cutoff.date() == date(2025, 8, 25)


class TestPrune:
    """What gets deleted, and what does not."""

    @pytest.mark.asyncio
    async def test_disabled_retention_touches_nothing(self):
        session = _FakeSession(eligible=99)
        result = await prune_baselines(session, 0, now=NOW)  # type: ignore[arg-type]
        assert result.deleted == 0
        assert result.cutoff is None
        assert session.statements == []
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_a_dry_run_counts_and_deletes_nothing(self):
        session = _FakeSession(eligible=4)
        result = await prune_baselines(session, 12, now=NOW, dry_run=True)  # type: ignore[arg-type]
        assert result.deleted == 4
        assert session.deletes == 0
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_old_baselines_are_deleted(self):
        session = _FakeSession(eligible=3)
        result = await prune_baselines(session, 12, now=NOW)  # type: ignore[arg-type]
        assert result.deleted == 3
        assert session.deletes == 1
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_the_delete_excludes_the_current_baseline(self):
        """A comparison tool that quietly stops comparing is worse than a stale one.

        Deleting the reference point would turn every "the plan has not moved" answer
        into "there is nothing to compare with".
        """
        session = _FakeSession(eligible=2)
        await prune_baselines(session, 12, now=NOW)  # type: ignore[arg-type]
        delete_stmt = next(
            s for s in session.statements if s.upper().startswith("DELETE")
        )
        assert "is_current = false" in delete_stmt

    @pytest.mark.asyncio
    async def test_an_old_current_baseline_is_reported_as_kept(self):
        session = _FakeSession(eligible=1, old_current=1)
        result = await prune_baselines(session, 12, now=NOW)  # type: ignore[arg-type]
        assert result.kept_current is True
        assert result.deleted == 1

    @pytest.mark.asyncio
    async def test_nothing_old_enough_is_not_an_error(self):
        session = _FakeSession(eligible=0)
        result = await prune_baselines(session, 12, now=NOW)  # type: ignore[arg-type]
        assert result.deleted == 0
        assert result.kept_current is False

    @pytest.mark.asyncio
    async def test_the_cutoff_is_reported_for_the_log_line(self):
        """The operator's evidence that the period was applied."""
        session = _FakeSession(eligible=1)
        result = await prune_baselines(session, 24, now=NOW)  # type: ignore[arg-type]
        assert result.cutoff is not None
        assert result.cutoff.date() == date(2024, 8, 25)
