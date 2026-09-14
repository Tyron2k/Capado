"""SQLModel entities for authentication: User and RefreshToken."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.utils.pg_types import UUIDArray


def _utcnow() -> datetime:
    """UTC timestamp as naive datetime (for TIMESTAMP WITHOUT TIME ZONE)."""
    return datetime.now(UTC).replace(tzinfo=None)


class UserRole(StrEnum):
    """User role determining write-access level."""

    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class User(SQLModel, table=True):
    """Application user with role and optional editor scopes.

    The role determines the level of write access. Editors are further
    restricted by scope fields: only entities in groups matching their
    scope_group_ids or projects matching scope_project_ids can be modified.

    ``resource_id`` links the account to the ``PersonalResource`` it plans, which is what lets that
    person read their OWN plan (``GET /api/me/plan``). Optional on both sides on purpose: most
    scheduled staff never log in, and a planner is usually not scheduled themselves. Unique, so
    "my plan" cannot answer differently depending on which account you used.
    """

    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(max_length=255, unique=True, nullable=False)
    name: str = Field(max_length=255, nullable=False)
    password_hash: str = Field(max_length=255, nullable=False)
    role: str = Field(
        default=UserRole.viewer,
        sa_column=Column(
            SAEnum(
                "admin",
                "editor",
                "viewer",
                name="userrole",
                create_constraint=False,
                create_type=False,
            ),
            nullable=False,
            server_default="viewer",
        ),
    )
    scope_group_ids: list[UUID] | None = Field(
        default=None,
        sa_column=Column(UUIDArray(), nullable=True),
    )
    scope_project_ids: list[UUID] | None = Field(
        default=None,
        sa_column=Column(UUIDArray(), nullable=True),
    )
    is_active: bool = Field(default=True)
    must_change_password: bool = Field(default=True)
    external_id: str | None = Field(default=None, max_length=255)
    resource_id: UUID | None = Field(
        default=None,
        foreign_key="personal_resources.id",
        unique=True,
    )
    created_at: datetime = Field(default_factory=_utcnow, index=True)
    updated_at: datetime = Field(default_factory=_utcnow)


class RefreshToken(SQLModel, table=True):
    """Hashed refresh token stored in the database for validation and revocation."""

    __tablename__ = "refresh_tokens"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", nullable=False, index=True)
    token_hash: str = Field(max_length=255, nullable=False, index=True)
    expires_at: datetime = Field(nullable=False)
    revoked_at: datetime | None = Field(default=None)
    # Set to the successor token's id when this token is rotated (not when it
    # is revoked via logout). Distinguishes a benign concurrent-refresh replay
    # from a logged-out/stolen token during reuse detection.
    replaced_by_id: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
