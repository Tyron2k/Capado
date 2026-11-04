"""Read-only package verdicts must retain blockers and expose missing evidence."""

from datetime import timedelta

import pytest
from sqlalchemy import event, select

from app.exceptions import NotFoundError
from app.models.assignment import Assignment
from app.models.calendar import Holiday, WorkWeekProfile
from app.models.conflict import Conflict
from app.models.project import WorkPackage
from app.models.resource import PersonalResource, ResourceType
from app.models.skill import PersonalResourceSkill
from app.services.planning_readiness import (
    get_work_package_readiness,
    list_planning_work_packages,
)
from tests.planning_reference import MONDAY, WEDNESDAY, _clock, _seed_plan


async def test_positive_checks_do_not_claim_machine_shift_personnel_presence(
    db_session,
):
    plan = await _seed_plan(db_session)
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert (
        result.personnel_status
        == result.infrastructure_status
        == result.qualification_status
        == "covered"
    )
    assert result.status == "covered"
    assert result.limits == ["personnel_clock_times", "infrastructure_continuity"]
    assert result.conflicts == result.supply_gaps == result.unmet_requirements == []
    assert result.personnel_requirements == result.infrastructure_requirements == 1
    assert len(result.assignments) == 3
    assert result.checked_at.utcoffset().total_seconds() == 0
    assert not db_session.new and not db_session.dirty
    assert (await db_session.scalars(select(Conflict))).all() == []


async def test_missing_personnel_is_not_hidden_by_precision_limits(db_session):
    plan = await _seed_plan(db_session)
    plan.crew_bookings[1].start_date = MONDAY + timedelta(days=1)
    await db_session.commit()
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert result.status == result.personnel_status == "missing_requirements"
    assert result.infrastructure_status == "covered"
    assert [
        (r.resource_type, r.assigned_quantity, r.gap) for r in result.unmet_requirements
    ] == [("personal", 1, 1)]


async def test_qualification_failure_remains_visible_alongside_coverage_gaps(
    db_session,
):
    plan = await _seed_plan(db_session)
    plan.crew_qualifications[0].level = 2
    await db_session.commit()
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert result.status == result.qualification_status == "conflicting"
    assert result.personnel_status == "missing_requirements"
    assert [a.id for a in result.assignments if a.skill_mismatch] == [
        plan.crew_bookings[0].id
    ]
    assert result.conflicts == []


async def test_zero_site_supply_is_not_a_positive_capacity_verdict(db_session):
    plan = await _seed_plan(db_session)
    db_session.add(
        Holiday(
            site_id=plan.site.id,
            day=WEDNESDAY,
            name="Fictional closure",
            working_minutes=0,
        )
    )
    await db_session.commit()
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert result.status == result.personnel_status == "not_fully_assessable"
    assert result.unmet_requirements == result.conflicts == []
    assert {(g.resource_id, g.day) for g in result.supply_gaps} == {
        (p.id, WEDNESDAY) for p in plan.people
    }


async def test_missing_standard_profile_is_unknown_not_a_proven_staffing_gap(
    db_session,
):
    plan = await _seed_plan(db_session)
    profile = await db_session.scalar(
        select(WorkWeekProfile).where(WorkWeekProfile.is_default)
    )
    await db_session.delete(profile)
    await db_session.commit()
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert result.personnel_status == result.status == "not_fully_assessable"
    assert "no_standard_profile" in result.limits
    assert "missing_calendar" in result.limits


async def test_unrestricted_machine_default_does_not_invent_a_missing_window(
    db_session,
):
    plan = await _seed_plan(db_session, windows=False)
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert result.infrastructure_status == "covered"
    assert result.conflicts == []


async def test_live_machine_check_names_both_causes_without_persisting_them(db_session):
    plan = await _seed_plan(db_session)
    extra = Assignment(
        resource_id=plan.machine.id,
        resource_type=ResourceType.infrastructure,
        work_package_id=plan.package.id,
        start_at=_clock(MONDAY, 21),
        end_at=_clock(MONDAY + timedelta(days=1), 1),
    )
    db_session.add(extra)
    await db_session.commit()
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert result.status == result.infrastructure_status == "conflicting"
    by_cause = {c.cause: c for c in result.conflicts}
    assert set(by_cause) == {"booking_overlap", "outside_availability"}
    assert set(by_cause["booking_overlap"].assignment_ids) == {
        plan.machine_booking.id,
        extra.id,
    }
    assert by_cause["outside_availability"].assignment_ids == [extra.id]
    assert all(c.resource_name == plan.machine.name for c in result.conflicts)
    assert not db_session.new and not db_session.dirty
    assert (await db_session.scalars(select(Conflict))).all() == []


