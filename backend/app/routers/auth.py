"""Authentication router: login, refresh, change-password, logout, and initial setup."""

import asyncio
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.config import settings
from app.database import get_session
from app.models.user import RefreshToken, User, UserRole
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    SetupRequest,
    SetupStatusResponse,
    UserInfo,
    UserScopes,
)
from app.services.auth_service import (
    create_access_token,
    create_refresh_token,
    hash_password,
    validate_refresh_token,
    verify_password,
)
from app.services.permissions import get_authenticated_user
from app.utils.auth_cookies import clear_refresh_cookie, set_refresh_cookie
from app.utils.rate_limit import rate_limit_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Precomputed bcrypt hash of a random value. Verified against when the email
# is unknown so login timing does not reveal whether an account exists
# (mitigates user enumeration via response-time side channel).
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


async def _revoke_all_user_tokens(session: AsyncSession, user_id: UUID) -> None:
    """Revoke every active refresh token for a user (family revocation).

    Args:
        session: Database session (not committed here).
        user_id: The user whose tokens should be revoked.

    """
    now = datetime.now(UTC).replace(tzinfo=None)
    statement = select(RefreshToken).where(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    )
    result = await session.execute(statement)
    for token in result.scalars().all():
        token.revoked_at = now
        session.add(token)


async def _delete_expired_tokens(session: AsyncSession) -> None:
    """Delete refresh tokens that are past expiry (revoked or not).

    Revoked-but-unexpired tokens are intentionally retained so that reuse
    of a rotated-out token can still be detected within its lifetime.

    Args:
        session: Database session (not committed here).

    """
    now = datetime.now(UTC).replace(tzinfo=None)
    await session.execute(delete(RefreshToken).where(RefreshToken.expires_at < now))


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate with email and password",
    dependencies=[Depends(rate_limit_auth)],
    responses={
        401: {"description": "Invalid credentials or account deactivated"},
        429: {"description": "Too many requests"},
    },
)
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    """Authenticate a user with email and password.

    Returns a short-lived access token in the body and sets the refresh token
    as an httpOnly cookie (never exposed to JavaScript).

    Args:
        body: Login credentials (email and password).
        response: Response used to attach the refresh-token cookie.
        session: Database session.

    Returns:
        Access token and user profile info.

    Raises:
        HTTPException: 401 if credentials are invalid or user is deactivated.

    """
    # Look up user by email
    statement = select(User).where(User.email == body.email)
    result = await session.execute(statement)
    user = result.scalar_one_or_none()

    # Always run a bcrypt verification — against the real hash if the user
    # exists, otherwise against a dummy hash — so the response time does not
    # leak whether the email is registered.
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = await asyncio.to_thread(verify_password, body.password, password_hash)

    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account deactivated",
        )

    # Create tokens
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
        must_change_password=user.must_change_password,
    )

    raw_refresh, token_hash, expires_at = create_refresh_token()

    # Store refresh token in database
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(refresh_record)
    await session.commit()

    set_refresh_cookie(response, raw_refresh)
    return LoginResponse(
        access_token=access_token,
        user=UserInfo(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            must_change_password=user.must_change_password,
            scopes=UserScopes(
                scope_group_ids=user.scope_group_ids,
                scope_project_ids=user.scope_project_ids,
            ),
        ),
    )


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    summary="Obtain a new access token using a refresh token",
    responses={
        401: {"description": "Invalid, expired, or revoked refresh token"},
    },
)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> RefreshResponse:
    """Exchange the refresh-token cookie for a new access token.

    Rotates the refresh token (issuing a fresh httpOnly cookie). Replay of a
    just-rotated token within the configured grace window is treated as a
    benign concurrent refresh (e.g. two browser tabs); replay outside the
    window — or of a logged-out token — is treated as theft and revokes the
    user's entire refresh-token family.

    Args:
        request: Incoming request (source of the refresh cookie).
        response: Response used to set/clear the refresh-token cookie.
        session: Database session.

    Returns:
        A new access token.

    Raises:
        HTTPException: 401 if the refresh token is missing, invalid, expired,
            revoked outside the grace window, or the user is inactive.

    """
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    statement = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    result = await session.execute(statement)
    stored_token = result.scalar_one_or_none()

    if stored_token is None:
        clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    now = datetime.now(UTC).replace(tzinfo=None)

    if stored_token.revoked_at is not None:
        # The token was already revoked — either rotated out (replaced_by_id
        # set) or logged out. A rotated token replayed within the grace window
        # is a benign concurrent refresh; anything else is treated as theft.
        grace = timedelta(seconds=settings.refresh_reuse_grace_seconds)
        within_grace = (
            stored_token.replaced_by_id is not None
            and (now - stored_token.revoked_at) <= grace
        )
        if not within_grace:
            logger.warning(
                "Refresh token reuse detected for user %s; revoking all tokens.",
                stored_token.user_id,
            )
            await _revoke_all_user_tokens(session, stored_token.user_id)
            await session.commit()
            clear_refresh_cookie(response)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        logger.info(
            "Concurrent refresh within grace window for user %s.",
            stored_token.user_id,
        )
    elif not validate_refresh_token(
        raw_token=raw_token,
        stored_hash=stored_token.token_hash,
        expires_at=stored_token.expires_at,
        revoked_at=stored_token.revoked_at,
    ):
        clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Load the user to get current role and scopes
    user_statement = select(User).where(User.id == stored_token.user_id)
    user_result = await session.execute(user_statement)
    user = user_result.scalar_one_or_none()

    if user is None or not user.is_active:
        clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Issue new access token with current role/scopes
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
        must_change_password=user.must_change_password,
    )

    # Issue a new refresh token.
    raw_refresh, new_token_hash, expires_at = create_refresh_token()
    new_refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=new_token_hash,
        expires_at=expires_at,
    )
    session.add(new_refresh_record)

    # Only rotate (revoke + chain) when the presented token was still active.
    # For a grace re-issue the token is already revoked; leave it as-is.
    if stored_token.revoked_at is None:
        stored_token.revoked_at = now
        stored_token.replaced_by_id = new_refresh_record.id
        session.add(stored_token)

    # Opportunistic cleanup of expired rows so the table does not grow
    # unbounded. Revoked-but-unexpired rows are kept for reuse detection.
    await _delete_expired_tokens(session)

    await session.commit()

    set_refresh_cookie(response, raw_refresh)
    return RefreshResponse(access_token=access_token)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change the current user's password",
    responses={
        401: {"description": "Invalid old password"},
    },
)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Change the authenticated user's password.

    Validates the old password before accepting the new one. Clears the
    must_change_password flag on success.

    Args:
        body: Old and new passwords.
        current_user: The authenticated user (from JWT).
        session: Database session.

    Returns:
        204 No Content on success.

    Raises:
        HTTPException: 401 if the old password is incorrect.

    """
    if not await asyncio.to_thread(
        verify_password, body.old_password, current_user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid old password",
        )

    # Update password and clear must_change_password flag
    current_user.password_hash = await asyncio.to_thread(
        hash_password, body.new_password
    )
    current_user.must_change_password = False
    current_user.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.add(current_user)
    await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token (logout)",
)
async def logout(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke the refresh-token cookie, effectively logging the user out.

    Args:
        request: Incoming request (source of the refresh cookie).
        session: Database session.

    Returns:
        204 No Content on success (even if token was already revoked, missing,
        or not found). The refresh-token cookie is always cleared.

    """
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        statement = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await session.execute(statement)
        stored_token = result.scalar_one_or_none()

        if stored_token is not None and stored_token.revoked_at is None:
            stored_token.revoked_at = datetime.now(UTC).replace(tzinfo=None)
            session.add(stored_token)
            await session.commit()

    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(resp)
    return resp


