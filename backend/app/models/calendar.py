"""SQLModel models for working-time capacity: calendars, week profiles, windows.

Supply side of the capacity model (ADR-004, ADR-005). Demand lives on
``Assignment.allocation_percent``, which is a share of a normative working day
rather than of a resource's individual capacity.

All durations are integer minutes. Conflict detection sums allocations across
long date ranges, and a capacity check is an equality-adjacent comparison —
binary floating point would drift into phantom or missed conflicts.
"""

from datetime import UTC, date, datetime, time
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel, UniqueConstraint

MINUTES_PER_DAY = 1440


def _utcnow() -> datetime:
    """UTC timestamp as naive datetime (for TIMESTAMP WITHOUT TIME ZONE)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Holiday(SQLModel, table=True):
    """A calendar exception for one site on one date.

    Despite the name this covers every deviation from the week profile, which
    is why it carries ``working_minutes`` instead of being a pure flag:

    - ``working_minutes = 0`` — public holiday, company shutdown, bridge day.
    - ``0 < working_minutes < profile`` — half day (24 and 31 December in most
      German firms).
    - ``working_minutes > 0`` on a day the profile calls free — a designated
      working Saturday, which real plant calendars do contain.

    A row overrides the week profile for that date. Scoped per site because
    public holidays differ by location, and a bridge day is a local decision.
    """

    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("site_id", "day", name="uq_holidays_site_day"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    site_id: UUID = Field(foreign_key="sites.id", index=True)
    day: date = Field(index=True)
    name: str = Field(max_length=255)
    working_minutes: int = Field(default=0, ge=0, le=MINUTES_PER_DAY)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkWeekProfile(SQLModel, table=True):
    """A reusable weekly availability pattern, in minutes per weekday.

    Named and shared rather than per-resource, because a plant has a handful
    of patterns ("Standard 5-day 8 h", "Part-time 30 h Mon–Thu") and hundreds
    of resources. This is where part-time and shift patterns live — not in
    ``Absence``, which cannot express a weekday shape (ADR-004).

    Exactly one profile should carry ``is_default``; resources without an
    explicit assignment fall back to it, so a fresh install has capacity
    instead of reporting zero everywhere.
    """

    __tablename__ = "work_week_profiles"
    __table_args__ = (UniqueConstraint("name", name="uq_work_week_profiles_name"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    monday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    tuesday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    wednesday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    thursday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    friday_minutes: int = Field(default=480, ge=0, le=MINUTES_PER_DAY)
    saturday_minutes: int = Field(default=0, ge=0, le=MINUTES_PER_DAY)
    sunday_minutes: int = Field(default=0, ge=0, le=MINUTES_PER_DAY)
    is_default: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def minutes_for_weekday(self, weekday: int) -> int:
        """Available minutes for a weekday, Monday = 0 through Sunday = 6."""
        return (
            self.monday_minutes,
            self.tuesday_minutes,
            self.wednesday_minutes,
            self.thursday_minutes,
            self.friday_minutes,
            self.saturday_minutes,
            self.sunday_minutes,
        )[weekday]


class ResourceWorkProfile(SQLModel, table=True):
    """Binds a week profile to a resource or to a resource group, for a period.

    Exactly one of ``resource_id`` and ``group_id`` is set. A group binding is
    what makes this usable at all: a plant with 1600 people has a handful of
    working-time patterns, and requiring one row per person would mean nobody
    maintains them. A department gets its hours once; the part-time employee gets
    an individual row as the exception.

    Resolution order, most specific first: an individual binding, then the
    resource's own group, then that group's parent, then the default profile.

    Dated rather than a plain foreign key, so a contract change is a new row and
    the capacity of a past period stays reproducible. ``valid_until = None``
    means open-ended.
    """

    __tablename__ = "resource_work_profiles"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    resource_id: UUID | None = Field(default=None, index=True)
    group_id: UUID | None = Field(
        default=None, foreign_key="resource_groups.id", index=True
    )
    profile_id: UUID = Field(foreign_key="work_week_profiles.id", index=True)
    valid_from: date = Field(index=True)
    valid_until: date | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def covers(self, day: date) -> bool:
        """Whether this binding is in force on a date."""
        return self.valid_from <= day and (
            self.valid_until is None or day <= self.valid_until
        )


class InfrastructureAvailabilityWindow(SQLModel, table=True):
    """A clock window on one weekday during which a resource may be booked.

    Several rows per weekday express a multi-shift operation (06:00–14:00 and
    14:00–22:00 as two rows rather than one artificial span).

    ``weekday`` is the day the window **starts** on. A row whose ``end_time`` is
    before its ``start_time`` runs past midnight, so a night shift is one row —
    weekday 0 with 22:00 and 06:00 — rather than two that a reader has to join.
    Equal times are rejected as ambiguous.

    Because a wrapping row cannot be interpreted from itself alone, callers ask
    ``WorkingTimeService.covered_spans`` rather than reading rows directly.

    A resource with no windows at all is available around the clock, which
    keeps the pre-ADR-005 behaviour as the default: adding this table changes
    no existing plan until an operator opts in.
    """

    __tablename__ = "infrastructure_availability_windows"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    resource_id: UUID = Field(foreign_key="infrastructure_resources.id", index=True)
    weekday: int = Field(ge=0, le=6, index=True)
    start_time: time = Field(sa_column=Column(sa.Time, nullable=False))
    end_time: time = Field(sa_column=Column(sa.Time, nullable=False))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
