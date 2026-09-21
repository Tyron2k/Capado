"""Tests for OIDC user resolution and the SSO / must_change_password interaction.

SSO users authenticate through the identity provider and may have no usable
local password, so the forced-password-change gate must never block them.
These tests verify that :func:`app.routers.oidc._find_or_create_user` clears
``must_change_password`` on every path (auto-create, email account-linking,
and an already-linked user), and honors the auto-create toggle.

All data is inline and clearly fictional; a mock AsyncSession stands in for the
database.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.config import settings
from app.models.user import User, UserRole
from app.routers import oidc as oidc_router
from app.routers.oidc import _find_or_create_user
from app.services.oidc_service import OIDCUserInfo


@pytest.fixture(autouse=True)
def setup_database():
    """No-op override: these tests use a mock session, not the test database."""
    yield


def _userinfo(
    sub: str = "sub-123",
    email: str = "sso.user@example.test",
    email_verified: bool | None = True,
) -> OIDCUserInfo:
    """Fabricate OIDC userinfo with clearly fictional values.

    ``email_verified`` defaults to True — a well-behaved provider — because the tests below are
    about the must_change_password interaction, not about the verification gate. The gate has its
    own class, and it is the reason this default has to be stated rather than left off: with
    ``oidc_require_verified_email`` on, omitting the claim refuses the login.
    """
    return OIDCUserInfo(
        sub=sub, email=email, name="SSO Test User", email_verified=email_verified
    )


def _local_user(must_change: bool) -> User:
    """Build a fake local user account."""
    return User(
        id=uuid4(),
        email="sso.user@example.test",
        name="Existing Local User",
        password_hash="local-hash",
        role=UserRole.editor,
        is_active=True,
        must_change_password=must_change,
    )


def _session_returning(*scalars: object) -> AsyncMock:
    """Build a mock session whose execute() yields the given scalars in order."""
    results = []
    for value in scalars:
        result = MagicMock()
        result.scalar_one_or_none = lambda v=value: v
        results.append(result)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=results)
    session.add = MagicMock()
    return session


async def test_oidc_provider_error_cannot_forge_log_entries(monkeypatch, caplog):
    """Provider-controlled callback fields stay on one physical log line."""
    monkeypatch.setattr(oidc_router, "OIDC_ENABLED", True)

    response = await oidc_router.oidc_callback(
        error="access_denied\r\nINFO forged entry",
        error_description="The user cancelled\nWARNING forged entry",
        session=AsyncMock(),
    )

    assert response.status_code == 302
    message = caplog.records[-1].getMessage()
    assert "\r" not in message
    assert "\n" not in message
    assert r'"access_denied\r\nINFO forged entry"' in message
    assert r'"The user cancelled\nWARNING forged entry"' in message


class TestOidcUserResolution:
    """SSO users must never be gated by must_change_password."""

    async def test_auto_create_sets_flag_false(self, monkeypatch):
        """A newly auto-created SSO user is not required to change a password."""
        monkeypatch.setattr(settings, "oidc_auto_create_users", True)
        # No user by external_id, none by email → auto-create.
        session = _session_returning(None, None)

        user = await _find_or_create_user(session, _userinfo())

        assert user is not None
        assert user.must_change_password is False
        assert user.password_hash == ""
        assert user.external_id == "sub-123"
        assert user.role == UserRole.viewer

    async def test_auto_create_disabled_returns_none(self, monkeypatch):
        """With auto-create off and no match, login is rejected."""
        monkeypatch.setattr(settings, "oidc_auto_create_users", False)
        session = _session_returning(None, None)

        user = await _find_or_create_user(session, _userinfo())

        assert user is None

    async def test_email_link_clears_pending_flag(self, monkeypatch):
        """Linking SSO to a local account clears its must_change_password flag."""
        monkeypatch.setattr(settings, "oidc_auto_create_users", False)
        existing = _local_user(must_change=True)
        # No user by external_id, but one matches by email → link.
        session = _session_returning(None, existing)

        user = await _find_or_create_user(session, _userinfo())

        assert user is existing
        assert user.external_id == "sub-123"
        assert user.must_change_password is False

    async def test_existing_linked_user_flag_cleared(self, monkeypatch):
        """An already-linked SSO user with a stale flag gets it cleared."""
        monkeypatch.setattr(settings, "oidc_auto_create_users", False)
        existing = _local_user(must_change=True)
        existing.external_id = "sub-123"
        # Found immediately by external_id.
        session = _session_returning(existing)

        user = await _find_or_create_user(session, _userinfo())

        assert user is existing
        assert user.must_change_password is False


class TestVerifiedEmailGate:
    """The email claim is what links an SSO login to an account, so it needs vouching for.

    Whoever can make a provider assert an address reaches the matching account WITH ITS ROLE —
    an administrator's included. These tests pin the gate in front of both paths that key off the
    address, and pin that the already-linked path is not affected by it.
    """

    async def test_unverified_email_is_refused_for_linking(self, monkeypatch):
        """An existing account is not handed over on an unverified claim."""
        monkeypatch.setattr(settings, "oidc_require_verified_email", True)
        monkeypatch.setattr(settings, "oidc_auto_create_users", False)
        existing = _local_user(must_change=False)
        session = _session_returning(None, existing)

        user = await _find_or_create_user(session, _userinfo(email_verified=False))

        assert user is None
        assert existing.external_id is None, "the account must not have been linked"

    async def test_absent_claim_is_refused_too(self, monkeypatch):
        """A provider that says nothing has not vouched for anything.

        This is the case that matters most: a provider allowing self-registration without
        verification typically OMITS the claim rather than setting it false, so treating absent as
        acceptable would leave the main hole open.
        """
        monkeypatch.setattr(settings, "oidc_require_verified_email", True)
        monkeypatch.setattr(settings, "oidc_auto_create_users", False)
        session = _session_returning(None, _local_user(must_change=False))

        assert (
            await _find_or_create_user(session, _userinfo(email_verified=None)) is None
        )

    async def test_unverified_email_is_refused_for_creation(self, monkeypatch):
        """Auto-creation is gated too, so an unverified address cannot squat an account."""
        monkeypatch.setattr(settings, "oidc_require_verified_email", True)
        monkeypatch.setattr(settings, "oidc_auto_create_users", True)
        session = _session_returning(None, None)

        assert (
            await _find_or_create_user(session, _userinfo(email_verified=False)) is None
        )

    async def test_gate_does_not_affect_an_already_linked_account(self, monkeypatch):
        """Matching on external_id needs no email trust — the subject IS the identity.

        Refusing here would lock out every SSO user the moment a provider stopped sending the
        claim, which is a self-inflicted outage rather than a safeguard.
        """
        monkeypatch.setattr(settings, "oidc_require_verified_email", True)
        existing = _local_user(must_change=False)
        existing.external_id = "sub-123"
        session = _session_returning(existing)

        user = await _find_or_create_user(session, _userinfo(email_verified=None))

        assert user is existing

    async def test_gate_can_be_switched_off(self, monkeypatch):
        """For a provider that omits the claim and whose addresses the operator trusts."""
        monkeypatch.setattr(settings, "oidc_require_verified_email", False)
        monkeypatch.setattr(settings, "oidc_auto_create_users", False)
        existing = _local_user(must_change=True)
        session = _session_returning(None, existing)

        user = await _find_or_create_user(session, _userinfo(email_verified=None))

        assert user is existing
        assert user.external_id == "sub-123"
