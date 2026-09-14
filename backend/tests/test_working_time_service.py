"""Tests for :mod:`app.services.working_time_service`.

This is the arithmetic every capacity number and every conflict now rests on
(ADR-004), so the three scenarios the model is *designed* to distinguish are
asserted explicitly rather than left to inference:

- a weekend places no demand and cannot conflict,
- a vacation day does conflict, because it is a working day with no
  availability — the "on leave but assigned" signal,
- a part-time resource booked at 100% conflicts, because percent is a share of
  a normative day rather than of that resource.

No database: the service is built through :meth:`WorkingTimeService.from_data`.
All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date, time
from uuid import UUID, uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.absence import Absence, AbsenceReason
from app.models.calendar import (
    InfrastructureAvailabilityWindow,
    ResourceWorkProfile,
    WorkWeekProfile,
)
from app.models.resource import ResourceType
from app.services.working_time_service import (
    NORMATIVE_DAY_MINUTES,
    WorkingTimeService,
    percent_to_minutes,
)

# 2026-06-01 is a Monday; the week runs Mon 1st through Sun 7th.
MONDAY = date(2026, 6, 1)
FRIDAY = date(2026, 6, 5)
SATURDAY = date(2026, 6, 6)
SUNDAY = date(2026, 6, 7)

RESOURCE_ID = UUID("11111111-1111-1111-1111-111111111111")
SITE_ID = UUID("22222222-2222-2222-2222-222222222222")


def _full_time_profile() -> WorkWeekProfile:
    """Monday to Friday eight hours, weekend free."""
    return WorkWeekProfile(id=uuid4(), name="Standard 5-Tage 8 h", is_default=True)


def _part_time_profile() -> WorkWeekProfile:
    """Thirty hours: Monday to Thursday 7.5 h, Friday off."""
    return WorkWeekProfile(
        id=uuid4(),
        name="Teilzeit 30 h Mo-Do",
        monday_minutes=450,
        tuesday_minutes=450,
        wednesday_minutes=450,
        thursday_minutes=450,
        friday_minutes=0,
        saturday_minutes=0,
        sunday_minutes=0,
    )


def _absence(
    start: date, end: date, percent: float = 100.0, resource_id: UUID = RESOURCE_ID
) -> Absence:
    """Fictional absence covering the given range."""
    return Absence(
        id=uuid4(),
        resource_id=resource_id,
        resource_type=ResourceType.personal,
        reason=AbsenceReason.planned,
        start_date=start,
        end_date=end,
        allocation_percent=percent,
    )


def _service(
    *,
    profile: WorkWeekProfile | None = None,
    holidays: dict[tuple[UUID, date], int] | None = None,
    absences: list[Absence] | None = None,
    windows: list[InfrastructureAvailabilityWindow] | None = None,
    with_site: bool = True,
) -> WorkingTimeService:
    """Build a service for one fictional resource."""
    profile = profile or _full_time_profile()
    return WorkingTimeService.from_data(
        default_profile=profile,
        profiles={profile.id: profile},
        sites={RESOURCE_ID: SITE_ID if with_site else None},
        holidays=holidays or {},
        absences={RESOURCE_ID: absences} if absences else {},
        windows={RESOURCE_ID: windows} if windows else {},
    )


# ---------------------------------------------------------------------------
# percent_to_minutes
# ---------------------------------------------------------------------------


class TestPercentToMinutes:
    """Conversion happens once, at the boundary, and yields integers."""

    def test_hundred_percent_is_a_normative_day(self):
        """100% is exactly one normative working day."""
        assert percent_to_minutes(100) == NORMATIVE_DAY_MINUTES

    def test_half_is_half_a_day(self):
        """50% of a 480-minute day is four hours."""
        assert percent_to_minutes(50) == 240

    @given(percent=st.floats(min_value=0, max_value=100))
    @settings(max_examples=50)
    def test_result_is_always_an_int_within_the_day(self, percent: float):
        """Any share in range converts to an integer bounded by the day."""
        minutes = percent_to_minutes(percent)
        assert isinstance(minutes, int)
        assert 0 <= minutes <= NORMATIVE_DAY_MINUTES


# ---------------------------------------------------------------------------
# calendar_minutes — the supply from profile and site calendar
# ---------------------------------------------------------------------------


class TestCalendarMinutes:
    """Week profile, overridden by a holiday row for that site and date."""

    def test_working_day_comes_from_the_profile(self):
        """A Monday on a standard profile grants a full day."""
        assert _service().calendar_minutes(RESOURCE_ID, MONDAY) == 480

    def test_weekend_grants_nothing(self):
        """Saturday and Sunday are zero on a standard profile."""
        service = _service()
        assert service.calendar_minutes(RESOURCE_ID, SATURDAY) == 0
        assert service.calendar_minutes(RESOURCE_ID, SUNDAY) == 0

    def test_part_time_profile_shortens_the_day(self):
        """A 30 h profile grants 450 minutes Monday and nothing Friday."""
        service = _service(profile=_part_time_profile())
        assert service.calendar_minutes(RESOURCE_ID, MONDAY) == 450
        assert service.calendar_minutes(RESOURCE_ID, FRIDAY) == 0

    def test_holiday_overrides_the_profile(self):
        """A holiday row wins over the week profile."""
        service = _service(holidays={(SITE_ID, MONDAY): 0})
        assert service.calendar_minutes(RESOURCE_ID, MONDAY) == 0

    def test_half_day_holiday_is_expressible(self):
        """24 December style half days need no special case."""
        service = _service(holidays={(SITE_ID, MONDAY): 240})
        assert service.calendar_minutes(RESOURCE_ID, MONDAY) == 240

    def test_designated_working_saturday_is_expressible(self):
        """A holiday row can also open a day the profile calls free.

        Real plant calendars contain working Saturdays; this is why the row
        carries minutes rather than a boolean.
        """
        service = _service(holidays={(SITE_ID, SATURDAY): 480})
        assert service.calendar_minutes(RESOURCE_ID, SATURDAY) == 480

    def test_holiday_of_another_site_does_not_apply(self):
        """Calendars are per site, so a foreign row must not leak."""
        other_site = uuid4()
        service = _service(holidays={(other_site, MONDAY): 0})
        assert service.calendar_minutes(RESOURCE_ID, MONDAY) == 480

    def test_resource_without_a_site_ignores_holidays(self):
        """Without a site there is no calendar to override the profile."""
        service = _service(holidays={(SITE_ID, MONDAY): 0}, with_site=False)
        assert service.calendar_minutes(RESOURCE_ID, MONDAY) == 480


# ---------------------------------------------------------------------------
# available_minutes — supply reduced by absences
# ---------------------------------------------------------------------------


class TestAvailableMinutes:
    """An absence is a share of the resource's own day, not of a normal day."""

    def test_without_absence_available_equals_calendar(self):
        """Nothing removed means nothing missing."""
        assert _service().available_minutes(RESOURCE_ID, MONDAY) == 480

    def test_full_absence_removes_the_whole_day(self):
        """A 100% absence leaves no availability."""
        service = _service(absences=[_absence(MONDAY, MONDAY)])
        assert service.available_minutes(RESOURCE_ID, MONDAY) == 0

    def test_half_absence_halves_the_day(self):
        """50% of a full-time day is four hours left."""
        service = _service(absences=[_absence(MONDAY, MONDAY, percent=50)])
        assert service.available_minutes(RESOURCE_ID, MONDAY) == 240

    def test_absence_scales_to_the_part_time_day(self):
        """A full day off for a 7.5 h resource removes 450, not 480."""
        service = _service(
            profile=_part_time_profile(), absences=[_absence(MONDAY, MONDAY)]
        )
        assert service.available_minutes(RESOURCE_ID, MONDAY) == 0
        assert service.calendar_minutes(RESOURCE_ID, MONDAY) == 450

    def test_overlapping_absences_cannot_exceed_the_day(self):
        """Two overlapping absences cap at 100%, never negative availability."""
        service = _service(
            absences=[
                _absence(MONDAY, MONDAY, percent=80),
                _absence(MONDAY, MONDAY, percent=80),
            ]
        )
        assert service.absence_percent(RESOURCE_ID, MONDAY) == 100.0
        assert service.available_minutes(RESOURCE_ID, MONDAY) == 0

    @given(percent=st.floats(min_value=0.1, max_value=100))
    @settings(max_examples=50)
    def test_available_never_exceeds_calendar(self, percent: float):
        """An absence can only ever reduce supply."""
        service = _service(absences=[_absence(MONDAY, MONDAY, percent=percent)])
        available = service.available_minutes(RESOURCE_ID, MONDAY)
        assert 0 <= available <= service.calendar_minutes(RESOURCE_ID, MONDAY)


