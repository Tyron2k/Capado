"""Property-based and example tests for conflict detection cores.

Targets the pure, database-free logic of :mod:`app.services.conflict_service`:

- :meth:`ConflictService.group_consecutive_conflict_days` — grouping of
  conflicting days into contiguous periods.
- :meth:`ConflictService._emit_infrastructure_period` — sweep-line detection
  of overlapping infrastructure intervals.

The service is instantiated with ``session=None`` because these methods never
touch the database. All data is inline and clearly fictional.
"""

import asyncio
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.resource import ResourceType
from app.services.conflict_service import ConflictDay, ConflictService
from app.services.time_zone import local_wall_time_to_utc, planning_zone

_ORIGIN = date(2026, 1, 1)


def _service() -> ConflictService:
    """Build a ConflictService whose pure methods never touch the session."""
    return ConflictService(session=None)  # type: ignore[arg-type]


def _group(days: list[ConflictDay]):
    """Run the async grouping helper synchronously for tests."""
    return asyncio.run(
        _service().group_consecutive_conflict_days(
            days, resource_id=uuid4(), resource_type=ResourceType.personal
        )
    )


def _unique_cause_day(day: date) -> ConflictDay:
    """A conflict day with a unique triggering assignment id."""
    return ConflictDay(
        date=day,
        available=100.0,
        assigned=150.0,
        assignment_ids=[uuid4()],
    )


# ---------------------------------------------------------------------------
# group_consecutive_conflict_days
# ---------------------------------------------------------------------------


class TestGrouping:
    """Grouping conflict days into periods."""

    def test_empty_yields_no_periods(self):
        """No conflict days produce no periods."""
        assert _group([]) == []

    def test_single_day_period(self):
        """A single conflict day becomes a one-day period."""
        aid = uuid4()
        day = ConflictDay(
            date=_ORIGIN, available=100.0, assigned=120.0, assignment_ids=[aid]
        )
        periods = _group([day])
        assert len(periods) == 1
        assert periods[0].start_date == _ORIGIN
        assert periods[0].end_date == _ORIGIN
        assert periods[0].assignment_ids == [aid]

    def test_consecutive_days_merge(self):
        """Two calendar-consecutive days merge into a single period."""
        days = [
            _unique_cause_day(_ORIGIN),
            _unique_cause_day(_ORIGIN + timedelta(days=1)),
        ]
        periods = _group(days)
        assert len(periods) == 1
        assert periods[0].start_date == _ORIGIN
        assert periods[0].end_date == _ORIGIN + timedelta(days=1)

    def test_gap_with_distinct_cause_splits(self):
        """Non-adjacent days with different causes form separate periods."""
        days = [
            _unique_cause_day(_ORIGIN),
            _unique_cause_day(_ORIGIN + timedelta(days=10)),
        ]
        periods = _group(days)
        assert len(periods) == 2

    def test_same_cause_merges_across_gap(self):
        """Days sharing the same triggering assignments merge despite a gap."""
        shared = [uuid4(), uuid4()]
        days = [
            ConflictDay(
                date=_ORIGIN, available=100.0, assigned=200.0, assignment_ids=shared
            ),
            ConflictDay(
                date=_ORIGIN + timedelta(days=30),
                available=100.0,
                assigned=200.0,
                assignment_ids=shared,
            ),
        ]
        periods = _group(days)
        assert len(periods) == 1
        assert periods[0].start_date == _ORIGIN
        assert periods[0].end_date == _ORIGIN + timedelta(days=30)

    @given(
        offsets=st.lists(
            st.integers(min_value=0, max_value=200),
            min_size=1,
            max_size=25,
            unique=True,
        )
    )
    @settings(max_examples=60)
    def test_periods_cover_every_input_day(self, offsets: list[int]):
        """Every input conflict day falls within exactly one returned period.

        Uses unique per-day causes so merging is driven purely by calendar
        adjacency, making the covering invariant deterministic.
        """
        days = [_unique_cause_day(_ORIGIN + timedelta(days=o)) for o in offsets]
        periods = _group(days)

        # Periods are ordered and span the full extent of the input.
        assert periods[0].start_date == min(d.date for d in days)
        assert periods[-1].end_date == max(d.date for d in days)
        starts = [p.start_date for p in periods]
        assert starts == sorted(starts)

        # Each input day is covered by exactly one period.
        for d in days:
            covering = [p for p in periods if p.start_date <= d.date <= p.end_date]
            assert len(covering) == 1

    @given(
        run_length=st.integers(min_value=1, max_value=15),
    )
    @settings(max_examples=40)
    def test_contiguous_run_is_one_period(self, run_length: int):
        """A run of consecutive days collapses into a single period."""
        days = [
            _unique_cause_day(_ORIGIN + timedelta(days=i)) for i in range(run_length)
        ]
        periods = _group(days)
        assert len(periods) == 1
        assert periods[0].start_date == _ORIGIN
        assert periods[0].end_date == _ORIGIN + timedelta(days=run_length - 1)


