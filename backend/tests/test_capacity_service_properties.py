"""Property-based and example tests for capacity arithmetic.

Targets the pure, database-free cores of :mod:`app.services.capacity_service`:

- :func:`get_utilization_color` threshold classification.
- :meth:`CapacityService._assigned_percent_for_day` (FTE-based summation for
  personal resources; exclusive 100%-per-booking for infrastructure).
- :meth:`CapacityService._absence_percent_for_day`.

All test data is inline and clearly fictional (fake resources built with
``SimpleNamespace``); no real customer data and no database is used.
"""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.resource import ResourceType
from app.services.capacity_service import (
    BASE_CAPACITY_PERCENT,
    CapacityService,
    get_utilization_color,
)

_DAY = date(2026, 6, 15)


def _service() -> CapacityService:
    """Build a CapacityService whose pure methods never touch the session."""
    return CapacityService(session=None)  # type: ignore[arg-type]


def _personal(start: date, end: date, percent: float) -> SimpleNamespace:
    """Fake personal assignment covering [start, end] at ``percent``."""
    return SimpleNamespace(
        start_date=start,
        end_date=end,
        allocation_percent=percent,
        start_at=None,
        end_at=None,
    )


def _infra(start_at: datetime, end_at: datetime) -> SimpleNamespace:
    """Fake infrastructure assignment occupying [start_at, end_at]."""
    return SimpleNamespace(
        start_date=None,
        end_date=None,
        allocation_percent=None,
        start_at=start_at,
        end_at=end_at,
    )


# ---------------------------------------------------------------------------
# get_utilization_color
# ---------------------------------------------------------------------------


class TestUtilizationColor:
    """Threshold classification for utilization colors."""

    def test_boundaries(self):
        """Boundary values map to the documented colors."""
        assert get_utilization_color(0) == "green"
        assert get_utilization_color(79.9) == "green"
        assert get_utilization_color(80) == "yellow"
        assert get_utilization_color(100) == "yellow"
        assert get_utilization_color(100.01) == "red"

    @given(u=st.floats(min_value=0, max_value=79.999, allow_nan=False))
    @settings(max_examples=50)
    def test_below_80_is_green(self, u: float):
        """Any utilization strictly below 80% is green."""
        assert get_utilization_color(u) == "green"

    @given(u=st.floats(min_value=80, max_value=100, allow_nan=False))
    @settings(max_examples=50)
    def test_80_to_100_is_yellow(self, u: float):
        """Utilization in [80, 100] is yellow."""
        assert get_utilization_color(u) == "yellow"

    @given(u=st.floats(min_value=100.0001, max_value=1000, allow_nan=False))
    @settings(max_examples=50)
    def test_above_100_is_red(self, u: float):
        """Any utilization above 100% is red."""
        assert get_utilization_color(u) == "red"


# ---------------------------------------------------------------------------
# _assigned_percent_for_day — personal (FTE summation)
# ---------------------------------------------------------------------------


class TestPersonalAllocation:
    """FTE-based allocation summation for personal resources."""

    def test_four_quarter_assignments_equal_full(self):
        """Four 25% assignments on the same day sum to 100% (FTE arithmetic)."""
        svc = _service()
        assignments = [_personal(_DAY, _DAY, 25.0) for _ in range(4)]
        total = svc._assigned_percent_for_day(assignments, ResourceType.personal, _DAY)
        assert total == 100.0

    def test_assignment_outside_day_contributes_zero(self):
        """An assignment whose range excludes the day contributes nothing."""
        svc = _service()
        other = _personal(_DAY + timedelta(days=5), _DAY + timedelta(days=9), 50.0)
        total = svc._assigned_percent_for_day([other], ResourceType.personal, _DAY)
        assert total == 0.0

    @given(
        count=st.integers(min_value=0, max_value=10),
        percent=st.floats(min_value=1, max_value=100, allow_nan=False),
    )
    @settings(max_examples=60)
    def test_sum_is_count_times_percent(self, count: int, percent: float):
        """N overlapping personal assignments at p% sum to N*p%."""
        svc = _service()
        assignments = [_personal(_DAY, _DAY, percent) for _ in range(count)]
        total = svc._assigned_percent_for_day(assignments, ResourceType.personal, _DAY)
        assert total == pytest.approx(count * percent)

    @given(
        offset=st.integers(min_value=1, max_value=30),
        percent=st.floats(min_value=1, max_value=100, allow_nan=False),
    )
    @settings(max_examples=40)
    def test_only_covering_days_count(self, offset: int, percent: float):
        """Only assignments whose range includes the queried day are summed."""
        svc = _service()
        covering = _personal(_DAY - timedelta(days=offset), _DAY, percent)
        not_covering = _personal(
            _DAY + timedelta(days=1), _DAY + timedelta(days=offset), percent
        )
        total = svc._assigned_percent_for_day(
            [covering, not_covering], ResourceType.personal, _DAY
        )
        assert total == percent


