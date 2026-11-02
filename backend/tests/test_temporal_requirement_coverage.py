"""Daily personnel commitments on the standard profile's workdays."""

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from app.models.absence import Absence, AbsenceReason
from app.models.assignment import Assignment
from app.models.calendar import ResourceWorkProfile, WorkWeekProfile
from app.models.project import Project
from app.models.resource import ResourceType
from app.models.work_package_requirement import RequirementMode, WorkPackageRequirement
from app.services.capacity_service import CapacityService
from app.services.unmet_requirements_service import (
    _personal_workday_coverage,
    compute_coverage,
    get_unmet_requirements,
)
from tests.test_requirement_coverage_audit import DAY, _seed_case


async def _case(
    session,
    people,
    *,
    mode=RequirementMode.headcount,
    quantity=1,
    start=DAY,
    end=DAY + timedelta(days=2),
    threshold=100,
):
    package, bookings = await _seed_case(
        session, people=people, mode=mode, quantity=quantity
    )
    package.start_date, package.end_date = start, end
    project = await session.get(Project, package.project_id)
    project.start_date, project.end_date = start, end
    requirement = (await session.execute(select(WorkPackageRequirement))).scalar_one()
    requirement.min_allocation_percent = threshold
    await session.commit()
    return package, bookings


@pytest.mark.parametrize(
    "mode,allocation,quantity,coverage",
    [
        (RequirementMode.headcount, 100, 2, 1),
        (RequirementMode.effort_fte, 50, 1, 0.5),
    ],
)
async def test_disjoint_people_cannot_be_added_across_days(
    db_session, mode, allocation, quantity, coverage
):
    await _case(
        db_session,
        [
            {"start_date": DAY, "end_date": DAY, "allocation": allocation},
            {"start_date": DAY + timedelta(days=1), "allocation": allocation},
        ],
        mode=mode,
        quantity=quantity,
    )
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert len(unmet) == 1
    assert unmet[0].assigned_quantity == coverage
    assert unmet[0].gap == quantity - coverage


async def test_qualified_crew_can_rotate_without_a_daily_gap(db_session):
    await _case(
        db_session,
        [
            {"start_date": DAY, "end_date": DAY},
            {"start_date": DAY + timedelta(days=1)},
        ],
    )
    assert await get_unmet_requirements(db_session, resource_type="personal") == []


@pytest.mark.parametrize(
    "people",
    [
        [{"start_date": DAY, "end_date": DAY}, {"start_date": DAY + timedelta(days=2)}],
        [{"start_date": DAY + timedelta(days=3), "end_date": DAY + timedelta(days=4)}],
        [{"start_date": DAY - timedelta(days=2), "end_date": DAY - timedelta(days=1)}],
    ],
)
async def test_unstaffed_workdays_and_outside_bookings_leave_a_gap(db_session, people):
    await _case(db_session, people)
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert len(unmet) == 1
    assert unmet[0].assigned_quantity == 0
    assert unmet[0].gap == 1


@pytest.mark.parametrize("saturday_minutes,expected_gap", [(0, False), (480, True)])
async def test_standard_profile_controls_required_weekdays(
    db_session, saturday_minutes, expected_gap
):
    next_monday = DAY + timedelta(days=7)
    await _case(
        db_session,
        [
            {"end_date": DAY + timedelta(days=4)},
            {"start_date": next_monday, "end_date": next_monday},
        ],
        end=next_monday,
    )
    profile = (
        await db_session.execute(
            select(WorkWeekProfile).where(WorkWeekProfile.is_default)
        )
    ).scalar_one()
    profile.saturday_minutes = saturday_minutes
    await db_session.commit()
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert bool(unmet) == expected_gap
    if expected_gap:
        assert unmet[0].assigned_quantity == 0


async def test_weekend_only_package_has_no_standard_profile_staffing_demand(db_session):
    await _case(
        db_session, [], start=DAY + timedelta(days=5), end=DAY + timedelta(days=6)
    )
    assert await get_unmet_requirements(db_session, resource_type="personal") == []


