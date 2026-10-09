"""SQLAlchemy entities for authentication: User and RefreshToken."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.utils.pg_types import UUIDArray
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class UserRole(StrEnum):
    """User role determining write-access level."""

    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class User(ORMModel, kw_only=True, eq=False):
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
    __table_args__ = (sa.Index("uq_users_resource_id", "resource_id", unique=True),)

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[str] = mapped_column(
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
        default=UserRole.viewer,
    )
    scope_group_ids: Mapped[list[UUID] | None] = mapped_column(
        UUIDArray(), nullable=True, default=None
    )
    scope_project_ids: Mapped[list[UUID] | None] = mapped_column(
        UUIDArray(), nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, default=True
    )
    external_id: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, default=None
    )
    resource_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "personal_resources.id",
            name="fk_users_resource_id_personal_resources",
            ondelete="SET NULL",
        ),
        nullable=True,
        unique=False,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        index=True,
        default_factory=_utcnow,
        insert_default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )


class RefreshToken(ORMModel, kw_only=True, eq=False):
    """Hashed refresh token stored in the database for validation and revocation."""

    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "users.id", name="refresh_tokens_user_id_fkey", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, default=None
    )
    # Set to the successor token's id when this token is rotated (not when it
    # is revoked via logout). Distinguishes a benign concurrent-refresh replay
    # from a logged-out/stolen token during reuse detection.
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
