"""Synthetic people/machine/qualification reference cases on real PostgreSQL.

The services intentionally answer different questions. These tests assert each
answer, including read-after-write reconciliation, without inventing a second
feasibility engine or claiming minute-level personnel presence.
"""

import logging
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.absence import Absence, AbsenceReason
from app.models.assignment import Assignment
from app.models.calendar import (
    Holiday,
    InfrastructureAvailabilityWindow,
    ResourceWorkProfile,
    WorkWeekProfile,
)
from app.models.conflict import Conflict, ConflictAssignment, ConflictCause
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.skill import (
    InfrastructureResourceSkill,
    PersonalResourceSkill,
    Skill,
    SkillAttribute,
)
from app.models.work_package_requirement import RequirementMode, WorkPackageRequirement
from app.services.capacity_service import CapacityService
from app.services.conflict_refresh import refresh_after_commit, refresh_resources
from app.services.conflict_service import ConflictService
from app.services.skill_mismatch import detect_mismatches
from app.services.time_zone import local_wall_time_to_utc, planning_zone
from app.services.unmet_requirements_service import get_unmet_requirements
from tests.test_requirement_coverage_audit import _seed_case
from tests.test_utc_migration_postgres import legacy_database, migrate  # noqa: F401

MONDAY = date(2099, 1, 5)
WEDNESDAY = MONDAY + timedelta(days=2)


def _clock(day, hour):
    return local_wall_time_to_utc(datetime.combine(day, time(hour)), planning_zone())


@pytest_asyncio.fixture
async def combined_database(legacy_database):
    url, engine = legacy_database
    migration = await migrate(url, "head")
    assert migration.returncode == 0, migration.stderr
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session, engine


async def _seed_plan(session, *, windows=True):
    # Extend the existing personnel fixture rather than maintain a parallel seed.
    package, crew_bookings = await _seed_case(
        session,
        quantity=2,
        minimum_level=3,
        people=[{"level": 3, "valid_from": MONDAY, "valid_until": WEDNESDAY}] * 2,
    )
    assert (package.start_date, package.end_date) == (MONDAY, WEDNESDAY)
    people_by_id = {
        p.id: p
        for p in (
            await session.scalars(
                select(PersonalResource).where(
                    PersonalResource.id.in_([b.resource_id for b in crew_bookings])
                )
            )
        ).all()
    }
    people = [people_by_id[b.resource_id] for b in crew_bookings]
    qualifications = {
        q.resource_id: q
        for q in (
            await session.scalars(
                select(PersonalResourceSkill).where(
                    PersonalResourceSkill.resource_id.in_(people_by_id)
                )
            )
        ).all()
    }
    crew_qualifications = [qualifications[p.id] for p in people]
    crew_requirement = (
        await session.scalars(
            select(WorkPackageRequirement).where(
                WorkPackageRequirement.work_package_id == package.id
            )
        )
    ).one()
    profile = await session.scalar(
        select(WorkWeekProfile).where(WorkWeekProfile.is_default)
    )
    for weekday in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        setattr(profile, weekday + "_minutes", 480)
    profile.saturday_minutes = profile.sunday_minutes = 0
    site = Site(name="Fictional workshop")
    machine_group = ResourceGroup(
        name="Fictional machines", resource_type=ResourceType.infrastructure
    )
    machine_skill = Skill(
        name="Fictional lifting capability", resource_type="infrastructure"
    )
    session.add_all([site, machine_group, machine_skill])
    await session.flush()
    for person in people:
        person.site_id = site.id
    machine = InfrastructureResource(
        name="Fictional crane", group_id=machine_group.id, site_id=site.id
    )
    machine_attribute = SkillAttribute(
        name="Fictional assessed lifting", skill_id=machine_skill.id
    )
    session.add_all([machine, machine_attribute])
    await session.flush()
    machine_qualification = InfrastructureResourceSkill(
        resource_id=machine.id,
        skill_attribute_id=machine_attribute.id,
        level=3,
        valid_from=MONDAY,
        valid_until=WEDNESDAY,
    )
    machine_requirement = WorkPackageRequirement(
        work_package_id=package.id,
        skill_id=machine_skill.id,
        skill_attribute_id=machine_attribute.id,
        quantity=1,
        min_level=2,
    )
    machine_booking = Assignment(
        resource_type=ResourceType.infrastructure,
        resource_id=machine.id,
        work_package_id=package.id,
        start_at=_clock(MONDAY, 22),
        end_at=_clock(MONDAY + timedelta(days=1), 2),
    )
    session.add_all([machine_qualification, machine_requirement, machine_booking])
    if windows:
        session.add(
            InfrastructureAvailabilityWindow(
                resource_id=machine.id, weekday=0, start_time=time(22), end_time=time(6)
            )
        )
    await session.commit()
    return SimpleNamespace(
        package=package,
        people=people,
        machine=machine,
        site=site,
        crew_qualifications=crew_qualifications,
        machine_qualification=machine_qualification,
        crew_requirement=crew_requirement,
        crew_bookings=crew_bookings,
        machine_booking=machine_booking,
        resource_ids={person.id for person in people} | {machine.id},
    )


