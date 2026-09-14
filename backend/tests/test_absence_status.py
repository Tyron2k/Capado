"""Tests for the provisional/confirmed absence status.

The rule worth pinning is that both statuses reduce capacity **identically**. The intuitive
implementation — provisional leave is not real yet, so it does not count — passes any test that
only checks "does the status round-trip", and produces plans that break at approval rather than
now. So the assertions here are about the arithmetic, not about the field.

Uses the ``from_data`` seam of :class:`WorkingTimeService`, so the real availability code path
runs. No database.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.models.absence import Absence, AbsenceStatus
from app.models.calendar import WorkWeekProfile
from app.models.resource import ResourceType
from app.services.working_time_service import WorkingTimeService

RESOURCE = UUID("11111111-0000-0000-0000-000000000001")
MONDAY = date(2026, 8, 24)

FULL_WEEK = WorkWeekProfile(
    name="5x8",
    monday_minutes=480,
    tuesday_minutes=480,
    wednesday_minutes=480,
    thursday_minutes=480,
    friday_minutes=480,
    saturday_minutes=0,
    sunday_minutes=0,
)


def _absence(status: AbsenceStatus, percent: float = 100.0) -> Absence:
    return Absence(
        resource_id=RESOURCE,
        resource_type=ResourceType.personal,
        reason="planned",
        start_date=MONDAY,
        end_date=MONDAY,
        allocation_percent=percent,
        status=status,
    )


def _service(*absences: Absence) -> WorkingTimeService:
    return WorkingTimeService.from_data(
        default_profile=FULL_WEEK,
        absences={RESOURCE: list(absences)},
    )


class TestCapacityIsReducedRegardlessOfStatus:
    def test_a_confirmed_absence_removes_the_day(self):
        service = _service(_absence(AbsenceStatus.confirmed))
        assert service.available_minutes(RESOURCE, MONDAY) == 0

    def test_a_provisional_absence_removes_the_day_TOO(self):
        """The decision this feature turns on. Counting it as free capacity would plan
        work against a day likely to disappear, and the plan would break at approval —
        the one moment nobody is looking at it."""
        service = _service(_absence(AbsenceStatus.provisional))
        assert service.available_minutes(RESOURCE, MONDAY) == 0

    def test_both_statuses_give_the_same_number(self):
        confirmed = _service(_absence(AbsenceStatus.confirmed))
        provisional = _service(_absence(AbsenceStatus.provisional))
        assert confirmed.available_minutes(
            RESOURCE, MONDAY
        ) == provisional.available_minutes(RESOURCE, MONDAY)

    def test_a_partial_provisional_absence_reduces_proportionally(self):
        service = _service(_absence(AbsenceStatus.provisional, percent=50.0))
        assert service.available_minutes(RESOURCE, MONDAY) == 240


class TestProvisionalPercent:
    def test_a_day_with_no_absence_reports_zero(self):
        assert _service().provisional_percent(RESOURCE, MONDAY) == 0.0

    def test_a_confirmed_absence_is_not_reported_as_negotiable(self):
        service = _service(_absence(AbsenceStatus.confirmed))
        assert service.provisional_percent(RESOURCE, MONDAY) == 0.0
        assert service.absence_percent(RESOURCE, MONDAY) == 100.0

    def test_a_fully_provisional_day_reports_the_whole_gap(self):
        """Both methods returning the same number is what "the entire gap is still open"
        looks like, which is why they are capped the same way."""
        service = _service(_absence(AbsenceStatus.provisional))
        assert service.provisional_percent(RESOURCE, MONDAY) == 100.0
        assert service.absence_percent(RESOURCE, MONDAY) == 100.0

    def test_a_mixed_day_reports_only_the_provisional_share(self):
        service = _service(
            _absence(AbsenceStatus.confirmed, percent=60.0),
            _absence(AbsenceStatus.provisional, percent=40.0),
        )
        assert service.absence_percent(RESOURCE, MONDAY) == 100.0
        assert service.provisional_percent(RESOURCE, MONDAY) == 40.0

    def test_the_provisional_share_is_capped_like_the_total(self):
        service = _service(
            _absence(AbsenceStatus.provisional, percent=80.0),
            _absence(AbsenceStatus.provisional, percent=80.0),
        )
        assert service.provisional_percent(RESOURCE, MONDAY) == 100.0

    def test_a_day_outside_the_absence_range_reports_nothing(self):
        service = _service(_absence(AbsenceStatus.provisional))
        assert service.provisional_percent(RESOURCE, date(2026, 8, 25)) == 0.0


class TestDefault:
    def test_an_absence_without_an_explicit_status_is_confirmed(self):
        """Matching migration 023: an absence somebody typed in is a fact unless they said
        otherwise, and defaulting the other way would reclassify existing recorded leave of
        the whole workforce as uncertain."""
        absence = Absence(
            resource_id=RESOURCE,
            resource_type=ResourceType.personal,
            reason="planned",
            start_date=MONDAY,
            end_date=MONDAY,
        )
        assert absence.status == AbsenceStatus.confirmed
