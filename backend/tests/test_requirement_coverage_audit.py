"""Cross-service characterization of work-package requirement coverage.

These tests compare persisted aggregate coverage with the qualification mismatch
check for the *same* assignments. Confirmed safe behavior is asserted normally;
qualification and temporal false positives are ordinary regression checks.

The SQLite-backed `db_session` uses the real mapped tables, but this is not a
substitute for PostgreSQL-specific integration or concurrent-write testing.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.assignment import Assignment
from app.models.calendar import WorkWeekProfile
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.skill import (
    InfrastructureResourceSkill,
    PersonalResourceSkill,
    Skill,
    SkillAttribute,
)
from app.models.work_package_requirement import RequirementMode, WorkPackageRequirement
from app.services.skill_mismatch import detect_mismatches
from app.services.unmet_requirements_service import get_unmet_requirements
from tests.planning_reference import _seed_case

DAY = date(2099, 1, 5)
LAST_DAY = DAY + timedelta(days=2)


async def _mismatches(session, package, bookings):
    """Use the same persisted assignments as the aggregate-coverage call."""
    return await detect_mismatches(
        session,
        [(b.id, b.resource_id, package.id) for b in bookings],
        {package.id},
        {b.resource_id for b in bookings},
    )


@pytest.mark.parametrize("kind", [ResourceType.personal, ResourceType.infrastructure])
async def test_valid_resource_is_covered_and_not_mismatched(db_session, kind):
    """Both service paths agree for a qualified, fully allocated resource."""
    package, bookings = await _seed_case(
        db_session, kind=kind, minimum_level=3, people=[{"level": 4}]
    )
    assert await _mismatches(db_session, package, bookings) == set()
    assert await get_unmet_requirements(db_session, resource_type=kind.value) == []


async def test_missing_qualification_is_unmet_and_mismatched(db_session):
    """An assignment with no matching skill cannot satisfy the requirement."""
    package, bookings = await _seed_case(
        db_session, minimum_level=3, people=[{"qualified": False}]
    )
    assert await _mismatches(db_session, package, bookings) == {bookings[0].id}
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert len(unmet) == 1
    assert unmet[0].assigned_quantity == 0
    assert unmet[0].gap == 1


@pytest.fixture(
    params=[
        (ResourceType.personal, {"level": 4, "valid_until": DAY - timedelta(days=1)}),
        (ResourceType.personal, {"level": 2}),
        (ResourceType.personal, {"level": None}),
        (ResourceType.personal, {"level": 4, "valid_from": DAY + timedelta(days=1)}),
        (ResourceType.personal, {"valid_until": DAY + timedelta(days=1)}),
        (ResourceType.infrastructure, {"level": 2}),
        (ResourceType.infrastructure, {"level": None}),
        (ResourceType.infrastructure, {"valid_from": DAY + timedelta(days=1)}),
        (
            ResourceType.infrastructure,
            {
                "valid_until": DAY + timedelta(days=1),
                "end_at": datetime(2099, 1, 7, 12, tzinfo=UTC),
            },
        ),
        (
            ResourceType.infrastructure,
            {"level": 4, "valid_until": DAY - timedelta(days=1)},
        ),
    ],
    ids=[
        "expired-person",
        "below-minimum-level",
        "unassessed-level",
        "not-yet-valid",
        "mid-booking-expiry",
        "machine-below-minimum-level",
        "machine-unassessed-level",
        "machine-not-yet-valid",
        "machine-mid-booking-expiry",
        "expired-machine",
    ],
)
async def unqualified_case(db_session, request):
    """Persist the same unqualified-resource cases for both service checks."""
    kind, details = request.param
    package, bookings = await _seed_case(
        db_session, kind=kind, minimum_level=3, people=[details]
    )
    return kind, package, bookings


async def test_unqualified_resource_is_mismatched(db_session, unqualified_case):
    """Qualification mismatch detection must keep rejecting these bookings."""
    _, package, bookings = unqualified_case
    assert await _mismatches(db_session, package, bookings) == {bookings[0].id}


async def test_unqualified_resource_must_not_cover_requirement(
    db_session, unqualified_case
):
    """Aggregate coverage should reject the same unqualified bookings."""
    kind, _, _ = unqualified_case
    unmet = await get_unmet_requirements(db_session, resource_type=kind.value)
    assert len(unmet) == 1
    assert unmet[0].assigned_quantity == 0
    assert unmet[0].gap == 1


async def test_headcount_counts_one_resource_once_across_bookings(db_session):
    """Two bookings for one person do not become two distinct bodies."""
    package, bookings = await _seed_case(
        db_session,
        quantity=2,
        people=[{"start_date": DAY, "end_date": DAY}],
    )
    db_session.add(
        Assignment(
            resource_type=ResourceType.personal,
            resource_id=bookings[0].resource_id,
            work_package_id=package.id,
            start_date=DAY + timedelta(days=1),
            end_date=LAST_DAY,
            allocation_percent=100.0,
        )
    )
    await db_session.commit()
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert len(unmet) == 1
    assert unmet[0].assigned_quantity == 1
    assert unmet[0].gap == 1


async def test_effort_mode_sums_two_half_allocations(db_session):
    """Divisible effort can be covered by distinct half-allocated people."""
    package, bookings = await _seed_case(
        db_session,
        quantity=1,
        mode=RequirementMode.effort_fte,
        people=[{"allocation": 50.0}, {"allocation": 50.0}],
    )
    assert await _mismatches(db_session, package, bookings) == set()
    assert await get_unmet_requirements(db_session, resource_type="personal") == []


@pytest.fixture
async def staggered_crew(db_session):
    """Persist qualified people whose bookings do not overlap."""
    return await _seed_case(
        db_session,
        quantity=2,
        people=[
            {"start_date": DAY, "end_date": DAY},
            {"start_date": DAY + timedelta(days=1), "end_date": LAST_DAY},
        ],
    )


async def test_staggered_people_are_not_mismatched(db_session, staggered_crew):
    """Disjoint booking dates do not make either person's qualification invalid."""
    package, bookings = staggered_crew
    assert await _mismatches(db_session, package, bookings) == set()


