"""Tests for :mod:`app.services.freeze_enforcement`.

The pure rules are tested in test_planning_freeze.py. What is tested here is the wiring: that
an admin bypasses, that no configured freeze means no refusal, and that the span is derived
through :func:`assignment_span` so both booking shapes are seen.

The last one matters more than it reads. Personnel bookings use ``start_date``/``end_date``
and infrastructure bookings use ``start_at``/``end_at`` in the same table, and reading only one
pair is precisely the bug that once made every infrastructure booking invisible to the busyness
ranking. In a permission check the same mistake means silently ALLOWING an edit inside the
frozen period.

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment, ResourceType
from app.models.organization_settings import OrganizationSettings
from app.models.user import UserRole
from app.services.freeze_enforcement import enforce_freeze, freeze_date, span_of
from app.services.planning_freeze import Span

FREEZE = date(2026, 8, 1)


def _session_with_settings(settings: OrganizationSettings | None) -> AsyncMock:
    """Mocked AsyncSession whose settings query yields the given row."""
    session = AsyncMock(spec=AsyncSession)
    scalars = MagicMock()
    scalars.first = MagicMock(return_value=settings)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=result)
    return session


def _user(role: str) -> MagicMock:
    user = MagicMock()
    user.role = role
    return user


class TestSpanOf:
    def test_a_personnel_booking_uses_the_date_columns(self):
        assignment = Assignment(
            resource_id=MagicMock(),
            resource_type=ResourceType.personal,
            work_package_id=MagicMock(),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 10),
        )
        assert span_of(assignment) == Span(
            start=date(2026, 7, 1), end=date(2026, 7, 10)
        )

    def test_an_infrastructure_booking_uses_the_timestamp_columns(self):
        """Reading only the date pair would return an empty span for every machine
        booking — the same class of bug that made a fully booked hall look idle."""
        assignment = Assignment(
            resource_id=MagicMock(),
            resource_type=ResourceType.infrastructure,
            work_package_id=MagicMock(),
            start_at=datetime(2026, 7, 1, 6, 0),
            end_at=datetime(2026, 7, 10, 14, 0),
        )
        assert span_of(assignment) == Span(
            start=date(2026, 7, 1), end=date(2026, 7, 10)
        )

    def test_a_row_with_neither_pair_yields_an_open_span(self):
        """Which the freeze predicate treats as reaching back indefinitely — the
        conservative reading, and the right one for a permission check."""
        assignment = Assignment(
            resource_id=MagicMock(),
            resource_type=ResourceType.personal,
            work_package_id=MagicMock(),
        )
        assert span_of(assignment) == Span(start=None, end=None)


class TestFreezeDate:
    async def test_no_settings_row_means_no_freeze(self):
        assert await freeze_date(_session_with_settings(None)) is None

    async def test_the_configured_date_is_returned(self):
        settings = OrganizationSettings(planning_freeze_before=FREEZE)
        assert await freeze_date(_session_with_settings(settings)) == FREEZE


class TestEnforceFreeze:
    async def test_an_admin_is_not_blocked(self):
        """And the settings are not even read — the audit log is what records the
        override."""
        session = _session_with_settings(
            OrganizationSettings(planning_freeze_before=FREEZE)
        )
        await enforce_freeze(
            session,
            _user(UserRole.admin),
            before=Span(date(2026, 7, 1), date(2026, 7, 5)),
            after=Span(date(2026, 7, 1), date(2026, 7, 5)),
        )
        session.execute.assert_not_called()

    async def test_no_configured_freeze_allows_everything(self):
        session = _session_with_settings(
            OrganizationSettings(planning_freeze_before=None)
        )
        await enforce_freeze(
            session,
            _user(UserRole.editor),
            before=None,
            after=Span(date(2020, 1, 1), date(2020, 1, 5)),
        )

    async def test_an_editor_is_blocked_inside_the_frozen_period(self):
        session = _session_with_settings(
            OrganizationSettings(planning_freeze_before=FREEZE)
        )
        with pytest.raises(HTTPException) as exc:
            await enforce_freeze(
                session,
                _user(UserRole.editor),
                before=None,
                after=Span(date(2026, 7, 1), date(2026, 7, 5)),
            )
        # 403 rather than 409: the change is well-formed and would be accepted from
        # somebody else, which is a permission answer, not a conflict.
        assert exc.value.status_code == 403
        assert "2026-08-01" in exc.value.detail

    async def test_an_editor_is_allowed_in_the_open_period(self):
        session = _session_with_settings(
            OrganizationSettings(planning_freeze_before=FREEZE)
        )
        await enforce_freeze(
            session,
            _user(UserRole.editor),
            before=Span(date(2026, 9, 1), date(2026, 9, 5)),
            after=Span(date(2026, 9, 2), date(2026, 9, 6)),
        )

    async def test_dragging_a_frozen_booking_forward_is_blocked(self):
        """The case the wiring exists for: the resulting dates are entirely legal, and
        only the prior state reveals that frozen history was rewritten."""
        session = _session_with_settings(
            OrganizationSettings(planning_freeze_before=FREEZE)
        )
        with pytest.raises(HTTPException) as exc:
            await enforce_freeze(
                session,
                _user(UserRole.editor),
                before=Span(date(2026, 7, 1), date(2026, 7, 5)),
                after=Span(date(2026, 9, 1), date(2026, 9, 5)),
            )
        assert exc.value.status_code == 403
