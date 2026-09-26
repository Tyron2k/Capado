"""Tests for the cookie-based refresh flow and reuse-detection grace window.

Exercises app.routers.auth.refresh directly with a mock AsyncSession and a
real FastAPI Response, verifying:

- a missing refresh cookie is rejected;
- an active token rotates and sets a fresh cookie;
- replay of a just-rotated token within the grace window is a benign
  concurrent refresh (re-issues, does not revoke the family);
- replay outside the grace window revokes the whole token family;
- replay of a logged-out (non-rotated) revoked token revokes the family.

All data is inline and clearly fictional; no database is used.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from app.config import settings
from app.routers.auth import refresh
from app.services.auth_service import create_refresh_token


@pytest.fixture(autouse=True)
def setup_database():
    """No-op override: these tests use a mock session, not the test database."""
    yield


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _request_with_cookie(raw_token: str | None) -> SimpleNamespace:
    """Fake request carrying (or missing) the refresh cookie."""
    cookies = {settings.refresh_cookie_name: raw_token} if raw_token else {}
    return SimpleNamespace(cookies=cookies)


def _exec_result(*, scalar: object = None, scalars: list | None = None) -> MagicMock:
    """Build a mock SQLAlchemy Result for scalar_one_or_none / scalars()."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=scalar)
    scalars_obj = MagicMock()
    scalars_obj.all = MagicMock(return_value=scalars or [])
    result.scalars = MagicMock(return_value=scalars_obj)
    return result


def _active_user() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        email="user@example.test",
        name="Test User",
        role="editor",
        scope_group_ids=None,
        scope_project_ids=None,
        must_change_password=False,
        is_active=True,
    )


def _stored_token(raw: str, *, revoked_at=None, replaced_by_id=None, user_id=None):
    """Fake RefreshToken row matching the given raw token's hash."""
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=_utcnow() + timedelta(days=7),
        revoked_at=revoked_at,
        replaced_by_id=replaced_by_id,
    )


def _has_refresh_cookie(response: Response) -> bool:
    """Whether the response sets a non-empty refresh cookie."""
    name = settings.refresh_cookie_name
    for key, value in response.raw_headers:
        if key != b"set-cookie" or name.encode() not in value:
            continue
        # A cleared cookie has an empty value / Max-Age=0.
        cleared = b"Max-Age=0" in value or f"{name}=;".encode() in value
        if not cleared:
            return True
    return False


class TestRefreshFlow:
    """Cookie-based refresh and reuse-detection grace window."""

    async def test_missing_cookie_rejected(self):
        """No refresh cookie → 401."""
        response = Response()
        session = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await refresh(
                request=_request_with_cookie(None),
                response=response,
                session=session,
            )
        assert exc.value.status_code == 401

    async def test_active_token_rotates_and_sets_cookie(self):
        """A valid active token rotates and issues a fresh cookie."""
        raw, _, _ = create_refresh_token()
        user = _active_user()
        stored = _stored_token(raw, user_id=user.id)

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _exec_result(scalar=stored),  # token lookup
                _exec_result(scalar=user),  # user lookup
                _exec_result(),  # delete expired
            ]
        )
        session.add = MagicMock()

        response = Response()
        result = await refresh(
            request=_request_with_cookie(raw), response=response, session=session
        )

        assert result.access_token
        assert not hasattr(result, "refresh_token")
        assert _has_refresh_cookie(response)
        # The presented (active) token was rotated: revoked + chained.
        assert stored.revoked_at is not None
        assert stored.replaced_by_id is not None

    async def test_grace_window_reissues_without_family_revoke(self):
        """A just-rotated token replayed within grace re-issues, no family kill."""
        raw, _, _ = create_refresh_token()
        user = _active_user()
        stored = _stored_token(
            raw,
            revoked_at=_utcnow() - timedelta(seconds=2),
            replaced_by_id=uuid4(),
            user_id=user.id,
        )

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _exec_result(scalar=stored),  # token lookup (revoked, recent)
                _exec_result(scalar=user),  # user lookup
                _exec_result(),  # delete expired
            ]
        )
        session.add = MagicMock()

        response = Response()
        result = await refresh(
            request=_request_with_cookie(raw), response=response, session=session
        )

        assert result.access_token
        assert _has_refresh_cookie(response)
        # Only two selects + one delete: family revocation was NOT triggered.
        assert session.execute.await_count == 3

    async def test_replay_outside_grace_revokes_family(self):
        """A rotated token replayed after the grace window revokes the family."""
        raw, _, _ = create_refresh_token()
        user_id = uuid4()
        stored = _stored_token(
            raw,
            revoked_at=_utcnow()
            - timedelta(seconds=settings.refresh_reuse_grace_seconds + 60),
            replaced_by_id=uuid4(),
            user_id=user_id,
        )
        family = [
            SimpleNamespace(revoked_at=None),
            SimpleNamespace(revoked_at=None),
        ]

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _exec_result(scalar=stored),  # token lookup
                _exec_result(scalars=family),  # _revoke_all_user_tokens select
            ]
        )
        session.add = MagicMock()

        response = Response()
        with pytest.raises(HTTPException) as exc:
            await refresh(
                request=_request_with_cookie(raw),
                response=response,
                session=session,
            )
        assert exc.value.status_code == 401
        # The whole family was revoked.
        assert all(t.revoked_at is not None for t in family)

    async def test_logged_out_token_replay_revokes_family(self):
        """A revoked-but-never-rotated (logout) token replay revokes the family."""
        raw, _, _ = create_refresh_token()
        stored = _stored_token(
            raw,
            revoked_at=_utcnow(),  # revoked now, but never rotated
            replaced_by_id=None,
            user_id=uuid4(),
        )
        family = [SimpleNamespace(revoked_at=None)]

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _exec_result(scalar=stored),
                _exec_result(scalars=family),
            ]
        )
        session.add = MagicMock()

        response = Response()
        with pytest.raises(HTTPException) as exc:
            await refresh(
                request=_request_with_cookie(raw),
                response=response,
                session=session,
            )
        assert exc.value.status_code == 401
        assert all(t.revoked_at is not None for t in family)