@router.get(
    "/setup-status",
    response_model=SetupStatusResponse,
    summary="Check if initial setup is required",
)
async def setup_status(
    session: AsyncSession = Depends(get_session),
) -> SetupStatusResponse:
    """Check whether the application needs initial setup.

    Returns required=true when no users exist in the database, indicating
    that the first admin user needs to be created via the setup endpoint.

    Args:
        session: Database session.

    Returns:
        Object with a boolean `required` field.

    """
    count_statement = select(func.count()).select_from(User)
    result = await session.execute(count_statement)
    user_count = result.scalar_one()
    return SetupStatusResponse(required=user_count == 0)


@router.post(
    "/setup",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the first admin user (initial setup)",
    dependencies=[Depends(rate_limit_auth)],
    responses={
        403: {"description": "Setup already completed (users exist)"},
        429: {"description": "Too many requests"},
    },
)
async def setup(
    body: SetupRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    """Create the first admin user during initial application setup.

    This endpoint is only available when no users exist in the database.
    Once a user has been created, subsequent calls return 403.

    Args:
        body: Admin user details (name, email, password).
        response: Response used to attach the refresh-token cookie.
        session: Database session.

    Returns:
        Login response with access token and user info (refresh token is set
        as an httpOnly cookie).

    Raises:
        HTTPException: 403 if users already exist (setup already completed).

    """
    # Verify no users exist
    count_statement = select(func.count()).select_from(User)
    result = await session.execute(count_statement)
    user_count = result.scalar_one()

    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed",
        )

    # Create the first admin user (no must_change_password since they set it now)
    user = User(
        email=body.email,
        name=body.name,
        password_hash=await asyncio.to_thread(hash_password, body.password),
        role=UserRole.admin,
        is_active=True,
        must_change_password=False,
    )
    session.add(user)
    await session.flush()

    # Issue tokens so the user is logged in immediately
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
        must_change_password=user.must_change_password,
    )

    raw_refresh, token_hash, expires_at = create_refresh_token()
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(refresh_record)
    await session.commit()

    set_refresh_cookie(response, raw_refresh)
    return LoginResponse(
        access_token=access_token,
        user=UserInfo(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            must_change_password=user.must_change_password,
            scopes=UserScopes(
                scope_group_ids=user.scope_group_ids,
                scope_project_ids=user.scope_project_ids,
            ),
        ),
    )
