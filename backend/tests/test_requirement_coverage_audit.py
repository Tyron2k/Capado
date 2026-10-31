"""Cross-service characterization of work-package requirement coverage.

These tests compare persisted aggregate coverage with the qualification mismatch
check for the *same* assignments. Confirmed safe behavior is asserted normally;
suspected false positives are strict xfails until the domain contract is fixed.

The SQLite-backed `db_session` uses the real mapped tables, but this is not a
substitute for PostgreSQL-specific integration or concurrent-write testing.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.models.assignment import Assignment
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

DAY = date(2099, 1, 5)
LAST_DAY = DAY + timedelta(days=2)


async def _seed_case(
    session,
    *,
    kind=ResourceType.personal,
    quantity=1,
    mode=RequirementMode.headcount,
    minimum_level=None,
    people=(),
):
    """Persist a small fictional requirement and the specified resource bookings."""
    group = ResourceGroup(name="Fixture team", resource_type=kind)
    skill = Skill(name="Fixture qualification", resource_type=kind.value)
    project = Project(name="Fixture project", start_date=DAY, end_date=LAST_DAY)
    session.add_all([group, skill, project])
    await session.flush()

    attribute = SkillAttribute(name="Fixture attribute", skill_id=skill.id)
    package = WorkPackage(
        name="Fixture package",
        project_id=project.id,
        start_date=DAY,
        end_date=LAST_DAY,
    )
    session.add_all([attribute, package])
    await session.flush()

    session.add(
        WorkPackageRequirement(
            work_package_id=package.id,
            skill_id=skill.id,
            skill_attribute_id=attribute.id,
            quantity=quantity,
            requirement_mode=mode,
            min_allocation_percent=100.0,
            min_level=minimum_level,
        )
    )

    bookings = []
    for index, person in enumerate(people):
        if kind == ResourceType.personal:
            resource = PersonalResource(name=f"Person {index}", group_id=group.id)
        else:
            resource = InfrastructureResource(
                name=f"Machine {index}", group_id=group.id
            )
        session.add(resource)
        await session.flush()

        if person.get("qualified", True):
            held = {
                "resource_id": resource.id,
                "skill_attribute_id": attribute.id,
                "level": person.get("level", 4),
                "valid_from": person.get("valid_from"),
                "valid_until": person.get("valid_until"),
            }
            if kind == ResourceType.personal:
                session.add(PersonalResourceSkill(**held))
            else:
                session.add(InfrastructureResourceSkill(**held))

        if kind == ResourceType.personal:
            booking = Assignment(
                resource_type=kind,
                resource_id=resource.id,
                work_package_id=package.id,
                start_date=person.get("start_date", DAY),
                end_date=person.get("end_date", LAST_DAY),
                allocation_percent=person.get("allocation", 100.0),
            )
        else:
            booking = Assignment(
                resource_type=kind,
                resource_id=resource.id,
                work_package_id=package.id,
                start_at=person.get("start_at", datetime(2099, 1, 5, 10, tzinfo=UTC)),
                end_at=person.get("end_at", datetime(2099, 1, 5, 12, tzinfo=UTC)),
            )
        session.add(booking)
        bookings.append(booking)

    await session.commit()
    return package, bookings


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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Aggregate unmet coverage counts skill attributes but does not apply "
        "qualification date bounds or minimum level (issue #137)."
    ),
)
@pytest.mark.parametrize(
    ("kind", "details"),
    [
        (ResourceType.personal, {"level": 4, "valid_until": DAY - timedelta(days=1)}),
        (ResourceType.personal, {"level": 2}),
        (ResourceType.personal, {"level": None}),
        (ResourceType.personal, {"level": 4, "valid_from": DAY + timedelta(days=1)}),
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
        "expired-machine",
    ],
)
async def test_unqualified_resource_must_not_cover_requirement(
    db_session, kind, details
):
    """The mismatch checker rejects these bookings; aggregate coverage should too."""
    package, bookings = await _seed_case(
        db_session, kind=kind, minimum_level=3, people=[details]
    )
    assert await _mismatches(db_session, package, bookings) == {bookings[0].id}
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Aggregate headcount treats non-overlapping personal bookings as "
        "simultaneous work-package staffing (issue #137 / #139)."
    ),
)
async def test_staggered_people_do_not_cover_two_person_crew(db_session):
    """Two people on disjoint days cannot staff a two-person crew together."""
    package, bookings = await _seed_case(
        db_session,
        quantity=2,
        people=[
            {"start_date": DAY, "end_date": DAY},
            {"start_date": DAY + timedelta(days=1), "end_date": LAST_DAY},
        ],
    )
    assert await _mismatches(db_session, package, bookings) == set()
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert len(unmet) == 1
    assert unmet[0].gap >= 1
