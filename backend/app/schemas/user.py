"""Pydantic request/response schemas for user management endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserCreateRequest(BaseModel):
    """Request body for POST /api/users (admin creates a new user)."""

    name: str = Field(..., min_length=1, max_length=255, description="User full name")
    email: str = Field(
        ..., min_length=1, max_length=255, description="Unique email address"
    )
    password: str = Field(
        ..., min_length=8, description="Initial password (min 8 chars)"
    )
    role: str = Field(
        default="viewer",
        description="User role: admin, editor, or viewer",
    )
    scope_group_ids: list[UUID] | None = Field(
        default=None, description="Resource group IDs the editor can manage"
    )
    scope_project_ids: list[UUID] | None = Field(
        default=None, description="Project IDs the editor can manage"
    )


class UserUpdateRequest(BaseModel):
    """Request body for PUT /api/users/{id} (admin updates a user)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(
        default=None, description="New role: admin, editor, or viewer"
    )
    scope_group_ids: list[UUID] | None = Field(default=None)
    scope_project_ids: list[UUID] | None = Field(default=None)
    password: str | None = Field(
        default=None,
        min_length=8,
        description=(
            "Reset this user's password. The user must change it at next login. "
            "Omit the field to leave the password untouched."
        ),
    )
    resource_id: UUID | None = Field(
        default=None,
        description=(
            "Link this account to the scheduled person it belongs to, which is what lets that "
            "person read their own plan. Omit the field to leave the link untouched; see "
            "clear_resource_id to remove one."
        ),
    )
    clear_resource_id: bool = Field(
        default=False,
        description=(
            "Remove the link to a scheduled person. A separate flag because omitting "
            "resource_id has to mean 'leave alone' — otherwise every rename would unlink."
        ),
    )


class UserResponse(BaseModel):
    """Response body representing a user."""

    id: UUID
    email: str
    name: str
    role: str
    scope_group_ids: list[UUID] | None = None
    scope_project_ids: list[UUID] | None = None
    is_active: bool
    must_change_password: bool
    resource_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Paginated list of users."""

    items: list[UserResponse]
    total: int
