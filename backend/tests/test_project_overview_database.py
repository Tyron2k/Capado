"""Scoped overview queries preserve resource-wide utilization and calendar semantics."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.absence import Absence
from app.models.assignment import Assignment
from app.models.calendar import Holiday, ResourceWorkProfile, WorkWeekProfile
from app.models.conflict import Conflict, ConflictAssignment
from app.models.project import Project, WorkPackage, WorkPackageDependency
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.services.capacity_service import CapacityService
from app.services.project_overview_service import ProjectOverviewService
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401


async def test_overview_keeps_external_bookings_calendars_and_distinct_conflicts(
    db_session,
):
    start, end = date(2026, 1, 5), date(2026, 1, 9)
    own = Project(name="Own", start_date=start, end_date=end)
    other = Project(name="Other", start_date=start, end_date=end)
    group = ResourceGroup(name="People")
    infra_group = ResourceGroup(name="Machines", resource_type="infrastructure")
    site = Site(name="Plant")
    standard = WorkWeekProfile(name="Standard", is_default=True)
    part_time = WorkWeekProfile(
        name="Part-time",
        monday_minutes=240,
        tuesday_minutes=240,
        wednesday_minutes=240,
        thursday_minutes=240,
        friday_minutes=240,
    )
    db_session.add_all([own, other, group, infra_group, site, standard, part_time])
    await db_session.flush()
    person = PersonalResource(
        name="Inactive but historically booked",
        group_id=group.id,
        site_id=site.id,
        is_active=False,
    )
    machine = InfrastructureResource(name="Machine", group_id=infra_group.id)
    wp = WorkPackage(
        name="Own package",
        project_id=own.id,
        start_date=start,
        end_date=end,
        lead_time_working_days=8,
    )
    foreign = WorkPackage(
        name="Foreign predecessor", project_id=other.id, start_date=start, end_date=end
    )
    db_session.add_all([person, machine, wp, foreign])
    await db_session.flush()
    bookings = [
        Assignment(
            resource_id=person.id,
            resource_type="personal",
            work_package_id=package.id,
            start_date=start,
            end_date=end,
            allocation_percent=50,
        )
        for package in (wp, foreign)
    ]
    infra = Assignment(
        resource_id=machine.id,
        resource_type="infrastructure",
        work_package_id=wp.id,
        start_at=datetime(2026, 1, 5, 8, tzinfo=UTC),
        end_at=datetime(2026, 1, 5, 16, tzinfo=UTC),
    )
    orphan = Assignment(
        resource_id=uuid4(),
        resource_type="personal",
        work_package_id=wp.id,
        start_date=start,
        end_date=end,
        allocation_percent=100,
    )
    conflict = Conflict(
        resource_id=person.id,
        resource_type="personal",
        start_date=start,
        end_date=end,
        total_assigned_percent=100,
        available_percent=50,
    )
    db_session.add_all(
        [
            *bookings,
            infra,
            orphan,
            conflict,
            ResourceWorkProfile(
                resource_id=person.id, profile_id=part_time.id, valid_from=start
            ),
            Holiday(site_id=site.id, day=start + timedelta(days=1), name="Closed"),
            Absence(
                resource_id=person.id,
                resource_type="personal",
                reason="planned",
                start_date=start + timedelta(days=2),
                end_date=start + timedelta(days=2),
            ),
            WorkPackageDependency(predecessor_id=foreign.id, successor_id=wp.id),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            ConflictAssignment(conflict_id=conflict.id, assignment_id=booking.id)
            for booking in (bookings[0], bookings[1], infra)
        ]
    )
    await db_session.commit()

    # Reference uses the existing single-resource path, including foreign bookings.
    reference = []
    for resource in (person, machine):
        weeks = await CapacityService(db_session).get_weekly_utilization(
            resource.id, start, end
        )
        reference.append(
            sum(w.total_assigned for w in weeks)
            / sum(w.total_available for w in weeks)
            * 100
        )
    overview = await ProjectOverviewService(db_session).get_overview(
        [own.id], today=start
    )
    item = overview.projects[0]
    assert item.average_resource_utilization_percent == round(sum(reference) / 2, 1)
    assert (
        item.open_conflict_count == 1
    )  # Two own links to the same persisted conflict.
    assert item.late_work_packages and item.dependency_violations
    assert len(overview.projects) == 1  # The predecessor's project is not added.
    full = await ProjectOverviewService(db_session).get_overview(
        [own.id, other.id], today=start
    )
    assert {p.project_id: p.open_conflict_count for p in full.projects} == {
        own.id: 1,
        other.id: 1,
    }


async def _bounded_query_overview(db_session, project_count):
    start, end = date(2026, 1, 5), date(2026, 1, 9)
    group = ResourceGroup(name="People")
    db_session.add_all([group, WorkWeekProfile(name="Standard", is_default=True)])
    await db_session.flush()
    projects = [
        Project(name=f"Project {i}", start_date=start, end_date=end)
        for i in range(project_count)
    ]
    people = [
        PersonalResource(name=f"Person {i}", group_id=group.id)
        for i in range(project_count)
    ]
    db_session.add_all([*projects, *people])
    await db_session.flush()
    packages = [
        WorkPackage(name=p.name, project_id=p.id, start_date=start, end_date=end)
        for p in projects
    ]
    db_session.add_all(packages)
    await db_session.flush()
    for i, package in enumerate(packages):
        for booking_index, person in enumerate((people[0], people[i])):
            db_session.add(
                Assignment(
                    resource_id=person.id,
                    resource_type="personal",
                    work_package_id=package.id,
                    start_date=start,
                    end_date=end,
                    allocation_percent=25 + booking_index,
                )
            )
    await db_session.commit()
    statements = []

    def record(_conn, _cursor, statement, *_):
        statements.append(statement)

    event.listen(db_session.bind.sync_engine, "before_cursor_execute", record)
    try:
        overview = await ProjectOverviewService(db_session).get_overview(
            [p.id for p in projects], today=start
        )
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", record)
    assert len(overview.projects) == project_count
    assert len(statements) <= 18, (
        f"{project_count} projects triggered {len(statements)} queries"
    )
    assert all(
        "WHERE" in sql
        for sql in statements
        if "FROM assignments" in sql or "FROM conflict_assignments" in sql
    )


async def test_prepared_capacity_reuses_only_covered_resource_and_date_windows(
    db_session,
):
    start, end = date(2026, 1, 5), date(2026, 1, 9)
    group = ResourceGroup(name="People")
    db_session.add_all([group, WorkWeekProfile(name="Default", is_default=True)])
    await db_session.flush()
    people = [PersonalResource(name=name, group_id=group.id) for name in ("One", "Two")]
    db_session.add_all(people)
    await db_session.commit()
    service = CapacityService(db_session)
    prepared = await service.prepare({people[0].id}, start, end)
    assert await service._get_working_time(people[0].id, start, end) is prepared
    assert await service._get_working_time(people[1].id, start, end) is not prepared
    assert (
        await service._get_working_time(people[0].id, start, end + timedelta(days=7))
        is not prepared
    )
    # Fallback reads must not replace the batch snapshot for covered requests.
    assert await service._get_working_time(people[0].id, start, end) is prepared


async def test_shared_resource_utilization_respects_each_projects_date_window(
    db_session,
):
    start = date(2026, 1, 5)
    group = ResourceGroup(name="Shared")
    db_session.add_all([group, WorkWeekProfile(name="Default", is_default=True)])
    await db_session.flush()
    person = PersonalResource(name="Shared person", group_id=group.id)
    projects = [
        Project(
            name=f"Window {i}",
            start_date=start + timedelta(days=i * 7),
            end_date=start + timedelta(days=i * 7 + 4),
        )
        for i in range(2)
    ]
    db_session.add_all([person, *projects])
    await db_session.flush()
    packages = [
        WorkPackage(
            project_id=p.id, name=p.name, start_date=p.start_date, end_date=p.end_date
        )
        for p in projects
    ]
    db_session.add_all(packages)
    await db_session.flush()
    db_session.add_all(
        [
            Assignment(
                resource_id=person.id,
                resource_type="personal",
                work_package_id=wp.id,
                start_date=wp.start_date,
                end_date=wp.end_date,
                allocation_percent=100 if i == 0 else 50,
            )
            for i, wp in enumerate(packages)
        ]
    )
    await db_session.commit()
    overview = await ProjectOverviewService(db_session).get_overview(today=start)
    assert {
        p.project_id: p.average_resource_utilization_percent for p in overview.projects
    } == {projects[0].id: 100, projects[1].id: 50}


@pytest.mark.parametrize("project_count", [1, 5, 15])
async def test_query_count_is_bounded_when_projects_and_resources_grow(
    db_session, project_count
):
    await _bounded_query_overview(db_session, project_count)


async def test_bounded_overview_queries_against_migrated_postgres(resource_database):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        await _bounded_query_overview(session, 15)


@pytest.mark.parametrize("weekday", range(7))
async def test_default_calendar_weekdays_include_weekends(db_session, weekday):
    """Plant lead times follow the actual default week, including working weekends."""
    fields = dict.fromkeys(
        (
            "monday_minutes",
            "tuesday_minutes",
            "wednesday_minutes",
            "thursday_minutes",
            "friday_minutes",
            "saturday_minutes",
            "sunday_minutes",
        ),
        0,
    )
    fields[list(fields)[weekday]] = 480
    profile = WorkWeekProfile(name="One working day", is_default=True, **fields)
    start = date(2026, 1, 5)
    project = Project(
        name="Calendar", start_date=start, end_date=start + timedelta(days=6)
    )
    db_session.add_all([profile, project])
    await db_session.flush()
    db_session.add(
        WorkPackage(
            name="Two working days",
            project_id=project.id,
            start_date=start,
            end_date=project.end_date,
            lead_time_working_days=2,
        )
    )
    await db_session.commit()
    item = (
        await ProjectOverviewService(db_session).get_overview(today=start)
    ).projects[0]
    assert len(item.late_work_packages) == 1
    assert item.late_work_packages[0].derived_end == start + timedelta(days=7 + weekday)
    assert item.late_work_packages[0].working_days_short == 1


@pytest.mark.parametrize("default_exists", [False, True])
async def test_unusable_default_calendar_keeps_dates_without_derived_schedule(
    db_session, default_exists
):
    """No working day means no invented end/float, even with dependency edges."""
    if default_exists:
        db_session.add(
            WorkWeekProfile(
                name="Closed",
                is_default=True,
                monday_minutes=0,
                tuesday_minutes=0,
                wednesday_minutes=0,
                thursday_minutes=0,
                friday_minutes=0,
                saturday_minutes=0,
                sunday_minutes=0,
            )
        )
    start = date(2026, 1, 5)
    project = Project(
        name="Closed calendar", start_date=start, end_date=start + timedelta(days=4)
    )
    db_session.add(project)
    await db_session.flush()
    first = WorkPackage(
        name="First",
        project_id=project.id,
        start_date=start,
        end_date=project.end_date,
        lead_time_working_days=3,
    )
    second = WorkPackage(
        name="Second",
        project_id=project.id,
        start_date=start,
        end_date=project.end_date,
        lead_time_working_days=3,
    )
    db_session.add_all([first, second])
    await db_session.flush()
    db_session.add(
        WorkPackageDependency(predecessor_id=first.id, successor_id=second.id)
    )
    await db_session.commit()
    item = (
        await ProjectOverviewService(db_session).get_overview(today=start)
    ).projects[0]
    assert item.start_date == project.start_date
    assert item.end_date == project.end_date
    assert item.active_work_package_count == 2
    assert item.late_work_packages == []
    assert item.dependency_violations == []
    assert item.min_float_working_days is None
    assert item.critical_work_package_count == 0


async def test_legacy_zero_resource_keeps_dated_profile_resolution(db_session):
    """Imported UUID zero must not turn a dated binding into a static plant week."""
    from uuid import UUID

    start = date(2026, 1, 5)
    group = ResourceGroup(name="Imported group")
    profile = WorkWeekProfile(name="Dated", is_default=False)
    project = Project(
        name="Imported IDs", start_date=start, end_date=start + timedelta(days=1)
    )
    db_session.add_all([group, profile, project])
    await db_session.flush()
    person = PersonalResource(id=UUID(int=0), name="Imported person", group_id=group.id)
    package = WorkPackage(
        name="Dated package",
        project_id=project.id,
        start_date=start,
        end_date=project.end_date,
        lead_time_working_days=3,
    )
    db_session.add_all([person, package])
    await db_session.flush()
    db_session.add_all(
        [
            ResourceWorkProfile(
                resource_id=person.id,
                profile_id=profile.id,
                valid_from=start + timedelta(days=1),
            ),
            Assignment(
                resource_id=person.id,
                resource_type="personal",
                work_package_id=package.id,
                start_date=start,
                end_date=project.end_date,
                allocation_percent=25,
            ),
        ]
    )
    await db_session.commit()
    item = (
        await ProjectOverviewService(db_session).get_overview(today=start)
    ).projects[0]
    assert item.late_work_packages[0].derived_end == start + timedelta(days=3)
