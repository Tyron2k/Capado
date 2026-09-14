"""Pydantic request/response schemas for authentication endpoints."""

from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Request body for POST /api/auth/login."""

    email: str = Field(..., min_length=1, description="User email address")
    password: str = Field(..., min_length=1, description="User password")


class ChangePasswordRequest(BaseModel):
    """Request body for POST /api/auth/change-password."""

    old_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(
        ..., min_length=8, description="New password (min 8 chars)"
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UserScopes(BaseModel):
    """User scope fields included in login response."""

    scope_group_ids: list[UUID] | None = None
    scope_project_ids: list[UUID] | None = None


class UserInfo(BaseModel):
    """User profile info returned in login response."""

    id: UUID
    email: str
    name: str
    role: str
    must_change_password: bool = False
    scopes: UserScopes


class LoginResponse(BaseModel):
    """Response body for POST /api/auth/login.

    The refresh token is delivered separately as an httpOnly cookie, not in
    the body, so it is never exposed to JavaScript.
    """

    access_token: str
    user: UserInfo


class RefreshResponse(BaseModel):
    """Response body for POST /api/auth/refresh.

    The rotated refresh token is delivered as an httpOnly cookie, not here.
    """

    access_token: str


# ---------------------------------------------------------------------------
# Setup schemas
# ---------------------------------------------------------------------------


class SetupRequest(BaseModel):
    """Request body for POST /api/auth/setup (first admin user creation)."""

    name: str = Field(..., min_length=1, max_length=255, description="Admin user name")
    email: str = Field(
        ..., min_length=1, max_length=255, description="Admin email address"
    )
    password: str = Field(..., min_length=8, description="Admin password (min 8 chars)")


class SetupStatusResponse(BaseModel):
    """Response body for GET /api/auth/setup-status."""

    required: bool = Field(
        ..., description="True if no users exist and setup is needed"
    )
