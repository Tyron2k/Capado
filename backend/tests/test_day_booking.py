"""Tests for :meth:`WorkingTimeService.day_booking_bounds`.

This is the usability path: a planner picks a day and the system maps it onto the
resource's operating hours, instead of a time range being typed for every
booking. The window configuration is stated once per resource.

No database. All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid4

from app.models.calendar import InfrastructureAvailabilityWindow
from app.services.time_zone import local_wall_time_to_utc, planning_zone
from app.services.working_time_service import WorkingTimeService

MONDAY = date(2026, 6, 1)
SATURDAY = date(2026, 6, 6)

RESOURCE = UUID("55555555-5555-5555-5555-555555555555")
SITE = UUID("66666666-6666-6666-6666-666666666666")


def _local(value: datetime) -> datetime:
    return local_wall_time_to_utc(value, planning_zone())


def _window(
    weekday: int, start: tuple[int, int], end: tuple[int, int]
) -> InfrastructureAvailabilityWindow:
    """Fictional availability window."""
    return InfrastructureAvailabilityWindow(
        id=uuid4(),
        resource_id=RESOURCE,
        weekday=weekday,
        start_time=time(*start),
        end_time=time(*end),
    )


def _service(
    windows: list[InfrastructureAvailabilityWindow] | None = None,
    holidays: dict[tuple[UUID, date], int] | None = None,
) -> WorkingTimeService:
    """Service for one fictional infrastructure resource."""
    return WorkingTimeService.from_data(
        sites={RESOURCE: SITE},
        holidays=holidays or {},
        windows={RESOURCE: windows} if windows else {},
    )


class TestDayBookingBounds:
    """A day maps onto the resource's operating envelope."""

    def test_unrestricted_resource_spans_the_whole_day(self):
        """No windows means around the clock, so a day is midnight to midnight."""
        bounds = _service().day_booking_bounds(RESOURCE, MONDAY)
        assert bounds == (
            _local(datetime(2026, 6, 1)),
            _local(datetime(2026, 6, 2)),
        )

    def test_single_shift_maps_onto_that_shift(self):
        """A 06:00-15:00 department yields exactly those hours."""
        bounds = _service([_window(0, (6, 0), (15, 0))]).day_booking_bounds(
            RESOURCE, MONDAY
        )
        assert bounds == (
            _local(datetime(2026, 6, 1, 6)),
            _local(datetime(2026, 6, 1, 15)),
        )

    def test_two_shifts_span_the_whole_operating_day(self):
        """From the first shift's start to the last shift's end."""
        windows = [_window(0, (6, 0), (14, 0)), _window(0, (14, 0), (22, 0))]
        bounds = _service(windows).day_booking_bounds(RESOURCE, MONDAY)
        assert bounds == (
            _local(datetime(2026, 6, 1, 6)),
            _local(datetime(2026, 6, 1, 22)),
        )

    def test_gap_between_shifts_is_included(self):
        """A resource taken for the day is taken during the shift change too.

        The envelope deliberately covers the break: a track occupied all day is
        not free for someone else between shifts. Windows say when work may be
        scheduled; a day booking says the resource is taken.
        """
        windows = [_window(0, (6, 0), (10, 0)), _window(0, (14, 0), (18, 0))]
        bounds = _service(windows).day_booking_bounds(RESOURCE, MONDAY)
        assert bounds == (
            _local(datetime(2026, 6, 1, 6)),
            _local(datetime(2026, 6, 1, 18)),
        )

    def test_night_shift_reaches_into_the_next_day(self):
        """A wrapping window extends the envelope past midnight."""
        bounds = _service([_window(0, (22, 0), (6, 0))]).day_booking_bounds(
            RESOURCE, MONDAY
        )
        assert bounds == (
            _local(datetime(2026, 6, 1, 22)),
            _local(datetime(2026, 6, 2)),
        )

    def test_closed_weekday_returns_nothing(self):
        """A day with no window cannot be booked, rather than booked emptily."""
        assert (
            _service([_window(0, (6, 0), (15, 0))]).day_booking_bounds(
                RESOURCE, SATURDAY
            )
            is None
        )

    def test_holiday_returns_nothing(self):
        """A plant holiday closes the resource."""
        service = _service([_window(0, (6, 0), (15, 0))], holidays={(SITE, MONDAY): 0})
        assert service.day_booking_bounds(RESOURCE, MONDAY) is None

    def test_bounds_are_usable_as_assignment_timestamps(self):
        """The result is ordered and non-empty, so it can be stored directly."""
        bounds = _service([_window(0, (6, 0), (15, 0))]).day_booking_bounds(
            RESOURCE, MONDAY
        )
        assert bounds is not None
        start, end = bounds
        assert start < end

    def test_unrestricted_dst_days_have_real_elapsed_length(self):
        """A local full day is 23 or 25 elapsed hours at the DST boundaries."""
        spring = _service().day_booking_bounds(RESOURCE, date(2026, 3, 29))
        autumn = _service().day_booking_bounds(RESOURCE, date(2026, 10, 25))
        assert spring is not None and spring[1] - spring[0] == timedelta(hours=23)
        assert autumn is not None and autumn[1] - autumn[0] == timedelta(hours=25)
