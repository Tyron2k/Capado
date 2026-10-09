"""The customer a folder's work belongs to.

An entity rather than the free-text column it replaces, because free text made "Acme" and "Acme GmbH"
two customers and nothing could say they were one. Introduced at the moment it was cheapest: the
free-text column never reached a deployed database, so there was nothing to reconcile by hand.

The link is on the FOLDER, inherited by the projects inside it, and overridable per project. See
migration 025 for why it is not the folder tree itself.
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


class Customer(ORMModel, kw_only=True, eq=False):
    """A customer, unique by name regardless of case.

    Attributes:
        name: Display name. Case-insensitively unique — a plain unique index would accept
            "Acme" beside "acme" and reintroduce exactly the duplication this replaces.
        reference: The customer number, theirs or ours. Free text on purpose: a customer number
            is whatever the counterparty says it is, and constraining its shape would only make
            correct values unenterable.
        note: Free-text note.
        is_active: Soft retirement. A customer with historical projects should stop appearing in
            pickers without the projects losing who they were for, which deleting would cost.
    """

    __tablename__ = "customers"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    reference: Mapped[str] = mapped_column(sa.String(128), nullable=False, default="")
    note: Mapped[str] = mapped_column(sa.String(1000), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )

    __table_args__ = (
        sa.Index("uq_customers_name_lower", sa.func.lower(name), unique=True),
    )
