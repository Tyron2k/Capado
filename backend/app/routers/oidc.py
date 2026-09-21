"""OIDC authentication router: login initiation, callback handling, and status."""

import hashlib
import hmac
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config import settings
from app.database import get_session
from app.models.user import RefreshToken, User, UserRole
from app.services.auth_service import create_access_token, create_refresh_token
from app.services.oidc_service import (
    FRONTEND_URL,
    OIDC_ENABLED,
    OIDCUserInfo,
    build_authorization_url,
    exchange_code_for_tokens,
    generate_state,
    get_userinfo,
)
from app.utils.auth_cookies import set_refresh_cookie
from app.utils.logging import quote_log_value

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oidc", tags=["auth"])

# Secret for signing state cookies. Shares the validated central JWT secret
# (fail-fast in production) — never a weak inline fallback.
_STATE_SECRET = settings.jwt_secret_key

# State expiry in seconds
_STATE_EXPIRY_SECONDS = 300


def _sign_state(state: str) -> str:
    """Create a signed state value with timestamp for verification.

    Args:
        state: The random state string.

    Returns:
        Signed string in format: state.timestamp.signature

    """
    ts = str(int(time.time()))
    payload = f"{state}.{ts}"
    sig = hmac.new(
        _STATE_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{payload}.{sig}"


def _verify_state(signed: str, expected_state: str) -> bool:
    """Verify a signed state cookie value.

    Args:
        signed: The signed cookie value (state.timestamp.signature).
        expected_state: The state parameter from the callback URL.

    Returns:
        True if valid and not expired.

    """
    parts = signed.split(".")
    if len(parts) != 3:
        return False

    state, ts_str, sig = parts

    if state != expected_state:
        return False

    # Check signature
    payload = f"{state}.{ts_str}"
    expected_sig = hmac.new(
        _STATE_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected_sig):
        return False

    # Check expiry
    try:
        ts = int(ts_str)
        if time.time() - ts > _STATE_EXPIRY_SECONDS:
            return False
    except ValueError:
        return False

    return True


@router.get(
    "/enabled",
    summary="Check if OIDC login is available",
    response_model=dict,
)
async def oidc_status() -> dict:
    """Return whether OIDC login is configured and available.

    Returns:
        JSON with `enabled` boolean field.

    """
    return {"enabled": OIDC_ENABLED}


@router.get(
    "/login",
    summary="Initiate OIDC login flow",
    responses={
        302: {"description": "Redirect to OIDC provider"},
        503: {"description": "OIDC not configured"},
    },
)
async def oidc_login() -> RedirectResponse:
    """Redirect the user to the Authentik OIDC authorization endpoint.

    Generates a CSRF state parameter, stores it in a signed cookie,
    and redirects to the identity provider.

    Returns:
        302 redirect to the OIDC authorization URL.

    Raises:
        HTTPException: 503 if OIDC is not configured.

    """
    if not OIDC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC is not configured",
        )

    state = generate_state()
    authorization_url = await build_authorization_url(state)

    response = RedirectResponse(url=authorization_url, status_code=302)
    response.set_cookie(
        key="oidc_state",
        value=_sign_state(state),
        max_age=_STATE_EXPIRY_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get(
    "/callback",
    summary="Handle OIDC callback from identity provider",
    responses={
        302: {"description": "Redirect to frontend with tokens"},
        400: {"description": "Invalid state or missing code"},
        503: {"description": "OIDC not configured"},
    },
)
async def oidc_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    oidc_state: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Handle the OIDC callback after user authenticates with Authentik.

    Validates the state parameter against the signed cookie, exchanges the
    authorization code for tokens, fetches user info, and either links to
    an existing user or creates a new one. Issues Capado JWT tokens and
    redirects to the frontend with the tokens.

    Args:
        code: Authorization code from the OIDC provider.
        state: CSRF state parameter for validation.
        error: Error code if the OIDC provider returned an error.
        error_description: Human-readable error description.
        oidc_state: Signed state cookie set during login initiation.
        session: Database session.

    Returns:
        302 redirect to frontend with access_token and refresh_token as query params.

    Raises:
        HTTPException: 400 if state is invalid or code is missing.
        HTTPException: 503 if OIDC is not configured.

    """
    if not OIDC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC is not configured",
        )

    # Handle provider errors
    if error:
        logger.warning(
            "OIDC provider error: %s — %s",
            quote_log_value(error),
            quote_log_value(error_description),
        )
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=oidc_denied",
            status_code=302,
        )

    # Validate state (CSRF protection via signed cookie)
    if not state or not oidc_state or not _verify_state(oidc_state, state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code",
        )

    # Exchange code for tokens
    try:
        token_response = await exchange_code_for_tokens(code)
    except Exception as exc:
        logger.error("OIDC token exchange failed: %s", exc)
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=oidc_exchange_failed",
            status_code=302,
        )

    # Get user info from provider
    try:
        userinfo = await get_userinfo(token_response["access_token"])
    except Exception as exc:
        logger.error("OIDC userinfo fetch failed: %s", exc)
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=oidc_userinfo_failed",
            status_code=302,
        )

    # Find or create user
    user = await _find_or_create_user(session, userinfo)

    if user is None:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=oidc_no_account",
            status_code=302,
        )

    if not user.is_active:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=account_deactivated",
            status_code=302,
        )

    # Issue Capado tokens
    scopes = {
        "scope_group_ids": user.scope_group_ids,
        "scope_project_ids": user.scope_project_ids,
    }
    access_token = create_access_token(
        user_id=user.id,
        role=user.role,
        scopes=scopes,
        email=user.email,
        name=user.name,
        must_change_password=False,
    )

    raw_refresh, token_hash, expires_at = create_refresh_token()
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(refresh_record)
    await session.commit()

    # Redirect to the frontend with only the short-lived access token in the
    # URL. The long-lived refresh token is set as an httpOnly cookie so it
    # never appears in browser history, logs, or the Referer header.
    redirect_url = f"{FRONTEND_URL}/auth/oidc/callback?access_token={access_token}"
    redirect = RedirectResponse(url=redirect_url, status_code=302)
    set_refresh_cookie(redirect, raw_refresh)
    return redirect


def _clear_password_change_flag(session: AsyncSession, user: User) -> None:
    """Clear ``must_change_password`` for an SSO-authenticated user.

    SSO users authenticate through the identity provider and may not have a
    usable local password, so the forced-password-change gate must never
    block them. Only writes when the flag is currently set.

    Args:
        session: Database session (committed by the caller).
        user: The user authenticated via OIDC.
    """
    if user.must_change_password:
        user.must_change_password = False
        user.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.add(user)


async def _find_or_create_user(
    session: AsyncSession,
    userinfo: OIDCUserInfo,
) -> User | None:
    """Find an existing user by external_id or email, optionally create a new one.

    Links the OIDC subject to the user's external_id field. If a user with the
    same email already exists but has no external_id, it is linked automatically
    (account linking on first SSO login).

    When OIDC_AUTO_CREATE_USERS is disabled (default), users that do not already
    exist in the database are rejected — only email-matching is performed.

    Args:
        session: Database session.
        userinfo: User information from the OIDC provider.

    Returns:
        The matched User, or None if no match and auto-creation is disabled.

    """
    auto_create = settings.oidc_auto_create_users

    # First: look up by external_id (OIDC subject)
    stmt = select(User).where(User.external_id == userinfo.sub)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        # SSO identity is managed by the IdP — no local password to change.
        _clear_password_change_flag(session, user)
        return user

    # Everything below keys off the EMAIL, which makes the address a credential: whoever can get
    # the provider to assert it reaches the matching account, with that account's role. So the
    # provider has to vouch for it first.
    #
    # This gate sits BEFORE both the linking and the creation step on purpose. Putting it only in
    # front of creation would repeat the mistake that oidc_auto_create_users already makes — that
    # flag reads like "nobody unexpected gets in" while the linking path runs ahead of it and
    # reaches existing accounts, administrators included.
    if settings.oidc_require_verified_email and not userinfo.email_verified:
        logger.warning(
            "OIDC login rejected for %s: provider reported email_verified=%s. "
            "Set OIDC_REQUIRE_VERIFIED_EMAIL=false only if your provider omits the claim "
            "and you trust the addresses it asserts.",
            userinfo.email,
            "absent" if userinfo.email_verified is None else userinfo.email_verified,
        )
        return None

    # Second: look up by email (account linking)
    stmt = select(User).where(User.email == userinfo.email)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        # Link the OIDC subject to the existing account
        user.external_id = userinfo.sub
        user.updated_at = datetime.now(UTC).replace(tzinfo=None)
        # Clear any pending forced password change: the account is now
        # authenticated via SSO, so the local password-change flow (which
        # requires the old password) neither applies nor is reachable.
        _clear_password_change_flag(session, user)
        session.add(user)
        await session.flush()
        logger.info(
            "Linked OIDC subject %s to existing user %s (%s)",
            userinfo.sub,
            user.id,
            user.email,
        )
        return user

    # Third: create new user only if auto-creation is enabled
    if not auto_create:
        logger.warning(
            "OIDC login rejected: no matching user for %s (auto-create disabled)",
            userinfo.email,
        )
        return None

    user = User(
        email=userinfo.email,
        name=userinfo.name,
        password_hash="",  # No password for OIDC-only users
        role=UserRole.viewer,
        is_active=True,
        must_change_password=False,
        external_id=userinfo.sub,
    )
    session.add(user)
    await session.flush()
    logger.info("Created new user from OIDC: %s (%s)", user.id, user.email)
    return user
