"""SQLAlchemy model for sites (Betriebsstätten).

A site is the top organizational level inside the one organization this
deployment serves (see ADR-003). It owns the working-time calendar, because
public holidays differ per location and therefore change the capacity
arithmetic rather than just a label.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Site(ORMModel, kw_only=True, eq=False):
    """A plant or physical location.

    Attributes:
        name: Display name of the site.
        region_code: Optional region identifier used by the holiday seed
            script to pre-fill public holidays, e.g. ``DE-BY`` for
            Bavaria. Never read at runtime by the capacity path — the
            ``holidays`` table is the source of truth (ADR-004).
        is_default: Marks the site that resources fall back to when none is
            set explicitly. Exactly one site should carry this flag.
        is_active: Soft-delete flag, consistent with resources and users.
    """

    __tablename__ = "sites"
    __table_args__ = (
        sa.Index(
            "uq_sites_default",
            "is_default",
            unique=True,
            postgresql_where=sa.text("is_default"),
            sqlite_where=sa.text("is_default"),
        ),
        sa.CheckConstraint(
            "NOT is_default OR is_active", name="ck_sites_default_active"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    region_code: Mapped[str | None] = mapped_column(
        sa.String(16), nullable=True, default=None
    )
    is_default: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, index=True, default=False
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, index=True, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
