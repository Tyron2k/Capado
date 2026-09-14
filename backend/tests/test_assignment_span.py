"""Tests for :func:`app.services.unmet_requirements_service.assignment_span`.

Written for a real bug rather than for coverage: the busyness ranking read only
`start_date`/`end_date`, so every infrastructure booking was invisible to it. Those rows
keep the dates NULL and use `start_at`/`end_at`, and in SQL `NULL <= x` is not true — so a
fully booked hall reported zero assignments and ranked as the LEAST busy candidate. It was
found by re-enabling the mypy error codes that `pyproject.toml` disables, not by anything
failing.

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from app.models.assignment import Assignment
from app.models.resource import ResourceType
from app.services.unmet_requirements_service import assignment_span


def _personal(start: date, end: date) -> Assignment:
    """A personal assignment: dates and a percentage, timestamps NULL."""
    return Assignment(
        id=uuid4(),
        resource_id=uuid4(),
        resource_type=ResourceType.personal,
        work_package_id=uuid4(),
        start_date=start,
        end_date=end,
        allocation_percent=80,
    )


def _infrastructure(start: datetime, end: datetime) -> Assignment:
    """An infrastructure assignment: timestamps only, dates and percentage NULL.

    This is the shape every one of the 85 assignments in the live deployment has.
    """
    return Assignment(
        id=uuid4(),
        resource_id=uuid4(),
        resource_type=ResourceType.infrastructure,
        work_package_id=uuid4(),
        start_at=start,
        end_at=end,
    )


class TestAssignmentSpan:
    """One range out of two mutually exclusive column sets."""

    def test_a_personal_assignment_uses_its_dates(self):
        span = assignment_span(_personal(date(2026, 3, 2), date(2026, 3, 20)))
        assert span == (date(2026, 3, 2), date(2026, 3, 20))

    def test_an_infrastructure_assignment_uses_its_timestamps(self):
        """The case that was silently dropped."""
        span = assignment_span(
            _infrastructure(datetime(2026, 3, 2, 6, 0), datetime(2026, 3, 20, 14, 0))
        )
        assert span == (date(2026, 3, 2), date(2026, 3, 20))

    def test_the_time_of_day_is_discarded_not_rounded(self):
        """A booking ending at 00:30 still occupies that day.

        Truncating to the date is deliberate: the ranking asks which days a resource is
        busy on, and a booking that runs half an hour into a day occupies it.
        """
        span = assignment_span(
            _infrastructure(datetime(2026, 3, 2, 23, 0), datetime(2026, 3, 3, 0, 30))
        )
        assert span == (date(2026, 3, 2), date(2026, 3, 3))

    def test_a_single_day_infrastructure_booking(self):
        span = assignment_span(
            _infrastructure(datetime(2026, 3, 2, 6, 0), datetime(2026, 3, 2, 14, 0))
        )
        assert span == (date(2026, 3, 2), date(2026, 3, 2))

    def test_a_row_with_neither_pair_is_skipped_not_fatal(self):
        """Should not occur, but is not worth crashing a ranking over."""
        empty = Assignment(
            id=uuid4(),
            resource_id=uuid4(),
            resource_type=ResourceType.infrastructure,
            work_package_id=uuid4(),
        )
        assert assignment_span(empty) is None

    def test_dates_win_when_both_pairs_are_somehow_present(self):
        """Not a shape the writers produce, but the reading has to be deterministic."""
        both = _personal(date(2026, 3, 2), date(2026, 3, 20))
        both.start_at = datetime(2026, 6, 1, 6, 0)
        both.end_at = datetime(2026, 6, 30, 14, 0)
        assert assignment_span(both) == (date(2026, 3, 2), date(2026, 3, 20))

    def test_a_half_open_row_falls_through_to_none(self):
        """One timestamp without the other cannot describe a range."""
        partial = Assignment(
            id=uuid4(),
            resource_id=uuid4(),
            resource_type=ResourceType.infrastructure,
            work_package_id=uuid4(),
            start_at=datetime(2026, 3, 2, 6, 0),
        )
        assert assignment_span(partial) is None