# ---------------------------------------------------------------------------
# _assigned_percent_for_day — infrastructure (exclusive 100% per booking)
# ---------------------------------------------------------------------------


class TestInfrastructureAllocation:
    """Exclusive booking model for infrastructure resources."""

    def test_single_booking_is_100(self):
        """A single overlapping infrastructure booking counts as 100%."""
        svc = _service()
        booking = _infra(
            datetime.combine(_DAY, time(8, 0)),
            datetime.combine(_DAY, time(9, 0)),
        )
        total = svc._assigned_percent_for_day(
            [booking], ResourceType.infrastructure, _DAY
        )
        assert total == 100.0

    def test_duration_does_not_change_percent(self):
        """A one-minute and an all-day booking both count as exactly 100%."""
        svc = _service()
        short = _infra(
            datetime.combine(_DAY, time(8, 0)),
            datetime.combine(_DAY, time(8, 1)),
        )
        long = _infra(
            datetime.combine(_DAY, time(0, 0)),
            datetime.combine(_DAY + timedelta(days=1), time(0, 0)),
        )
        assert (
            svc._assigned_percent_for_day([short], ResourceType.infrastructure, _DAY)
            == svc._assigned_percent_for_day([long], ResourceType.infrastructure, _DAY)
            == 100.0
        )

    @given(count=st.integers(min_value=1, max_value=8))
    @settings(max_examples=40)
    def test_n_overlapping_bookings_sum_to_n_hundred(self, count: int):
        """N overlapping infrastructure bookings on a day sum to N*100%."""
        svc = _service()
        bookings = [
            _infra(
                datetime.combine(_DAY, time(8, 0)),
                datetime.combine(_DAY, time(17, 0)),
            )
            for _ in range(count)
        ]
        total = svc._assigned_percent_for_day(
            bookings, ResourceType.infrastructure, _DAY
        )
        assert total == count * 100.0

    def test_booking_ending_at_midnight_excludes_next_day(self):
        """A booking ending exactly at midnight does not occupy the next day."""
        svc = _service()
        booking = _infra(
            datetime.combine(_DAY, time(0, 0)),
            datetime.combine(_DAY + timedelta(days=1), time(0, 0)),
        )
        next_day = svc._assigned_percent_for_day(
            [booking], ResourceType.infrastructure, _DAY + timedelta(days=1)
        )
        assert next_day == 0.0


# ---------------------------------------------------------------------------
# _absence_percent_for_day
# ---------------------------------------------------------------------------


class TestAbsenceAllocation:
    """Absence percentages add to the daily load."""

    @given(
        percent=st.floats(min_value=1, max_value=100, allow_nan=False),
        span=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=40)
    def test_absence_covering_day_counts(self, percent: float, span: int):
        """An absence spanning the day contributes its percentage."""
        svc = _service()
        absence = SimpleNamespace(
            start_date=_DAY - timedelta(days=span),
            end_date=_DAY + timedelta(days=span),
            allocation_percent=percent,
        )
        assert svc._absence_percent_for_day([absence], _DAY) == percent

    def test_absence_outside_day_is_zero(self):
        """An absence that does not cover the day contributes nothing."""
        svc = _service()
        absence = SimpleNamespace(
            start_date=_DAY + timedelta(days=1),
            end_date=_DAY + timedelta(days=3),
            allocation_percent=100.0,
        )
        assert svc._absence_percent_for_day([absence], _DAY) == 0.0


def test_base_capacity_is_100():
    """The base daily capacity is a flat 100%."""
    assert BASE_CAPACITY_PERCENT == 100.0
