"""The customer a folder's work belongs to.

An entity rather than the free-text column it replaces, because free text made "Acme" and "Acme GmbH"
two customers and nothing could say they were one. Introduced at the moment it was cheapest: the
free-text column never reached a deployed database, so there was nothing to reconcile by hand.

The link is on the FOLDER, inherited by the projects inside it, and overridable per project. See
migration 025 for why it is not the folder tree itself.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """UTC timestamp as naive datetime (for TIMESTAMP WITHOUT TIME ZONE)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Customer(SQLModel, table=True):
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

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255, nullable=False)
    reference: str = Field(default="", max_length=128, nullable=False)
    note: str = Field(default="", max_length=1000, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
