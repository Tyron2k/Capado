"""SQLModel model for sites (Betriebsstätten).

A site is the top organizational level inside the one organization this
deployment serves (see ADR-003). It owns the working-time calendar, because
public holidays differ per location and therefore change the capacity
arithmetic rather than just a label.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Site(SQLModel, table=True):
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

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255)
    region_code: str | None = Field(default=None, max_length=16)
    is_default: bool = Field(default=False, index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
