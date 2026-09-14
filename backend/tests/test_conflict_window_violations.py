"""Tests for infrastructure bookings outside availability windows (ADR-005).

The default matters as much as the detection: a resource with no windows defined
is unrestricted, so introducing the table must not invalidate a single plan made
before it existed. That is asserted first.

No database: ``ConflictService._detect_window_violations`` touches no session,
and the working-time data is supplied through
:meth:`WorkingTimeService.from_data`. All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID, uuid4

from app.models.assignment import Assignment
from app.models.calendar import InfrastructureAvailabilityWindow
from app.models.conflict import ConflictCause
from app.models.resource import ResourceType
from app.services.conflict_service import ConflictService
from app.services.working_time_service import WorkingTimeService

# 2026-06-01 is a Monday, 2026-06-06 a Saturday.
MONDAY = date(2026, 6, 1)
TUESDAY = date(2026, 6, 2)
SATURDAY = date(2026, 6, 6)

RESOURCE_ID = UUID("33333333-3333-3333-3333-333333333333")
SITE_ID = UUID("44444444-4444-4444-4444-444444444444")


def _service() -> ConflictService:
    """Conflict service whose window check never touches the session."""
    return ConflictService(session=None)  # type: ignore[arg-type]


def _window(
    weekday: int, start: tuple[int, int], end: tuple[int, int]
) -> InfrastructureAvailabilityWindow:
    """Fictional availability window on one weekday."""
    return InfrastructureAvailabilityWindow(
        id=uuid4(),
        resource_id=RESOURCE_ID,
        weekday=weekday,
        start_time=time(*start),
        end_time=time(*end),
    )


def _booking(
    start: datetime, end: datetime, assignment_id: UUID | None = None
) -> Assignment:
    """Fictional infrastructure booking with minute precision."""
    return Assignment(
        id=assignment_id or uuid4(),
        resource_id=RESOURCE_ID,
        resource_type=ResourceType.infrastructure,
        work_package_id=uuid4(),
        start_at=start,
        end_at=end,
    )


def _working_time(
    windows: list[InfrastructureAvailabilityWindow] | None = None,
    holidays: dict[tuple[UUID, date], int] | None = None,
) -> WorkingTimeService:
    """Working-time service for one fictional infrastructure resource."""
    return WorkingTimeService.from_data(
        sites={RESOURCE_ID: SITE_ID},
        holidays=holidays or {},
        windows={RESOURCE_ID: windows} if windows else {},
    )


class TestUnrestrictedByDefault:
    """A resource without windows must behave exactly as it did before."""

    def test_no_windows_means_no_violations(self):
        """Sunday night booking on an unrestricted resource is fine."""
        booking = _booking(datetime(2026, 6, 7, 3, 0), datetime(2026, 6, 7, 5, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time()
        )
        assert periods == []


class TestWithinWindows:
    """Bookings that fit raise nothing."""

    def test_booking_inside_the_window(self):
        """08:00–12:00 inside a 06:00–14:00 shift is clean."""
        booking = _booking(datetime(2026, 6, 1, 8, 0), datetime(2026, 6, 1, 12, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time([_window(0, (6, 0), (14, 0))])
        )
        assert periods == []

    def test_booking_exactly_filling_the_window(self):
        """Window boundaries are inclusive of the booked span."""
        booking = _booking(datetime(2026, 6, 1, 6, 0), datetime(2026, 6, 1, 14, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time([_window(0, (6, 0), (14, 0))])
        )
        assert periods == []

    def test_booking_spanning_two_adjacent_shifts(self):
        """Two shifts that touch cover a booking across both."""
        windows = [_window(0, (6, 0), (14, 0)), _window(0, (14, 0), (22, 0))]
        booking = _booking(datetime(2026, 6, 1, 10, 0), datetime(2026, 6, 1, 18, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time(windows)
        )
        assert periods == []


class TestOutsideWindows:
    """Bookings outside operating hours are their own conflict cause."""

    def test_booking_entirely_outside(self):
        """A night booking against a day shift is flagged."""
        booking = _booking(datetime(2026, 6, 1, 2, 0), datetime(2026, 6, 1, 4, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time([_window(0, (6, 0), (14, 0))])
        )
        assert len(periods) == 1
        assert periods[0].cause == ConflictCause.outside_availability
        assert periods[0].start_date == MONDAY
        assert periods[0].end_date == MONDAY

    def test_booking_starting_before_the_window(self):
        """Partial coverage is still a violation."""
        booking = _booking(datetime(2026, 6, 1, 5, 0), datetime(2026, 6, 1, 10, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time([_window(0, (6, 0), (14, 0))])
        )
        assert len(periods) == 1

    def test_booking_running_past_the_window(self):
        """Overrunning the end of the shift is a violation."""
        booking = _booking(datetime(2026, 6, 1, 12, 0), datetime(2026, 6, 1, 16, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time([_window(0, (6, 0), (14, 0))])
        )
        assert len(periods) == 1

    def test_booking_in_the_gap_between_two_shifts(self):
        """A break between shifts is not bookable."""
        windows = [_window(0, (6, 0), (10, 0)), _window(0, (12, 0), (18, 0))]
        booking = _booking(datetime(2026, 6, 1, 10, 30), datetime(2026, 6, 1, 11, 30))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time(windows)
        )
        assert len(periods) == 1

    def test_weekday_without_windows_is_closed(self):
        """Windows are per weekday: a Monday shift does not open Saturday."""
        booking = _booking(datetime(2026, 6, 6, 8, 0), datetime(2026, 6, 6, 12, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time([_window(0, (6, 0), (14, 0))])
        )
        assert len(periods) == 1
        assert periods[0].start_date == SATURDAY

    def test_holiday_closes_the_resource(self):
        """A plant holiday suppresses windows, so any booking is flagged."""
        booking = _booking(datetime(2026, 6, 1, 8, 0), datetime(2026, 6, 1, 12, 0))
        periods = _service()._detect_window_violations(
            [booking],
            RESOURCE_ID,
            _working_time(
                [_window(0, (6, 0), (14, 0))], holidays={(SITE_ID, MONDAY): 0}
            ),
        )
        assert len(periods) == 1
        assert periods[0].available_percent == 0.0


class TestMultiDayBookings:
    """A period covers the offending days, not the whole booking."""

    def test_offending_days_bound_the_period(self):
        """The period spans the offending days of that booking."""
        windows = [_window(0, (6, 0), (22, 0))]  # Monday only
        booking = _booking(datetime(2026, 6, 1, 8, 0), datetime(2026, 6, 2, 12, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time(windows)
        )
        assert len(periods) == 1
        # Monday offends too: the booking occupies it until midnight, and the
        # window closes at 22:00. Tuesday has no window at all.
        assert periods[0].start_date == MONDAY
        assert periods[0].end_date == TUESDAY

    def test_first_day_is_flagged_when_the_window_stops_before_midnight(self):
        """A booking running to midnight needs coverage up to midnight.

        With a window ending at 23:59 the last minute of the day is uncovered, so
        the day is flagged. A wrapping window is the correct way to express
        continuous operation across the date boundary.
        """
        windows = [_window(0, (6, 0), (23, 59))]
        booking = _booking(datetime(2026, 6, 1, 8, 0), datetime(2026, 6, 2, 12, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time(windows)
        )
        assert len(periods) == 1
        assert periods[0].start_date == MONDAY

    def test_night_shift_across_midnight_is_covered(self):
        """22:00-06:00 is one wrapping row, and a booking inside it is clean.

        ``end_time`` before ``start_time`` means the window continues into the
        following day. This is what makes a three-shift operation expressible.
        """
        windows = [_window(0, (22, 0), (6, 0))]
        booking = _booking(datetime(2026, 6, 1, 22, 0), datetime(2026, 6, 2, 6, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time(windows)
        )
        assert periods == []

    def test_night_shift_does_not_cover_the_next_evening(self):
        """The wrap adds a tail on the following day, not a second full shift."""
        windows = [_window(0, (22, 0), (6, 0))]  # starts Monday only
        booking = _booking(datetime(2026, 6, 2, 22, 0), datetime(2026, 6, 3, 2, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time(windows)
        )
        assert len(periods) == 1

    def test_booking_beyond_the_wrapped_tail_is_flagged(self):
        """Running past 06:00 leaves the window even though it wrapped."""
        windows = [_window(0, (22, 0), (6, 0))]
        booking = _booking(datetime(2026, 6, 1, 22, 0), datetime(2026, 6, 2, 8, 0))
        periods = _service()._detect_window_violations(
            [booking], RESOURCE_ID, _working_time(windows)
        )
        assert len(periods) == 1
        assert periods[0].end_date == TUESDAY

    def test_holiday_on_the_starting_day_cancels_the_whole_night_shift(self):
        """The tail belongs to the day the shift started, so the holiday kills it.

        A holiday cancels a shift, and the small hours after midnight belong to
        the shift that began the evening before rather than to the new date.
        """
        windows = [_window(0, (22, 0), (6, 0))]
        booking = _booking(datetime(2026, 6, 1, 22, 0), datetime(2026, 6, 2, 6, 0))
        periods = _service()._detect_window_violations(
            [booking],
            RESOURCE_ID,
            _working_time(windows, holidays={(SITE_ID, MONDAY): 0}),
        )
        assert len(periods) == 1

    def test_each_assignment_gets_its_own_period(self):
        """Two offending bookings are two conflicts, not one merged span."""
        windows = [_window(0, (6, 0), (14, 0))]
        bookings = [
            _booking(datetime(2026, 6, 1, 2, 0), datetime(2026, 6, 1, 3, 0)),
            _booking(datetime(2026, 6, 1, 20, 0), datetime(2026, 6, 1, 21, 0)),
        ]
        periods = _service()._detect_window_violations(
            bookings, RESOURCE_ID, _working_time(windows)
        )
        assert len(periods) == 2
        assert {len(p.assignment_ids) for p in periods} == {1}

    def test_booking_without_timestamps_is_skipped(self):
        """A personal-shaped row in the list must not crash the check."""
        assignment = Assignment(
            id=uuid4(),
            resource_id=RESOURCE_ID,
            resource_type=ResourceType.personal,
            work_package_id=uuid4(),
            start_date=MONDAY,
            end_date=MONDAY,
            allocation_percent=50.0,
        )
        periods = _service()._detect_window_violations(
            [assignment],
            RESOURCE_ID,
            _working_time([_window(0, (6, 0), (14, 0))]),
        )
        assert periods == []