async def _unmet(session, plan):
    return {
        row.resource_type: row
        for row in await get_unmet_requirements(session)
        if row.work_package_id == plan.package.id
    }


async def _mismatches(session, plan):
    assignments = (
        await session.scalars(
            select(Assignment).where(Assignment.work_package_id == plan.package.id)
        )
    ).all()
    return await detect_mismatches(
        session,
        [(a.id, a.resource_id, a.work_package_id) for a in assignments],
        {plan.package.id},
        plan.resource_ids,
    )


async def _stored(session, plan):
    return list(
        (
            await session.scalars(
                select(Conflict).where(Conflict.resource_id.in_(plan.resource_ids))
            )
        ).all()
    )


async def _add_machine_overlap(session, plan):
    extra = Assignment(
        resource_type=ResourceType.infrastructure,
        resource_id=plan.machine.id,
        work_package_id=plan.package.id,
        start_at=_clock(MONDAY, 21),
        end_at=_clock(MONDAY + timedelta(days=1), 1),
    )
    session.add(extra)
    await session.commit()
    return extra


def _repair_machine_booking(extra):
    extra.start_at = _clock(MONDAY + timedelta(days=1), 2)
    extra.end_at = _clock(MONDAY + timedelta(days=1), 6)


@pytest.mark.parametrize(
    "windows", [True, False], ids=["night-window", "unrestricted-default"]
)
async def test_qualified_crew_and_midnight_machine_pass_the_available_checks(
    combined_database, windows
):
    session, _ = combined_database
    plan = await _seed_plan(session, windows=windows)
    assert await _unmet(session, plan) == {}
    assert await _mismatches(session, plan) == set()
    assert await refresh_resources(session, plan.resource_ids) == 0
    assert await _stored(session, plan) == []
    for person in plan.people:
        capacity = CapacityService(session)
        assert await capacity.calculate_available_capacity(person.id, MONDAY) == 100
        assert await capacity.get_assigned_percent(person.id, MONDAY) == 100
    # Date/percentage personnel bookings cannot prove presence during the night shift.


async def test_invalid_qualifications_leave_gaps_without_inventing_capacity_conflicts(
    combined_database,
):
    session, _ = combined_database
    plan = await _seed_plan(session)
    plan.crew_qualifications[0].level = 2
    plan.machine_qualification.valid_from = MONDAY - timedelta(days=30)
    plan.machine_qualification.valid_until = MONDAY - timedelta(days=1)
    await session.commit()
    unmet = await _unmet(session, plan)
    assert (unmet["personal"].assigned_quantity, unmet["personal"].gap) == (1, 1)
    assert (unmet["infrastructure"].assigned_quantity, unmet["infrastructure"].gap) == (
        0,
        1,
    )
    assert await _mismatches(session, plan) == {
        plan.crew_bookings[0].id,
        plan.machine_booking.id,
    }
    assert await refresh_resources(session, plan.resource_ids) == 0
    assert await _stored(session, plan) == []


