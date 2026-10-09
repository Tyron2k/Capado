"""Conversions between stored UTC instants and local planning clock readings."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TIME_ZONE = "Europe/Berlin"


def planning_zone(name: str = DEFAULT_TIME_ZONE) -> ZoneInfo:
    """Return the configured IANA zone for local planning rules."""
    return ZoneInfo(name)


def local_time(instant: datetime, zone: ZoneInfo) -> datetime:
    """View a UTC instant on the local planning clock."""
    if instant.utcoffset() is None:
        raise ValueError("An assignment timestamp must include a UTC offset")
    return instant.astimezone(zone)


def local_date(instant: datetime, zone: ZoneInfo) -> date:
    """Return the calendar date of an instant in the planning zone."""
    return local_time(instant, zone).date()


def planning_today(
    *, now: datetime | None = None, zone: ZoneInfo | None = None
) -> date:
    """Current calendar day in the planning zone, independent of the host TZ.

    ``now`` accepts an aware instant for reproducible historical calculations.
    Storage, audit and authentication timestamps continue to use UTC instants.
    """
    return local_date(
        now if now is not None else datetime.now(UTC), zone or planning_zone()
    )


def local_wall_time_to_utc(value: datetime, zone: ZoneInfo) -> datetime:
    """Interpret a wall-clock reading, rejecting DST gaps and repeated times."""
    if value.utcoffset() is not None:
        return value.astimezone(UTC)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        instant = value.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == value:
            candidates.add(instant)
    if len(candidates) != 1:
        raise ValueError("Local time is ambiguous or nonexistent due to DST")
    return candidates.pop()


def local_day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Return UTC boundaries of a local calendar day (which may be 23 or 25 hours)."""
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(
        UTC
    )
    return start, end