async def test_no_requirements_does_not_mean_a_validated_plan(db_session):
    plan = await _seed_plan(db_session)
    empty = WorkPackage(
        name="Unspecified demand",
        project_id=plan.package.project_id,
        start_date=MONDAY,
        end_date=WEDNESDAY,
    )
    db_session.add(empty)
    await db_session.commit()
    result = await get_work_package_readiness(db_session, empty.id)
    assert (
        result.status
        == result.personnel_status
        == result.infrastructure_status
        == result.qualification_status
        == "not_fully_assessable"
    )
    assert set(result.limits) == {
        "no_personnel_requirements",
        "no_infrastructure_requirements",
    }
    assert result.assignments == []


async def test_long_package_retains_known_gaps_but_does_not_run_unbounded_capacity_check(
    db_session,
):
    plan = await _seed_plan(db_session)
    plan.package.end_date = MONDAY + timedelta(days=10000)
    await db_session.commit()
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert result.personnel_status == result.status == "missing_requirements"
    assert result.infrastructure_status == "not_fully_assessable"
    assert "capacity_window_limit" in result.limits


async def test_current_picker_includes_problem_free_packages_but_not_finished_or_past(
    db_session,
):
    plan = await _seed_plan(db_session)
    db_session.add(
        WorkPackage(
            name="Old",
            project_id=plan.package.project_id,
            start_date=MONDAY.replace(year=2000),
            end_date=WEDNESDAY.replace(year=2000),
        )
    )
    await db_session.commit()
    packages = await list_planning_work_packages(db_session)
    assert [p.id for p in packages] == [plan.package.id]
    assert packages[0].project_name == "Fixture project"
    plan.package.completed_at = result_time = (
        await get_work_package_readiness(db_session, plan.package.id)
    ).checked_at
    await db_session.commit()
    assert result_time is not None
    assert await list_planning_work_packages(db_session) == []
    with pytest.raises(NotFoundError):
        await get_work_package_readiness(db_session, plan.package.id)


async def test_query_count_does_not_grow_with_resource_count(db_session):
    plan = await _seed_plan(db_session)
    engine = db_session.bind.sync_engine
    queries = []

    def count_sql(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", count_sql)
    try:
        await get_work_package_readiness(db_session, plan.package.id)
        initial = len(queries)
        for n in range(20):
            person = PersonalResource(
                name=f"Extra {n}", group_id=plan.people[0].group_id
            )
            db_session.add(person)
            await db_session.flush()
            db_session.add_all(
                [
                    PersonalResourceSkill(
                        resource_id=person.id,
                        skill_attribute_id=plan.crew_qualifications[
                            0
                        ].skill_attribute_id,
                        level=3,
                    ),
                    Assignment(
                        resource_id=person.id,
                        resource_type=ResourceType.personal,
                        work_package_id=plan.package.id,
                        start_date=MONDAY,
                        end_date=WEDNESDAY,
                        allocation_percent=100,
                    ),
                ]
            )
        await db_session.commit()
        queries.clear()
        result = await get_work_package_readiness(db_session, plan.package.id)
        assert len(result.assignments) == 23
        assert len(queries) == initial
    finally:
        event.remove(engine, "before_cursor_execute", count_sql)


async def test_conflict_check_timestamp_is_a_valid_utc_instant(db_session):
    from datetime import UTC, datetime

    from app.models.scheduled_job_run import JobRunStatus, ScheduledJobRun
    from app.routers.conflicts import get_conflict_check_status

    finished = datetime(2026, 11, 3, 12, tzinfo=UTC)
    db_session.add(
        ScheduledJobRun(
            job_name="refresh-conflicts",
            started_at=finished - timedelta(seconds=1),
            finished_at=finished,
            status=JobRunStatus.succeeded,
        )
    )
    await db_session.commit()
    result = await get_conflict_check_status(session=db_session, _current_user=None)
    assert result["last_checked_at"] == "2026-11-03T12:00:00Z"
    assert datetime.fromisoformat(result["last_checked_at"]) == finished


async def test_no_bookings_never_claim_checked_qualifications(db_session):
    plan = await _seed_plan(db_session)
    for booking in [*plan.crew_bookings, plan.machine_booking]:
        await db_session.delete(booking)
    await db_session.commit()
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert result.qualification_status == "not_fully_assessable"
    assert result.status == "missing_requirements"


async def test_personnel_only_can_pass_defined_scope_without_inventing_equipment_demand(
    db_session,
):
    from app.models.skill import Skill
    from app.models.work_package_requirement import WorkPackageRequirement

    plan = await _seed_plan(db_session)
    requirement = await db_session.scalar(
        select(WorkPackageRequirement)
        .join(Skill)
        .where(
            WorkPackageRequirement.work_package_id == plan.package.id,
            Skill.resource_type == "infrastructure",
        )
    )
    await db_session.delete(requirement)
    await db_session.delete(plan.machine_booking)
    await db_session.commit()
    result = await get_work_package_readiness(db_session, plan.package.id)
    assert result.status == result.personnel_status == "covered"
    assert result.infrastructure_status == "not_fully_assessable"
    assert "no_infrastructure_requirements" in result.limits