async def test_part_time_and_absence_block_capacity_despite_qualified_bookings(
    combined_database,
):
    session, _ = combined_database
    plan = await _seed_plan(session)
    part_time = WorkWeekProfile(name="Fictional half Monday", monday_minutes=240)
    session.add(part_time)
    await session.flush()
    session.add(
        ResourceWorkProfile(
            resource_id=plan.people[0].id, profile_id=part_time.id, valid_from=MONDAY
        )
    )
    session.add(
        Absence(
            resource_id=plan.people[1].id,
            resource_type=ResourceType.personal,
            reason=AbsenceReason.planned,
            start_date=MONDAY + timedelta(days=1),
            end_date=MONDAY + timedelta(days=1),
            allocation_percent=100,
        )
    )
    await session.commit()
    assert await _unmet(session, plan) == {}
    assert await _mismatches(session, plan) == set()
    assert await refresh_resources(session, plan.resource_ids) == 2
    conflicts = await _stored(session, plan)
    assert {
        (
            c.resource_id,
            c.cause,
            c.start_date,
            c.end_date,
            c.total_assigned_percent,
            c.available_percent,
        )
        for c in conflicts
    } == {
        (plan.people[0].id, ConflictCause.over_allocation, MONDAY, MONDAY, 100, 50),
        (
            plan.people[1].id,
            ConflictCause.over_allocation,
            MONDAY + timedelta(days=1),
            MONDAY + timedelta(days=1),
            100,
            0,
        ),
    }


async def test_site_closure_is_visible_supply_loss_even_without_a_stored_conflict(
    combined_database,
):
    session, _ = combined_database
    plan = await _seed_plan(session)
    session.add(
        Holiday(
            site_id=plan.site.id,
            day=WEDNESDAY,
            name="Fictional local shutdown",
            working_minutes=0,
        )
    )
    await session.commit()
    assert await _unmet(session, plan) == {}
    assert await _mismatches(session, plan) == set()
    assert await refresh_resources(session, plan.resource_ids) == 0
    assert await _stored(session, plan) == []
    for person in plan.people:
        capacity = CapacityService(session)
        assert await capacity.calculate_available_capacity(person.id, WEDNESDAY) == 0
        assert await capacity.get_assigned_percent(person.id, WEDNESDAY) == 0
    # Coverage counts commitments on standard-profile workdays, not site-aware supply.


async def test_headcount_and_effort_fte_remain_distinct_with_the_same_machine(
    combined_database,
):
    session, _ = combined_database
    plan = await _seed_plan(session)
    for booking in plan.crew_bookings:
        booking.allocation_percent = 50
    await session.commit()
    assert await _mismatches(session, plan) == set()
    unmet = await _unmet(session, plan)
    assert set(unmet) == {"personal"}
    assert (unmet["personal"].assigned_quantity, unmet["personal"].gap) == (0, 2)
    assert await refresh_resources(session, plan.resource_ids) == 0
    plan.crew_requirement.requirement_mode = RequirementMode.effort_fte
    plan.crew_requirement.quantity = 1
    await session.commit()
    assert await _unmet(session, plan) == {}
    assert await _stored(session, plan) == []


async def test_overlap_window_preview_and_stored_results_reconcile_after_edit(
    combined_database,
):
    session, engine = combined_database
    plan = await _seed_plan(session)
    extra = await _add_machine_overlap(session, plan)
    preview = await ConflictService(session).calculate_periods(plan.machine.id)
    assert {p.cause for p in preview} == {
        ConflictCause.booking_overlap,
        ConflictCause.outside_availability,
    }
    overlap = next(p for p in preview if p.cause == ConflictCause.booking_overlap)
    assert (overlap.start_date, overlap.end_date) == (
        MONDAY,
        MONDAY + timedelta(days=1),
    )
    assert set(overlap.assignment_ids) == {plan.machine_booking.id, extra.id}
    assert (overlap.total_assigned_percent, overlap.available_percent) == (200, 100)
    outside = next(p for p in preview if p.cause == ConflictCause.outside_availability)
    assert (outside.start_date, outside.end_date) == (MONDAY, MONDAY)
    assert outside.assignment_ids == [extra.id]
    assert (outside.total_assigned_percent, outside.available_percent) == (50, 37.5)
    assert await _unmet(session, plan) == {}
    assert await _mismatches(session, plan) == set()
    assert await refresh_resources(session, plan.resource_ids) == 2
    stored = await _stored(session, plan)
    links = (
        await session.scalars(
            select(ConflictAssignment).where(
                ConflictAssignment.conflict_id.in_([c.id for c in stored])
            )
        )
    ).all()

    def signature(conflict, ids):
        return (
            conflict.cause,
            conflict.start_date,
            conflict.end_date,
            conflict.total_assigned_percent,
            conflict.available_percent,
            frozenset(ids),
        )

    assert {
        signature(c, [link.assignment_id for link in links if link.conflict_id == c.id])
        for c in stored
    } == {signature(p, p.assignment_ids) for p in preview}
    old_ids = {c.id for c in stored}
    assert await refresh_resources(session, plan.resource_ids) == 2
    assert {c.id for c in await _stored(session, plan)} == old_ids
    _repair_machine_booking(extra)
    await session.commit()
    assert await ConflictService(session).calculate_periods(plan.machine.id) == []
    async with AsyncSession(engine) as reader:
        assert {c.id for c in await _stored(reader, plan)} == old_ids
    assert await refresh_resources(session, plan.resource_ids) == 0
    async with AsyncSession(engine) as reader:
        assert await _stored(reader, plan) == []
        assert (
            await reader.scalars(
                select(ConflictAssignment).where(
                    ConflictAssignment.conflict_id.in_(old_ids)
                )
            )
        ).all() == []