# ---------------------------------------------------------------------------
# demand_minutes and the three scenarios the model must distinguish
# ---------------------------------------------------------------------------


class TestDemandMinutes:
    """Demand is gated on the calendar, not on availability."""

    def test_working_day_demand_is_a_share_of_a_normative_day(self):
        """50% on a working day demands four hours."""
        assert _service().demand_minutes(RESOURCE_ID, MONDAY, 50) == 240

    def test_weekend_carries_no_demand(self):
        """Assignments span weekends; charging them there would be noise."""
        service = _service()
        assert service.demand_minutes(RESOURCE_ID, SATURDAY, 100) == 0
        assert service.demand_minutes(RESOURCE_ID, SUNDAY, 100) == 0

    def test_public_holiday_carries_no_demand(self):
        """A holiday grants no time, so nothing is demanded of it."""
        service = _service(holidays={(SITE_ID, MONDAY): 0})
        assert service.demand_minutes(RESOURCE_ID, MONDAY, 100) == 0

    @given(percent=st.floats(min_value=0.1, max_value=100))
    @settings(max_examples=50)
    def test_non_working_day_demand_is_always_zero(self, percent: float):
        """No share, however large, creates demand on a non-working day."""
        assert _service().demand_minutes(RESOURCE_ID, SUNDAY, percent) == 0


