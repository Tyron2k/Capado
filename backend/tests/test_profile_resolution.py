"""Tests for week-profile resolution across resource, group and default.

The order is the whole point of group bindings: a department states its hours
once, and one individual row overrides it for the part-time employee. Without the
override winning, group bindings would be useless; without inheritance, a plant
with 1600 people would need 1600 rows and nobody would maintain them.

No database: the service is built through :meth:`WorkingTimeService.from_data`.
All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from app.models.calendar import ResourceWorkProfile, WorkWeekProfile
from app.services.working_time_service import WorkingTimeService

MONDAY = date(2026, 6, 1)

RESOURCE = UUID("11111111-1111-1111-1111-111111111111")
DEPARTMENT = UUID("22222222-2222-2222-2222-222222222222")
PLANT = UUID("33333333-3333-3333-3333-333333333333")


def _profile(name: str, minutes: int) -> WorkWeekProfile:
    """Profile granting the same minutes Monday through Friday."""
    return WorkWeekProfile(
        id=uuid4(),
        name=name,
        monday_minutes=minutes,
        tuesday_minutes=minutes,
        wednesday_minutes=minutes,
        thursday_minutes=minutes,
        friday_minutes=minutes,
        saturday_minutes=0,
        sunday_minutes=0,
    )


def _binding(
    profile: WorkWeekProfile,
    *,
    resource_id: UUID | None = None,
    group_id: UUID | None = None,
    valid_from: date = date(2020, 1, 1),
    valid_until: date | None = None,
) -> ResourceWorkProfile:
    """Binding of a profile to a resource or a group."""
    return ResourceWorkProfile(
        id=uuid4(),
        resource_id=resource_id,
        group_id=group_id,
        profile_id=profile.id,
        valid_from=valid_from,
        valid_until=valid_until,
    )


DEFAULT = _profile("Standard 8 h", 480)
DEPARTMENT_PROFILE = _profile("Frühschicht 6-15", 540)
INDIVIDUAL_PROFILE = _profile("Teilzeit 6 h", 360)
PLANT_PROFILE = _profile("Werksstandard 7 h", 420)


def _service(
    bindings: list[ResourceWorkProfile] | None = None,
    group_bindings: list[ResourceWorkProfile] | None = None,
    group_parents: dict[UUID, UUID | None] | None = None,
) -> WorkingTimeService:
    """Service for one fictional resource in one department."""
    profiles = {
        p.id: p
        for p in (DEFAULT, DEPARTMENT_PROFILE, INDIVIDUAL_PROFILE, PLANT_PROFILE)
    }
    grouped: dict[UUID, list[ResourceWorkProfile]] = {}
    for binding in group_bindings or []:
        assert binding.group_id is not None
        grouped.setdefault(binding.group_id, []).append(binding)
    return WorkingTimeService.from_data(
        default_profile=DEFAULT,
        profiles=profiles,
        bindings={RESOURCE: bindings} if bindings else {},
        group_bindings=grouped,
        groups={RESOURCE: DEPARTMENT},
        group_parents=group_parents or {DEPARTMENT: None},
        sites={RESOURCE: None},
    )


class TestResolutionOrder:
    """Most specific binding wins."""

    def test_no_binding_falls_back_to_the_default(self):
        """A fresh install has capacity rather than reporting zero."""
        assert _service().calendar_minutes(RESOURCE, MONDAY) == 480

    def test_group_binding_applies_to_its_members(self):
        """A department states its hours once, for everyone under it."""
        service = _service(
            group_bindings=[_binding(DEPARTMENT_PROFILE, group_id=DEPARTMENT)]
        )
        assert service.calendar_minutes(RESOURCE, MONDAY) == 540

    def test_individual_binding_overrides_the_group(self):
        """The part-time employee is the exception, and the exception wins."""
        service = _service(
            bindings=[_binding(INDIVIDUAL_PROFILE, resource_id=RESOURCE)],
            group_bindings=[_binding(DEPARTMENT_PROFILE, group_id=DEPARTMENT)],
        )
        assert service.calendar_minutes(RESOURCE, MONDAY) == 360

    def test_parent_group_binding_is_inherited(self):
        """A plant-wide profile reaches a department that defines none."""
        service = _service(
            group_bindings=[_binding(PLANT_PROFILE, group_id=PLANT)],
            group_parents={DEPARTMENT: PLANT, PLANT: None},
        )
        assert service.calendar_minutes(RESOURCE, MONDAY) == 420

    def test_own_group_beats_the_parent(self):
        """The nearer group wins, so a department can deviate from the plant."""
        service = _service(
            group_bindings=[
                _binding(DEPARTMENT_PROFILE, group_id=DEPARTMENT),
                _binding(PLANT_PROFILE, group_id=PLANT),
            ],
            group_parents={DEPARTMENT: PLANT, PLANT: None},
        )
        assert service.calendar_minutes(RESOURCE, MONDAY) == 540


class TestValidity:
    """Bindings are dated, so a past period stays reproducible."""

    def test_expired_individual_binding_yields_to_the_group(self):
        """When the exception ends, the department default takes over again."""
        service = _service(
            bindings=[
                _binding(
                    INDIVIDUAL_PROFILE,
                    resource_id=RESOURCE,
                    valid_until=date(2026, 5, 31),
                )
            ],
            group_bindings=[_binding(DEPARTMENT_PROFILE, group_id=DEPARTMENT)],
        )
        assert service.calendar_minutes(RESOURCE, MONDAY) == 540

    def test_future_group_binding_does_not_apply_yet(self):
        """A binding that starts later must not change today."""
        service = _service(
            group_bindings=[
                _binding(
                    DEPARTMENT_PROFILE,
                    group_id=DEPARTMENT,
                    valid_from=date(2026, 7, 1),
                )
            ]
        )
        assert service.calendar_minutes(RESOURCE, MONDAY) == 480


class TestHierarchyRobustness:
    """The walk must terminate whatever the data says."""

    def test_cyclic_parents_do_not_hang(self):
        """A cycle from bad data must not loop forever."""
        service = _service(
            group_bindings=[_binding(PLANT_PROFILE, group_id=PLANT)],
            group_parents={DEPARTMENT: PLANT, PLANT: DEPARTMENT},
        )
        assert service.calendar_minutes(RESOURCE, MONDAY) == 420

    def test_resource_without_a_group_uses_the_default(self):
        """An ungrouped resource has no chain to walk."""
        service = WorkingTimeService.from_data(
            default_profile=DEFAULT,
            profiles={DEFAULT.id: DEFAULT},
            groups={RESOURCE: None},
            sites={RESOURCE: None},
        )
        assert service.calendar_minutes(RESOURCE, MONDAY) == 480