async def test_failed_derived_refresh_preserves_committed_input_and_previous_conflicts(
    combined_database, monkeypatch, caplog
):
    session, engine = combined_database
    plan = await _seed_plan(session)
    extra = await _add_machine_overlap(session, plan)
    await refresh_resources(session, plan.resource_ids)
    old_ids = {c.id for c in await _stored(session, plan)}
    assert len(old_ids) == 2
    _repair_machine_booking(extra)
    await session.commit()

    async def fail_saving(self, periods):
        raise RuntimeError("synthetic derived-save failure")

    with monkeypatch.context() as patch:
        patch.setattr(ConflictService, "_save_conflict_periods", fail_saving)
        with caplog.at_level(logging.ERROR):
            await refresh_after_commit(session, {plan.machine.id})
    assert "Conflict refresh failed after committed write" in caplog.text
    async with AsyncSession(engine) as reader:
        saved = await reader.get(Assignment, extra.id)
        assert saved.start_at == _clock(MONDAY + timedelta(days=1), 2)
        assert saved.end_at == _clock(MONDAY + timedelta(days=1), 6)
        assert {c.id for c in await _stored(reader, plan)} == old_ids
    assert await refresh_resources(session, plan.resource_ids) == 0
    assert await _stored(session, plan) == []


@pytest.mark.parametrize(
    "mode,after_duplicate",
    [
        (RequirementMode.headcount, 1),
        (RequirementMode.effort_fte, 1.5),
    ],
)
async def test_disjoint_crew_and_repeated_person_bookings_keep_their_units(
    combined_database, mode, after_duplicate
):
    session, _ = combined_database
    plan = await _seed_plan(session)
    plan.crew_requirement.requirement_mode = mode
    plan.crew_bookings[0].end_date = MONDAY
    plan.crew_bookings[1].start_date = MONDAY + timedelta(days=1)
    await session.commit()
    unmet = await _unmet(session, plan)
    assert set(unmet) == {"personal"}
    assert (unmet["personal"].assigned_quantity, unmet["personal"].gap) == (1, 1)
    assert await _mismatches(session, plan) == set()
    assert await refresh_resources(session, plan.resource_ids) == 0
    duplicate = Assignment(
        resource_id=plan.people[0].id,
        resource_type=ResourceType.personal,
        work_package_id=plan.package.id,
        start_date=MONDAY,
        end_date=WEDNESDAY,
        allocation_percent=50,
    )
    session.add(duplicate)
    await session.commit()
    unmet = await _unmet(session, plan)
    assert set(unmet) == {"personal"}
    # Only one body meets the threshold each day. Divisible effort sums to 1.5.
    assert (unmet["personal"].assigned_quantity, unmet["personal"].gap) == (
        after_duplicate,
        2 - after_duplicate,
    )
    assert await refresh_resources(session, plan.resource_ids) == 1
    conflict = (await _stored(session, plan))[0]
    assert (
        conflict.resource_id,
        conflict.cause,
        conflict.total_assigned_percent,
        conflict.available_percent,
    ) == (plan.people[0].id, ConflictCause.over_allocation, 150, 100)