class TestConflictScenarios:
    """The distinctions ADR-004 exists to make, asserted end to end."""

    def test_weekend_assignment_does_not_conflict(self):
        """Demand 0 against availability 0 is not an over-allocation."""
        service = _service()
        demand = service.demand_minutes(RESOURCE_ID, SUNDAY, 100)
        available = service.available_minutes(RESOURCE_ID, SUNDAY)
        assert demand <= available

    def test_assignment_on_a_vacation_day_conflicts(self):
        """A vacation day is a working day with no availability.

        This is the signal that would silently disappear if absences reduced
        the calendar instead of only availability.
        """
        service = _service(absences=[_absence(MONDAY, MONDAY)])
        demand = service.demand_minutes(RESOURCE_ID, MONDAY, 100)
        available = service.available_minutes(RESOURCE_ID, MONDAY)
        assert demand == 480
        assert available == 0
        assert demand > available

    def test_part_time_resource_booked_full_conflicts(self):
        """100% means a normative day, which a 7.5 h resource cannot supply."""
        service = _service(profile=_part_time_profile())
        demand = service.demand_minutes(RESOURCE_ID, MONDAY, 100)
        available = service.available_minutes(RESOURCE_ID, MONDAY)
        assert demand == 480
        assert available == 450
        assert demand > available

    def test_part_time_resource_booked_within_capacity_does_not_conflict(self):
        """A 90% booking fits inside a 450-minute day."""
        service = _service(profile=_part_time_profile())
        demand = service.demand_minutes(RESOURCE_ID, MONDAY, 90)
        assert demand == 432
        assert demand <= service.available_minutes(RESOURCE_ID, MONDAY)

    def test_full_time_resource_booked_full_does_not_conflict(self):
        """The ordinary case must stay quiet."""
        service = _service()
        demand = service.demand_minutes(RESOURCE_ID, MONDAY, 100)
        assert demand == service.available_minutes(RESOURCE_ID, MONDAY)


# ---------------------------------------------------------------------------
# Infrastructure availability windows (ADR-005)
# ---------------------------------------------------------------------------


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