async def test_staggered_people_do_not_cover_two_person_crew(
    db_session, staggered_crew
):
    """Two people on disjoint days cannot staff a two-person crew together."""
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert len(unmet) == 1
    assert unmet[0].gap >= 1


@pytest.mark.parametrize("kind", [ResourceType.personal, ResourceType.infrastructure])
@pytest.mark.parametrize("level,minimum", [(3, 3), (None, None)])
async def test_qualification_boundaries_are_inclusive(db_session, kind, level, minimum):
    """Exact date/level boundaries and an unspecified minimum remain supported."""
    package, bookings = await _seed_case(
        db_session,
        kind=kind,
        minimum_level=minimum,
        people=[
            {
                "level": level,
                "valid_from": DAY,
                "valid_until": LAST_DAY if kind == ResourceType.personal else DAY,
            }
        ],
    )
    assert await _mismatches(db_session, package, bookings) == set()
    assert await get_unmet_requirements(db_session, resource_type=kind.value) == []


async def test_coverage_checks_each_requirement_not_just_any_matching_one(db_session):
    """A resource satisfying one requirement cannot fill a stricter second one."""
    package, bookings = await _seed_case(
        db_session, minimum_level=3, people=[{"level": 4}]
    )
    requirement = (
        await db_session.execute(select(WorkPackageRequirement))
    ).scalar_one()
    db_session.add(
        WorkPackageRequirement(
            work_package_id=package.id,
            skill_id=requirement.skill_id,
            skill_attribute_id=None,
            quantity=1,
            min_level=5,
        )
    )
    await db_session.commit()
    assert await _mismatches(db_session, package, bookings) == set()
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert len(unmet) == 1
    assert unmet[0].attribute_name is None
    assert unmet[0].assigned_quantity == 0
    assert unmet[0].gap == 1
    assert unmet[0].suggestions == []


@pytest.mark.parametrize("kind", [ResourceType.personal, ResourceType.infrastructure])
async def test_suggestions_require_valid_qualified_active_candidates(db_session, kind):
    """Candidates must qualify for the whole package, not merely hold an attribute."""
    _, bookings = await _seed_case(
        db_session,
        kind=kind,
        minimum_level=3,
        people=[
            {"level": 3, "valid_from": DAY, "valid_until": LAST_DAY},
            {"valid_until": DAY - timedelta(days=1)},
            {"valid_from": DAY + timedelta(days=1)},
            {"level": 2},
            {"level": None},
            {"valid_until": DAY + timedelta(days=1)},
            {"qualified": False},
            {"active": False},
        ],
    )
    expected = bookings[0].resource_id
    for booking in bookings:
        await db_session.delete(booking)
    await db_session.commit()
    unmet = await get_unmet_requirements(db_session, resource_type=kind.value)
    assert len(unmet) == 1
    assert unmet[0].assigned_quantity == 0
    assert [s.resource_id for s in unmet[0].suggestions] == [expected]
    assert unmet[0].suggestions[0].resource_type == kind.value
