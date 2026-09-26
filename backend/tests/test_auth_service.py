"""Unit tests for app.services.auth_service.

Covers password hashing round-trip, JWT encode/decode, token expiry,
and refresh token validation logic.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.exceptions import BusinessRuleError
from app.services.auth_service import (
    _hash_refresh_token,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    validate_refresh_token,
    verify_password,
)


# Override the autouse database fixture — these tests are pure unit tests
# that don't need the test database.
@pytest.fixture(autouse=True)
def setup_database():
    """No-op override: auth service tests don't need the test database."""
    yield


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    """Tests for hash_password and verify_password."""

    def test_hash_and_verify_roundtrip(self):
        """A hashed password verifies correctly."""
        password = "secure-password-123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        """A wrong password does not verify."""
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_is_not_plaintext(self):
        """The hash is not the same as the plain password."""
        password = "my-secret"
        hashed = hash_password(password)
        assert hashed != password

    def test_different_hashes_for_same_password(self):
        """Bcrypt produces different hashes for the same input (salted)."""
        password = "same-password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2
        # Both still verify
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True

    def test_long_password_handled(self):
        """Passwords longer than 72 bytes are handled via pre-hashing."""
        long_password = "a" * 200
        hashed = hash_password(long_password)
        assert verify_password(long_password, hashed) is True
        assert verify_password("wrong", hashed) is False

    @given(password=st.text(min_size=1, max_size=200))
    @settings(max_examples=20, deadline=timedelta(seconds=5))
    def test_hash_verify_roundtrip_property(self, password: str):
        """For any password, hash then verify always returns True."""
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    @given(
        password=st.text(min_size=1, max_size=50),
        other=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=20, deadline=timedelta(seconds=5))
    def test_different_password_never_verifies_property(
        self, password: str, other: str
    ):
        """A different password never verifies against the hash."""
        assume(password != other)
        hashed = hash_password(password)
        assert verify_password(other, hashed) is False


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


class TestAccessToken:
    """Tests for create_access_token and decode_access_token."""

    def _make_token(self, **kwargs):
        """Helper to create a token with default values."""
        defaults = {
            "user_id": uuid4(),
            "role": "editor",
            "scopes": {
                "scope_group_ids": None,
                "scope_project_ids": None,
            },
        }
        defaults.update(kwargs)
        return create_access_token(**defaults), defaults

    def test_encode_decode_roundtrip(self):
        """A freshly created token decodes successfully."""
        user_id = uuid4()
        token = create_access_token(
            user_id=user_id,
            role="admin",
            scopes={
                "scope_group_ids": None,
                "scope_project_ids": None,
            },
        )
        payload = decode_access_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_payload_contains_scopes(self):
        """Token payload includes serialized scopes."""
        group_id = uuid4()
        project_id = uuid4()
        token = create_access_token(
            user_id=uuid4(),
            role="editor",
            scopes={
                "scope_group_ids": [group_id],
                "scope_project_ids": [project_id],
            },
        )
        payload = decode_access_token(token)
        assert payload["scopes"]["scope_group_ids"] == [str(group_id)]
        assert payload["scopes"]["scope_project_ids"] == [str(project_id)]

    def test_expired_token_raises(self):
        """An expired token raises BusinessRuleError on decode."""
        token = create_access_token(
            user_id=uuid4(),
            role="viewer",
            scopes={},
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(BusinessRuleError, match="Token expired"):
            decode_access_token(token)

    def test_invalid_token_string_raises(self):
        """A garbage string raises BusinessRuleError."""
        with pytest.raises(BusinessRuleError, match="Invalid token"):
            decode_access_token("not-a-valid-jwt")

    def test_token_type_must_be_access(self):
        """A token with wrong type field is rejected."""
        import jwt as pyjwt

        from app.services.auth_service import JWT_ALGORITHM, JWT_SECRET_KEY

        payload = {
            "sub": str(uuid4()),
            "role": "admin",
            "scopes": {},
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
            "type": "refresh",
        }
        token = pyjwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        with pytest.raises(BusinessRuleError, match="not an access token"):
            decode_access_token(token)

    @given(role=st.sampled_from(["admin", "editor", "viewer"]))
    @settings(max_examples=10)
    def test_role_preserved_in_token_property(self, role: str):
        """The role encoded in the token is always the role decoded."""
        user_id = uuid4()
        token = create_access_token(
            user_id=user_id,
            role=role,
            scopes={},
        )
        payload = decode_access_token(token)
        assert payload["role"] == role
        assert payload["sub"] == str(user_id)


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------


class TestRefreshToken:
    """Tests for create_refresh_token and validate_refresh_token."""

    def test_create_returns_triple(self):
        """create_refresh_token returns (raw, hash, expires_at)."""
        raw, token_hash, expires_at = create_refresh_token()
        assert isinstance(raw, str)
        assert len(raw) > 32
        assert isinstance(token_hash, str)
        assert len(token_hash) == 64  # SHA-256 hex
        assert isinstance(expires_at, datetime)
        assert expires_at > datetime.now(UTC)

    def test_validate_valid_token(self):
        """A fresh token validates successfully."""
        raw, token_hash, expires_at = create_refresh_token()
        assert validate_refresh_token(raw, token_hash, expires_at, None) is True

    def test_validate_wrong_token(self):
        """A different raw token does not validate."""
        _, token_hash, expires_at = create_refresh_token()
        assert (
            validate_refresh_token("wrong-token", token_hash, expires_at, None) is False
        )

    def test_validate_expired_token(self):
        """An expired token does not validate."""
        raw, token_hash, _ = create_refresh_token()
        expired_at = datetime.now(UTC) - timedelta(hours=1)
        assert validate_refresh_token(raw, token_hash, expired_at, None) is False

    def test_validate_revoked_token(self):
        """A revoked token does not validate."""
        raw, token_hash, expires_at = create_refresh_token()
        revoked_at = datetime.now(UTC)
        assert validate_refresh_token(raw, token_hash, expires_at, revoked_at) is False

    def test_hash_is_deterministic(self):
        """The same raw token always produces the same hash."""
        raw, token_hash, _ = create_refresh_token()
        assert _hash_refresh_token(raw) == token_hash

    @given(st.data())
    @settings(max_examples=15)
    def test_fresh_token_always_validates_property(self, data):
        """A freshly created refresh token always validates when not expired and not revoked."""
        raw, token_hash, expires_at = create_refresh_token()
        assert validate_refresh_token(raw, token_hash, expires_at, None) is True

    @given(
        days_expired=st.integers(min_value=1, max_value=365),
    )
    @settings(max_examples=10)
    def test_expired_token_never_validates_property(self, days_expired: int):
        """An expired refresh token never validates."""
        raw, token_hash, _ = create_refresh_token()
        expired_at = datetime.now(UTC) - timedelta(days=days_expired)
        assert validate_refresh_token(raw, token_hash, expired_at, None) is False
