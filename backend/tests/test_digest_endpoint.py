"""Tests for the digest endpoint and its threshold loading.

Calls the route handler directly with a mocked ``AsyncSession``, which is how this project
tests routers (see tests/test_audit_and_capacity_routes.py). No HTTP client, no dependency
overrides, no database.

The threshold tests matter more than they look: an install with no settings row must still
produce a useful digest, because a fresh deployment that reports nothing looks broken rather
than calm.

All data is inline and clearly fictional.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization_settings import OrganizationSettings
from app.routers.digest import get_digest
from app.services.digest import DigestThresholds
from app.services.digest_service import thresholds_from_settings


def _session_returning(rows: list) -> AsyncMock:
    """Mocked AsyncSession whose every execute yields the same rows."""
    session = AsyncMock(spec=AsyncSession)
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    scalars.first = MagicMock(return_value=rows[0] if rows else None)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    result.all = MagicMock(return_value=rows)
    session.execute = AsyncMock(return_value=result)
    return session


class TestThresholdsFromSettings:
    async def test_defaults_apply_when_no_settings_row_exists(self):
        """A fresh install must still produce a useful digest. Failing or reporting
        nothing here would look like the feature is broken."""
        thresholds = await thresholds_from_settings(_session_returning([]))
        assert thresholds == DigestThresholds()

    async def test_configured_values_are_used(self):
        settings = OrganizationSettings(
            digest_horizon_days=30,
            digest_critical_days=3,
            digest_warning_days=10,
            digest_max_findings=25,
        )
        thresholds = await thresholds_from_settings(_session_returning([settings]))
        assert thresholds.horizon_days == 30
        assert thresholds.critical_days == 3
        assert thresholds.warning_days == 10
        assert thresholds.max_findings == 25


class TestDigestEndpoint:
    async def test_an_empty_plan_returns_an_empty_but_well_formed_digest(self):
        """Every severity is present at zero. A header that omits a zero reads as if the
        check did not run, which is indistinguishable from "nothing is wrong"."""
        response = await get_digest(
            session=_session_returning([]),
            current_user=MagicMock(),
        )
        assert response.findings == []
        assert response.counts == {"critical": 0, "warning": 0, "info": 0}
        assert response.suppressed_count == 0

    async def test_the_response_states_which_day_it_was_computed_for(self):
        """Severity is relative to that day, so a cached digest without it cannot be
        judged for staleness."""
        response = await get_digest(
            session=_session_returning([]),
            current_user=MagicMock(),
        )
        assert response.generated_for is not None
