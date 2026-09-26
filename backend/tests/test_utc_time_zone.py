"""UTC storage, local-day boundaries, and the migration's timestamp coverage."""

import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlmodel import SQLModel
from sqlmodel.sql.sqltypes import UTCDateTime

import app.models  # noqa: F401
from app.models.assignment import Assignment
from app.schemas.assignment import AssignmentCreate
from app.schemas.settings import OrganizationSettingsUpdate
from app.services.conflict_suggestion_service import _shift_booking
from app.services.settings_service import (
    get_organization_settings,
    update_organization_settings,
)
from app.services.time_zone import (
    local_date,
    local_day_bounds,
    local_wall_time_to_utc,
)


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        ("2026-03-28T07:00:00+00:00", "2026-03-29T06:00:00+00:00"),
        ("2026-10-24T06:00:00+00:00", "2026-10-25T07:00:00+00:00"),
    ],
)
def test_booking_shift_uses_planning_calendar(start: str, expected: str) -> None:
    booking = Assignment(
        start_at=datetime.fromisoformat(start),
        end_at=datetime.fromisoformat(start) + timedelta(hours=2),
    )
    target = _shift_booking(booking, 1)
    assert target == (
        datetime.fromisoformat(expected),
        datetime.fromisoformat(expected) + timedelta(hours=2),
    )


@pytest.mark.parametrize(
    "start", ["2026-03-28T01:30:00+00:00", "2026-10-24T00:30:00+00:00"]
)
def test_booking_shift_never_guesses_a_target_offset(start: str) -> None:
    booking = Assignment(
        start_at=datetime.fromisoformat(start),
        end_at=datetime.fromisoformat(start) + timedelta(hours=2),
    )
    assert _shift_booking(booking, 1) is None


def test_local_day_can_differ_from_utc_day() -> None:
    """Bookings near midnight use the planning calendar, not their UTC date."""
    berlin = ZoneInfo("Europe/Berlin")
    assert local_date(datetime(2026, 7, 1, 22, 30, tzinfo=UTC), berlin) == date(
        2026, 7, 2
    )


@pytest.mark.parametrize(
    ("day", "hours"),
    [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)],
)
def test_local_day_bounds_follow_dst(day: date, hours: int) -> None:
    """UTC day boundaries respect the 23- and 25-hour Berlin days."""
    start, end = local_day_bounds(day, ZoneInfo("Europe/Berlin"))
    assert end - start == timedelta(hours=hours)


@pytest.mark.parametrize("hour", [2, 3])
def test_local_wall_time_rejects_dst_gap_or_fold(hour: int) -> None:
    """No arbitrary UTC instant is chosen for an invalid local clock reading."""
    day = 29 if hour == 2 else 25
    month = 3 if hour == 2 else 10
    local = datetime(2026, month, day, 2, 30)
    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        local_wall_time_to_utc(local, ZoneInfo("Europe/Berlin"))


def test_assignment_api_rejects_naive_timestamp() -> None:
    """A client must supply an offset before a booking can reach storage."""
    from uuid import uuid4

    with pytest.raises(ValidationError):
        AssignmentCreate(
            resource_id=uuid4(),
            resource_type="infrastructure",
            work_package_id=uuid4(),
            start_at=datetime(2026, 7, 1, 8),
            end_at=datetime(2026, 7, 1, 10),
        )


def test_settings_accept_only_iana_zones() -> None:
    """An invalid name cannot make every booking view fail at render time."""
    assert OrganizationSettingsUpdate(time_zone="America/New_York").time_zone == (
        "America/New_York"
    )
    with pytest.raises(ValidationError):
        OrganizationSettingsUpdate(time_zone="not/a-zone")


async def test_time_zone_setting_round_trips(db_session) -> None:
    """The shared zone survives a new session read and defaults to Berlin."""
    initial = await get_organization_settings(db_session)
    assert initial.time_zone == "Europe/Berlin"
    await update_organization_settings(db_session, time_zone="America/New_York")
    db_session.expire_all()
    updated = await get_organization_settings(db_session)
    assert updated.time_zone == "America/New_York"


def test_migration_covers_every_utc_datetime_column() -> None:
    """The migration list cannot silently omit a new timestamp column."""
    migration_path = (
        Path(__file__).parent.parent
        / "alembic/versions/002_utc_timestamps_and_time_zone.py"
    )
    spec = importlib.util.spec_from_file_location("utc_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    model_columns = {
        (table.name, column.name)
        for table in SQLModel.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, UTCDateTime)
    }
    migrated_columns = {
        (table, column)
        for table, columns in migration.UTC_COLUMNS.items()
        for column in columns
    } | {("assignments", "start_at"), ("assignments", "end_at")}
    assert migrated_columns == model_columns
