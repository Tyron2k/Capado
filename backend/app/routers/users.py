"""User management router: admin CRUD operations and user profile."""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.database import get_session
from app.models.resource import PersonalResource
from app.models.user import RefreshToken, User
from app.schemas.user import (
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.services.auth_service import hash_password
from app.services.permissions import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the authenticated user's profile.

    Args:
        current_user: The authenticated user from JWT.

    Returns:
        The current user's profile data.

    """
    return UserResponse.model_validate(current_user)


@router.get(
    "",
    response_model=UserListResponse,
    summary="List all users (admin only)",
    responses={403: {"description": "Insufficient permissions"}},
)
async def list_users(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=50, ge=1, le=200, description="Max records to return"),
    admin_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserListResponse:
    """List all users with pagination (admin only).

    Args:
        skip: Number of records to skip for pagination.
        limit: Maximum number of records to return.
        admin_user: The authenticated admin user.
        session: Database session.

    Returns:
        Paginated list of users with total count.

    """
    # Count total users
    count_statement = select(func.count()).select_from(User)
    count_result = await session.execute(count_statement)
    total = count_result.scalar_one()

    # Fetch paginated users
    statement = select(User).offset(skip).limit(limit).order_by(User.created_at)
    result = await session.execute(statement)
    users = result.scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (admin only)",
    responses={
        403: {"description": "Insufficient permissions"},
        409: {"description": "Email already exists"},
    },
)
async def create_user(
    body: UserCreateRequest,
    admin_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Create a new user with the specified details.

    The new user will have must_change_password=true, requiring them to
    change their password on first login.

    Args:
        body: User creation data (name, email, password, role, scopes).
        admin_user: The authenticated admin user.
        session: Database session.

    Returns:
        The newly created user.

    Raises:
        HTTPException: 409 if email already exists.

    """
    # Check email uniqueness
    existing_statement = select(User).where(User.email == body.email)
    existing_result = await session.execute(existing_statement)
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists",
        )

    # Create user with hashed password
    user = User(
        email=body.email,
        name=body.name,
        password_hash=await asyncio.to_thread(hash_password, body.password),
        role=body.role,
        scope_group_ids=body.scope_group_ids,
        scope_project_ids=body.scope_project_ids,
        is_active=True,
        must_change_password=True,
    )
    session.add(user)
    await session.commit()

    return UserResponse.model_validate(user)


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a user (admin only)",
    responses={
        403: {"description": "Insufficient permissions"},
        404: {"description": "User not found"},
    },
)
async def update_user(
    user_id: UUID,
    body: UserUpdateRequest,
    admin_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Update a user's name, role, scopes, or password.

    Passing ``password`` resets it and sets ``must_change_password``, so the account is usable
    immediately and the admin's chosen value is replaced by one only the user knows at next login.
    It exists because there is no self-service reset: no forgot-password flow and no reset mail
    (see docs/reference/known-limitations.md).

    An SSO account can be given a password here too. That is deliberate — it adds a local fallback
    for when the identity provider is unreachable — but note the OIDC login clears the
    must-change flag, because the SSO path cannot satisfy a change that requires the old password.

    Args:
        user_id: The ID of the user to update.
        body: Fields to update (only provided fields are changed).
        admin_user: The authenticated admin user.
        session: Database session.

    Returns:
        The updated user.

    Raises:
        HTTPException: 404 if user not found.

    """
    statement = select(User).where(User.id == user_id)
    result = await session.execute(statement)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Apply updates for provided fields
    if body.name is not None:
        user.name = body.name
    if body.role is not None:
        user.role = body.role
    if body.scope_group_ids is not None:
        user.scope_group_ids = body.scope_group_ids
    if body.scope_project_ids is not None:
        user.scope_project_ids = body.scope_project_ids
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        # The admin knows this value, so it is a handover credential rather than a password.
        user.must_change_password = True
        # The audit entry records THAT it changed; audit.REDACTED_FIELDS keeps the hash out.
        logger.info("Admin %s reset the password of user %s", admin_user.id, user.id)
    if body.clear_resource_id:
        user.resource_id = None
    elif body.resource_id is not None:
        # Checked here rather than left to the foreign key: a 404 naming the resource is a usable
        # answer, while an IntegrityError surfaces as a 500 and tells the admin nothing.
        target = await session.get(PersonalResource, body.resource_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Personal resource not found",
            )
        # The column is unique, so a person already claimed by another account is a conflict rather
        # than a silent reassignment — "my plan" must not answer differently per account.
        clash_stmt = select(User).where(
            User.resource_id == body.resource_id, User.id != user.id
        )
        clash_result = await session.execute(clash_stmt)
        if clash_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That person is already linked to another account",
                headers={"X-Error-Code": "resource_already_linked"},
            )
        user.resource_id = body.resource_id

    user.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.add(user)
    await session.commit()

    return UserResponse.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a user (admin only, soft-delete)",
    responses={
        403: {"description": "Insufficient permissions"},
        404: {"description": "User not found"},
    },
)
async def delete_user(
    user_id: UUID,
    admin_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Soft-delete a user by setting is_active=false and revoking refresh tokens.

    Args:
        user_id: The ID of the user to deactivate.
        admin_user: The authenticated admin user.
        session: Database session.

    Returns:
        204 No Content on success.

    Raises:
        HTTPException: 404 if user not found.

    """
    statement = select(User).where(User.id == user_id)
    result = await session.execute(statement)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Soft-delete: deactivate user
    user.is_active = False
    user.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(user)

    # Revoke all active refresh tokens for this user
    now = datetime.now(UTC).replace(tzinfo=None)
    token_statement = select(RefreshToken).where(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    )
    token_result = await session.execute(token_statement)
    tokens = token_result.scalars().all()

    for token in tokens:
        token.revoked_at = now
        session.add(token)

    await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{user_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete a user (admin only, hard-delete)",
    responses={
        403: {"description": "Insufficient permissions or cannot delete yourself"},
        404: {"description": "User not found"},
    },
)
async def permanently_delete_user(
    user_id: UUID,
    admin_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Permanently remove a user and all associated data from the database.

    This is irreversible. Deletes refresh tokens and the user record.
    An admin cannot delete their own account.

    Args:
        user_id: The ID of the user to permanently delete.
        admin_user: The authenticated admin user.
        session: Database session.

    Returns:
        204 No Content on success.

    Raises:
        HTTPException: 403 if trying to delete own account.
        HTTPException: 404 if user not found.

    """
    if admin_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete your own account",
        )

    statement = select(User).where(User.id == user_id)
    result = await session.execute(statement)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Delete all refresh tokens for this user
    token_statement = select(RefreshToken).where(RefreshToken.user_id == user_id)
    token_result = await session.execute(token_statement)
    tokens = token_result.scalars().all()
    for token in tokens:
        await session.delete(token)

    # Delete the user
    await session.delete(user)
    await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