# ---------------------------------------------------------------------------
# _emit_infrastructure_period (sweep-line overlap detection)
# ---------------------------------------------------------------------------


def _dt(day_offset: int, hour: int) -> datetime:
    """Build a fake timestamp at a given day offset and hour."""
    return local_wall_time_to_utc(
        datetime.combine(_ORIGIN + timedelta(days=day_offset), time(hour)),
        planning_zone(),
    )


class TestInfrastructureSweep:
    """Sweep-line overlap detection for infrastructure intervals."""

    def test_fewer_than_two_intervals_no_conflict(self):
        """A single interval can never conflict."""
        svc = _service()
        rid = uuid4()
        cluster = [(_dt(0, 8), _dt(0, 10), uuid4())]
        assert svc._emit_infrastructure_period(rid, cluster, set()) == []

    def test_disjoint_intervals_no_conflict(self):
        """Two non-overlapping intervals produce no conflict period."""
        svc = _service()
        rid = uuid4()
        cluster = [
            (_dt(0, 8), _dt(0, 10), uuid4()),
            (_dt(0, 11), _dt(0, 12), uuid4()),
        ]
        assert svc._emit_infrastructure_period(rid, cluster, set()) == []

    def test_overlapping_intervals_conflict(self):
        """Two overlapping intervals produce at least one conflict period."""
        svc = _service()
        rid = uuid4()
        ids = {uuid4(), uuid4()}
        cluster = [
            (_dt(0, 8), _dt(0, 12), next(iter(ids))),
            (_dt(0, 10), _dt(0, 14), uuid4()),
        ]
        periods = svc._emit_infrastructure_period(rid, cluster, ids)
        assert len(periods) >= 1
        assert all(p.resource_type == ResourceType.infrastructure for p in periods)
        assert all(p.total_assigned_percent >= 200.0 for p in periods)

    def test_touching_intervals_do_not_conflict(self):
        """Intervals that only touch at an endpoint do not overlap."""
        svc = _service()
        rid = uuid4()
        cluster = [
            (_dt(0, 8), _dt(0, 10), uuid4()),
            (_dt(0, 10), _dt(0, 12), uuid4()),
        ]
        assert svc._emit_infrastructure_period(rid, cluster, set()) == []

    @given(count=st.integers(min_value=2, max_value=6))
    @settings(max_examples=30)
    def test_all_identical_intervals_conflict(self, count: int):
        """Multiple identical overlapping intervals are always a conflict."""
        svc = _service()
        rid = uuid4()
        ids = {uuid4() for _ in range(count)}
        cluster = [(_dt(0, 8), _dt(0, 16), uuid4()) for _ in range(count)]
        periods = svc._emit_infrastructure_period(rid, cluster, ids)
        assert len(periods) >= 1
        assert max(p.total_assigned_percent for p in periods) >= count * 100.0