async def test_missing_standard_profile_does_not_claim_personnel_coverage(db_session):
    await _case(db_session, [{}])
    profile = (await db_session.execute(select(WorkWeekProfile))).scalar_one()
    await db_session.delete(profile)
    await db_session.commit()
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert len(unmet) == 1
    assert unmet[0].assigned_quantity == 0


@pytest.mark.parametrize(
    "mode,quantity,expected",
    [
        (RequirementMode.headcount, 2, 1),
        (RequirementMode.effort_fte, 2, 1.5),
    ],
)
async def test_same_person_bookings_preserve_mode_arithmetic(
    db_session, mode, quantity, expected
):
    package, bookings = await _case(db_session, [{}], mode=mode, quantity=quantity)
    db_session.add(
        Assignment(
            resource_type=ResourceType.personal,
            resource_id=bookings[0].resource_id,
            work_package_id=package.id,
            start_date=DAY,
            end_date=DAY + timedelta(days=2),
            allocation_percent=50,
        )
    )
    await db_session.commit()
    unmet = await get_unmet_requirements(db_session, resource_type="personal")
    assert len(unmet) == 1
    assert unmet[0].assigned_quantity == expected


@pytest.mark.parametrize("absence", [False, True])
async def test_commitment_coverage_does_not_hide_individual_capacity_shortfalls(
    db_session, absence
):
    _, bookings = await _case(db_session, [{}])
    resource = bookings[0].resource_id
    if absence:
        db_session.add(
            Absence(
                resource_type=ResourceType.personal,
                resource_id=resource,
                reason=AbsenceReason.planned,
                start_date=DAY,
                end_date=DAY,
                allocation_percent=100,
            )
        )
    else:
        part_time = WorkWeekProfile(name="Half time", monday_minutes=240)
        db_session.add(part_time)
        await db_session.flush()
        db_session.add(
            ResourceWorkProfile(
                resource_id=resource, profile_id=part_time.id, valid_from=DAY
            )
        )
    await db_session.commit()
    assert await get_unmet_requirements(db_session, resource_type="personal") == []
    capacity = CapacityService(db_session)
    assert await capacity.calculate_available_capacity(resource, DAY) == (
        0 if absence else 50
    )
    assert await capacity.get_assigned_percent(resource, DAY) == 100


@settings(max_examples=70, deadline=None)
@given(
    rows=st.lists(
        st.tuples(
            st.integers(0, 3),
            st.integers(-2, 12),
            st.integers(0, 6),
            st.sampled_from([25.0, 50.0, 100.0]),
        ),
        max_size=12,
    ),
    weekdays=st.sets(st.integers(0, 6)),
    mode=st.sampled_from(list(RequirementMode)),
)
def test_boundary_sweep_matches_an_independent_day_by_day_oracle(rows, weekdays, mode):
    from uuid import UUID

    bookings = [
        Assignment(
            resource_type=ResourceType.personal,
            resource_id=UUID(int=person + 1),
            work_package_id=UUID(int=100),
            start_date=DAY + timedelta(days=offset),
            end_date=DAY + timedelta(days=offset + length),
            allocation_percent=allocation,
        )
        for person, offset, length, allocation in rows
    ]
    end = DAY + timedelta(days=9)
    daily = []
    for offset in range(10):
        day = DAY + timedelta(days=offset)
        if day.weekday() in weekdays:
            daily.append(
                compute_coverage(
                    mode,
                    50,
                    [
                        (b.resource_id, b.allocation_percent)
                        for b in bookings
                        if b.start_date <= day <= b.end_date
                    ],
                )
            )
    assert _personal_workday_coverage(mode, 50, bookings, DAY, end, weekdays) == (
        min(daily) if daily else None
    )


def test_long_span_and_maximum_date_do_not_require_a_daily_loop():
    from uuid import UUID

    booking = Assignment(
        resource_type=ResourceType.personal,
        resource_id=UUID(int=1),
        work_package_id=UUID(int=100),
        start_date=DAY,
        end_date=date.max,
        allocation_percent=100,
    )
    assert (
        _personal_workday_coverage(
            RequirementMode.headcount, 100, [booking], DAY, date.max, {0, 1, 2, 3, 4}
        )
        == 1
    )
