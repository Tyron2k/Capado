"""An administrator resetting another user's password.

There is no self-service reset in Capado — no forgot-password flow and no reset mail — so this
endpoint is the only way back in for a user who has lost their password, short of writing a bcrypt
hash into the table by hand. See docs/reference/known-limitations.md.

Two properties matter beyond "the hash changed", and both are pinned here: the value the admin
chose is a HANDOVER credential, so the account must be forced to replace it; and the audit entry
must record the event without the material, which is covered by
``audit.REDACTED_FIELDS`` and its own tests in test_audit.py.

A mock session stands in for the database, matching the style of the other router tests.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.user import User, UserRole
from app.routers.users import update_user
from app.schemas.user import UserUpdateRequest
from app.services.auth_service import hash_password, verify_password


@pytest.fixture(autouse=True)
def setup_database():
    """No-op override: these tests use a mock session, not the test database."""
    yield


def _user(**overrides: object) -> User:
    """Build a fake target account with clearly fictional values."""
    defaults: dict[str, object] = {
        "id": uuid4(),
        "email": "target.user@example.test",
        "name": "Target User",
        "password_hash": hash_password("the-old-password"),
        "role": UserRole.editor,
        "is_active": True,
        "must_change_password": False,
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


def _session_returning(user: User | None) -> AsyncMock:
    """Mock session whose single execute() yields the given user."""
    result = MagicMock()
    result.scalar_one_or_none = lambda: user
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    return session


def _admin() -> User:
    """The acting administrator."""
    return _user(email="admin@example.test", name="Admin", role=UserRole.admin)


class TestAdminPasswordReset:
    """Setting someone else's password, and what must follow from it."""

    async def test_password_is_replaced(self):
        """The new value works and the old one stops working."""
        target = _user()
        session = _session_returning(target)

        await update_user(
            target.id,
            UserUpdateRequest(password="a-fresh-password"),
            admin_user=_admin(),
            session=session,
        )

        assert verify_password("a-fresh-password", target.password_hash)
        assert not verify_password("the-old-password", target.password_hash)

    async def test_reset_forces_a_change_at_next_login(self):
        """The admin knows this value, so it is a handover credential, not a password."""
        target = _user(must_change_password=False)
        session = _session_returning(target)

        await update_user(
            target.id,
            UserUpdateRequest(password="a-fresh-password"),
            admin_user=_admin(),
            session=session,
        )

        assert target.must_change_password is True

    async def test_omitting_the_field_leaves_the_password_alone(self):
        """A rename must not silently invalidate someone's login."""
        target = _user()
        before = target.password_hash
        session = _session_returning(target)

        await update_user(
            target.id,
            UserUpdateRequest(name="Renamed User"),
            admin_user=_admin(),
            session=session,
        )

        assert target.password_hash == before
        assert target.must_change_password is False
        assert target.name == "Renamed User"

    async def test_the_stored_value_is_not_the_plaintext(self):
        """Obvious, and worth a test precisely because it would be silent if wrong."""
        target = _user()
        session = _session_returning(target)

        await update_user(
            target.id,
            UserUpdateRequest(password="a-fresh-password"),
            admin_user=_admin(),
            session=session,
        )

        assert "a-fresh-password" not in target.password_hash

    async def test_short_password_is_refused_by_the_schema(self):
        """Eight characters, matching the setup endpoint rather than a second rule."""
        with pytest.raises(ValueError):
            UserUpdateRequest(password="short")

    async def test_missing_user_is_a_404(self):
        """Resetting a password on a user that does not exist must not be a 200."""
        from fastapi import HTTPException

        session = _session_returning(None)

        with pytest.raises(HTTPException) as exc_info:
            await update_user(
                uuid4(),
                UserUpdateRequest(password="a-fresh-password"),
                admin_user=_admin(),
                session=session,
            )

        assert exc_info.value.status_code == 404
