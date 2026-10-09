"""SQLAlchemy model for resource absences: any period of reduced or zero availability.

Absences reduce the available capacity of a resource. The conflict service
treats them like assignments when calculating total allocation for a day:
if assignments + absences exceed 100%, a conflict is raised.
"""

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.models.resource import ResourceType
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AbsenceReason(StrEnum):
    """Whether an absence was foreseeable, which is the only thing planning needs.

    The reason used to name the cause — ``vacation``, ``sick``, ``maintenance``,
    ``training``, ``other``. ``sick`` made this column a health datum, an Art. 9
    GDPR special category, and the capacity calculation never used it: only the date
    range and ``allocation_percent`` enter the arithmetic. Storing a special category
    because it is *informative* is not sufficient grounds.

    What planning actually needs is whether the absence could be planned around.
    That distinction survives; the cause does not.

    A subtlety that makes or breaks this: ``unplanned`` must NOT be a synonym for
    the old ``sick``. If nothing else mapped into it, renaming the value would keep
    the health datum under a new label. ``other`` therefore maps to ``unplanned``
    too, so the bucket genuinely mixes causes — sickness, family emergency,
    compassionate leave, no-show. For rows written before migration 013 the mixing
    is only as good as the historic use of ``other``, which is a reduction of
    inferability rather than its removal.

    ``part_time`` was removed earlier, with ADR-004: a part-time employee is not
    absent, and an absence has a date range rather than a weekday shape, so it could
    never express "Mon–Thu full, Fri off". Part-time lives in ``WorkWeekProfile``.
    """

    planned = "planned"
    unplanned = "unplanned"


class AbsenceStatus(StrEnum):
    """Whether the absence is settled or still a request.

    BOTH statuses reduce capacity identically, which is the opposite of the intuitive
    reading. Treating a requested holiday as free capacity means planning work against days
    that are likely to disappear, and the plan then breaks at approval — the one moment
    nobody is looking at it. What the distinction buys is knowing which capacity gaps can
    still be renegotiated, not a different calculation.

    No ``rejected``: a rejected request is not an absence, and keeping it here would mean
    every reader of this table has to remember to exclude it. Deleting the row is the
    honest representation, and the audit log records that it existed.
    """

    provisional = "provisional"
    confirmed = "confirmed"


class Absence(ORMModel, kw_only=True, eq=False):
    """A period of reduced or zero availability for a resource.

    Any non-project blocking of capacity over a DATE RANGE. Two things it is deliberately not:

    - It does not record a cause. ``reason`` says only whether the absence was foreseeable
      (``planned`` / ``unplanned``); see ``AbsenceReason``.
    - It is not how part-time is modelled. A recurring weekday pattern cannot be expressed as a
      date range, so part-time lives in ``WorkWeekProfile`` (ADR-004). Modelling it here as well
      would offer two contradictory ways to state the same fact.
    """

    __tablename__ = "absences"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    resource_id: Mapped[UUID] = mapped_column(sa.Uuid(), nullable=False, index=True)
    resource_type: Mapped[ResourceType] = mapped_column(
        sa.Enum(
            ResourceType,
            name="resourcetype",
            native_enum=True,
            length=14,
            create_constraint=False,
        ),
        nullable=False,
    )
    reason: Mapped[AbsenceReason] = mapped_column(
        sa.Enum(
            AbsenceReason,
            name="absencereason",
            native_enum=True,
            length=9,
            create_constraint=False,
        ),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(sa.Date(), nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(sa.Date(), nullable=False, index=True)
    allocation_percent: Mapped[float] = mapped_column(
        sa.Float(), nullable=False, default=100.0
    )
    # Defaults to confirmed, matching migration 023: an absence somebody typed in is a fact
    # unless they said otherwise, and defaulting to provisional would reclassify existing
    # recorded leave as uncertain.
    status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        default=AbsenceStatus.confirmed,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(
        sa.String(500), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