class TestAvailabilityWindows:
    """No windows means unrestricted, so the table changes nothing by default."""

    def test_resource_without_windows_is_available_all_day(self):
        """The pre-ADR-005 default is preserved."""
        assert _service().window_minutes(RESOURCE_ID, MONDAY) == 1440

    def test_single_window_bounds_the_day(self):
        """One shift from 06:00 to 14:00 is eight hours."""
        service = _service(windows=[_window(0, (6, 0), (14, 0))])
        assert service.window_minutes(RESOURCE_ID, MONDAY) == 480

    def test_two_shifts_add_up(self):
        """Multi-shift operation is two rows, not one artificial span."""
        service = _service(
            windows=[_window(0, (6, 0), (14, 0)), _window(0, (14, 0), (22, 0))]
        )
        assert service.window_minutes(RESOURCE_ID, MONDAY) == 960

    def test_overlapping_windows_do_not_inflate_the_day(self):
        """A misconfigured pair must not report more time than exists."""
        service = _service(
            windows=[_window(0, (6, 0), (14, 0)), _window(0, (10, 0), (18, 0))]
        )
        assert service.window_minutes(RESOURCE_ID, MONDAY) == 720

    def test_windows_apply_only_to_their_weekday(self):
        """A Monday window says nothing about Tuesday."""
        service = _service(windows=[_window(0, (6, 0), (14, 0))])
        assert service.window_minutes(RESOURCE_ID, FRIDAY) == 0

    def test_holiday_suppresses_every_window(self):
        """A machine does not run on a plant holiday."""
        service = _service(
            windows=[_window(0, (6, 0), (14, 0))],
            holidays={(SITE_ID, MONDAY): 0},
        )
        assert service.windows_for(RESOURCE_ID, MONDAY) == []
        assert service.window_minutes(RESOURCE_ID, MONDAY) == 0

    def test_half_day_holiday_still_suppresses_windows(self):
        """working_minutes > 0 is about people, not about machine hours."""
        service = _service(
            windows=[_window(0, (6, 0), (14, 0))],
            holidays={(SITE_ID, MONDAY): 240},
        )
        assert service.window_minutes(RESOURCE_ID, MONDAY) == 0


# ---------------------------------------------------------------------------
# Dated profile bindings
# ---------------------------------------------------------------------------


class TestProfileBindings:
    """A contract change is a new row, so past capacity stays reproducible."""

    def test_binding_in_force_wins_over_the_default(self):
        """A covering binding selects its own profile."""
        part_time = _part_time_profile()
        full_time = _full_time_profile()
        binding = ResourceWorkProfile(
            id=uuid4(),
            resource_id=RESOURCE_ID,
            profile_id=part_time.id,
            valid_from=MONDAY,
            valid_until=None,
        )
        service = WorkingTimeService.from_data(
            default_profile=full_time,
            profiles={part_time.id: part_time, full_time.id: full_time},
            bindings={RESOURCE_ID: [binding]},
            sites={RESOURCE_ID: SITE_ID},
        )
        assert service.calendar_minutes(RESOURCE_ID, MONDAY) == 450

    def test_expired_binding_falls_back_to_the_default(self):
        """Outside its validity a binding does not apply."""
        part_time = _part_time_profile()
        full_time = _full_time_profile()
        binding = ResourceWorkProfile(
            id=uuid4(),
            resource_id=RESOURCE_ID,
            profile_id=part_time.id,
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 5, 31),
        )
        service = WorkingTimeService.from_data(
            default_profile=full_time,
            profiles={part_time.id: part_time, full_time.id: full_time},
            bindings={RESOURCE_ID: [binding]},
            sites={RESOURCE_ID: SITE_ID},
        )
        assert service.calendar_minutes(RESOURCE_ID, MONDAY) == 480

    def test_without_any_profile_there_is_no_capacity(self):
        """A deployment with no default profile reports zero, not a crash."""
        service = WorkingTimeService.from_data(sites={RESOURCE_ID: SITE_ID})
        assert service.calendar_minutes(RESOURCE_ID, MONDAY) == 0
        assert service.demand_minutes(RESOURCE_ID, MONDAY, 100) == 0
