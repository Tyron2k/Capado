"""Authentication service: password hashing and JWT token management."""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt

from app.config import settings
from app.exceptions import BusinessRuleError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (sourced from the centralized settings object)
# ---------------------------------------------------------------------------

JWT_SECRET_KEY: str = settings.jwt_secret_key
JWT_ALGORITHM: str = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES: int = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS: int = settings.refresh_token_expire_days


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


BCRYPT_WORK_FACTOR: int = settings.bcrypt_work_factor


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt.

    Uses a configurable work factor (default 12, minimum 10) via the
    BCRYPT_WORK_FACTOR environment variable. Passwords longer than 72 bytes
    are pre-hashed with SHA-256 to stay within bcrypt's input limit while
    preserving entropy.

    Args:
        plain_password: The user-supplied password in plain text.

    Returns:
        The bcrypt hash string suitable for storage.

    """
    password_bytes = _prepare_password(plain_password)
    salt = bcrypt.gensalt(rounds=BCRYPT_WORK_FACTOR)
    return bcrypt.hashpw(password_bytes, salt).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a stored bcrypt hash.

    Args:
        plain_password: The user-supplied password to check.
        hashed_password: The stored bcrypt hash.

    Returns:
        True if the password matches, False otherwise.

    """
    password_bytes = _prepare_password(plain_password)
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode())
    except (ValueError, TypeError):
        return False


def _prepare_password(plain_password: str) -> bytes:
    """Encode password to bytes, pre-hashing if over 72 bytes.

    Args:
        plain_password: The plain-text password.

    Returns:
        Bytes suitable for bcrypt input (always <= 72 bytes).

    """
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > 72:
        # Pre-hash with SHA-256 to fit bcrypt's 72-byte limit. This is NOT the password hash:
        # bcrypt (hash_password, above) is the computationally expensive hash that is stored.
        # SHA-256 only condenses inputs longer than bcrypt's 72-byte cutoff so that two long
        # passwords sharing a 72-byte prefix are not treated as equal — the practice bcrypt's
        # own docs and OWASP recommend. CodeQL sees the isolated sha256() call and cannot follow
        # the chain, so this is a false positive; suppressed rather than "fixed" into worse code.
        password_bytes = (
            hashlib.sha256(  # codeql[py/weak-sensitive-data-hashing]
                password_bytes
            )
            .hexdigest()
            .encode("utf-8")
        )
    return password_bytes


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


def create_access_token(
    user_id: UUID,
    role: str,
    scopes: dict[str, list[str] | list[UUID] | None],
    *,
    email: str | None = None,
    name: str | None = None,
    must_change_password: bool = False,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a short-lived JWT access token with role and scopes in the payload.

    Args:
        user_id: The user's unique identifier.
        role: The user's role (admin, editor, viewer).
        scopes: Dict with scope_departments, scope_locations, scope_project_ids.
        email: The user's email address (included for client-side decoding).
        name: The user's display name (included for client-side decoding).
        must_change_password: Whether the user must change their password.
        expires_delta: Optional custom expiry duration. Defaults to
            ACCESS_TOKEN_EXPIRE_MINUTES.

    Returns:
        Encoded JWT string.

    """
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    # Serialize UUIDs in scope_project_ids to strings for JSON compatibility
    serialized_scopes: dict[str, list[str] | None] = {}
    for key, value in scopes.items():
        if value is None:
            serialized_scopes[key] = None
        else:
            serialized_scopes[key] = [str(v) for v in value]

    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "role": role,
        "must_change_password": must_change_password,
        "scopes": serialized_scopes,
        "exp": expire,
        "iat": now,
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Args:
        token: The encoded JWT string.

    Returns:
        The decoded payload dictionary with keys: sub, role, scopes, exp, iat, type.

    Raises:
        BusinessRuleError: If the token is invalid, expired, or not an access token.

    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise BusinessRuleError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise BusinessRuleError(f"Invalid token: {exc}") from exc

    if payload.get("type") != "access":
        raise BusinessRuleError("Token is not an access token")

    return payload


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------


def _hash_refresh_token(raw_token: str) -> str:
    """Create a SHA-256 hash of a raw refresh token for database storage.

    Args:
        raw_token: The plain-text refresh token.

    Returns:
        Hex-encoded SHA-256 hash.

    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_refresh_token() -> tuple[str, str, datetime]:
    """Generate a new refresh token with its hash and expiry.

    Returns:
        A tuple of (raw_token, token_hash, expires_at) where:
        - raw_token is sent to the client
        - token_hash is stored in the database
        - expires_at is the expiration timestamp

    """
    raw_token = secrets.token_urlsafe(64)
    token_hash = _hash_refresh_token(raw_token)
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
        days=REFRESH_TOKEN_EXPIRE_DAYS
    )
    return raw_token, token_hash, expires_at


def validate_refresh_token(
    raw_token: str,
    stored_hash: str,
    expires_at: datetime,
    revoked_at: datetime | None,
) -> bool:
    """Validate a refresh token against its stored hash and metadata.

    Args:
        raw_token: The plain-text refresh token from the client.
        stored_hash: The SHA-256 hash stored in the database.
        expires_at: The token's expiration timestamp.
        revoked_at: When the token was revoked, or None if still active.

    Returns:
        True if the token is valid (hash matches, not expired, not revoked).

    """
    if revoked_at is not None:
        return False

    now = datetime.now(UTC).replace(tzinfo=None)
    if now >= expires_at:
        return False

    computed_hash = _hash_refresh_token(raw_token)
    return secrets.compare_digest(computed_hash, stored_hash)
