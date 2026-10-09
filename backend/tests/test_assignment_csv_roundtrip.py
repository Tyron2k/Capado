"""Assignment CSV round trips and refusals against two independent databases.

SQLite checks relationships and persisted rows here. It drops timestamp offsets
on read, so UTC instants are compared explicitly; PostgreSQL timezone migration
coverage remains in test_utc_migration_postgres.py.
"""

from datetime import UTC, date, datetime
from io import BytesIO

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.assignment import Assignment
from app.models.base import ORMModel
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.resource_group import ResourceGroup
from app.models.work_package_template import WorkPackageTemplate
from app.routers.import_export import _parse_upload
from app.services.import_export import (
    export_assignments_csv,
    export_infrastructure_csv,
    export_personnel_csv,
    export_projects_csv,
    export_templates_csv,
    import_assignments,
    import_infrastructure,
    import_personnel,
    import_projects,
    import_templates,
)

HEADER = (
    "Project",
    "Work Package",
    "Resource",
    "Start",
    "End",
    "Allocation",
    "Resource Type",
    "Resource Group",
)
LEGACY_HEADER = HEADER[:6]


@pytest_asyncio.fixture
async def empty_target():
    """An independent empty schema, enforcing the foreign keys being restored."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(ORMModel.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def planning_data(db_session):
    """Repeated names across types/groups exercise the actual CSV references."""
    groups = [
        ResourceGroup(name="Team A", resource_type="personal"),
        ResourceGroup(name="Team B", resource_type="personal"),
        ResourceGroup(name="Machines", resource_type="infrastructure"),
    ]
    db_session.add_all(groups)
    await db_session.flush()
    people = [
        PersonalResource(name="Shared", group_id=groups[0].id),
        PersonalResource(name="Shared", group_id=groups[1].id),
        PersonalResource(name="Solo", group_id=groups[0].id),
    ]
    machine = InfrastructureResource(name="Shared", group_id=groups[2].id)
    project = Project(
        name="Build", start_date=date(2026, 10, 1), end_date=date(2026, 10, 31)
    )
    db_session.add_all([*people, machine, project])
    await db_session.flush()
    wp = WorkPackage(
        name="Paint",
        project_id=project.id,
        start_date=project.start_date,
        end_date=project.end_date,
    )
    db_session.add(wp)
    db_session.add(WorkPackageTemplate(name="Basic", description="Standard task"))
    await db_session.commit()
    return project, wp, people, machine


async def csv_rows(content):
    """Use the same UTF-8/BOM parser as an upload from the UI."""
    upload = UploadFile(
        filename="export.csv", file=BytesIO(content.encode("utf-8-sig"))
    )
    return await _parse_upload(upload)


async def all_assignments(session):
    return (await session.execute(select(Assignment))).scalars().all()


async def test_complete_area_csvs_restore_precise_assignments_and_ids(
    db_session, empty_target, planning_data
):
    project, wp, people, machine = planning_data
    source = [
        Assignment(
            resource_type="personal",
            resource_id=people[0].id,
            work_package_id=wp.id,
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 6),
            allocation_percent=33.5,
        ),
        Assignment(
            resource_type="personal",
            resource_id=people[0].id,
            work_package_id=wp.id,
            start_date=date(2026, 10, 12),
            end_date=date(2026, 10, 13),
            allocation_percent=66.75,
        ),
        Assignment(
            resource_type="personal",
            resource_id=people[1].id,
            work_package_id=wp.id,
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 6),
            allocation_percent=42.125,
        ),
        # Two occurrences of 02:15 in the DST fold, representing different UTC instants.
        Assignment(
            resource_type="infrastructure",
            resource_id=machine.id,
            work_package_id=wp.id,
            start_at=datetime.fromisoformat(
                "2026-10-25T02:15:23.123456+02:00"
            ).astimezone(UTC),
            end_at=datetime.fromisoformat(
                "2026-10-25T02:45:23.654321+02:00"
            ).astimezone(UTC),
        ),
        Assignment(
            resource_type="infrastructure",
            resource_id=machine.id,
            work_package_id=wp.id,
            start_at=datetime.fromisoformat(
                "2026-10-25T02:15:23.123456+01:00"
            ).astimezone(UTC),
            end_at=datetime.fromisoformat(
                "2026-10-25T02:45:23.654321+01:00"
            ).astimezone(UTC),
        ),
    ]
    db_session.add_all(source)
    await db_session.commit()
    pairs = (
        (export_personnel_csv, import_personnel),
        (export_infrastructure_csv, import_infrastructure),
        (export_templates_csv, import_templates),
        (export_projects_csv, import_projects),
        (export_assignments_csv, import_assignments),
    )
    for export, import_ in pairs:
        rows = await csv_rows(await export(db_session))
        result = await import_(empty_target, rows)
        assert result.errors == []
        assert result.skipped == 0
    assert result.created == 5

    restored = await all_assignments(empty_target)
    assert len(restored) == 5
    assert {a.id for a in source} == {a.id for a in restored}
    assert {a.resource_id for a in source} == {a.resource_id for a in restored}
    people_rows = [a for a in restored if a.resource_type == "personal"]
    assert sorted(a.allocation_percent for a in people_rows) == [33.5, 42.125, 66.75]
    infra_rows = [a for a in restored if a.resource_type == "infrastructure"]
    assert {a.start_at.replace(tzinfo=UTC) for a in infra_rows} == {
        datetime(2026, 10, 25, 0, 15, 23, 123456, UTC),
        datetime(2026, 10, 25, 1, 15, 23, 123456, UTC),
    }
    assert all(
        a.start_date is None and a.allocation_percent is None for a in infra_rows
    )
    assert all(a.start_at is None for a in people_rows)

    before = await csv_rows(await export_assignments_csv(db_session))
    after = await csv_rows(await export_assignments_csv(empty_target))
    assert tuple(before[0]) == ("Capado CSV", "2", "assignments")
    assert before == after
    second_import = await import_assignments(empty_target, before)
    assert second_import.errors == []
    assert second_import.created == 0
    assert second_import.updated == 5
    assert second_import.skipped == 0
    assert len(await all_assignments(empty_target)) == 5


async def test_reimport_skips_only_identical_bookings(db_session, planning_data):
    rows = [
        HEADER,
        (
            "Build",
            "Paint",
            "Solo",
            "2026-10-05",
            "2026-10-06",
            "33.5",
            "personal",
            "Team A",
        ),
        (
            "Build",
            "Paint",
            "Solo",
            "2026-10-05",
            "2026-10-06",
            "66.5",
            "personal",
            "Team A",
        ),
    ]
    first = await import_assignments(db_session, [*rows, rows[1]])
    assert first.errors == []
    assert first.created == 2
    assert first.skipped == 1
    db_session.expire_all()  # Duplicate detection must also work after a fresh DB read.
    second = await import_assignments(db_session, rows)
    assert second.created == 0
    assert second.skipped == 2


@pytest.mark.parametrize(
    "header,row",
    [
        (
            LEGACY_HEADER,
            ("Build", "Paint", "Shared", "2026-10-05", "2026-10-06", "100"),
        ),
        (
            HEADER,
            (
                "Build",
                "Paint",
                "Shared",
                "2026-10-05",
                "2026-10-06",
                "100",
                "personal",
                "",
            ),
        ),
        (
            HEADER,
            (
                "Build",
                "Paint",
                "Shared",
                "2026-10-05",
                "2026-10-06",
                "100",
                "machine",
                "Machines",
            ),
        ),
        (
            HEADER,
            (
                "Build",
                "Paint",
                "Solo",
                "2026-10-05",
                "2026-10-06",
                "100",
                "personal",
                "Team B",
            ),
        ),
    ],
)
async def test_bad_resource_references_never_write(
    db_session, planning_data, header, row
):
    result = await import_assignments(db_session, [header, row])
    assert result.created == 0
    assert result.errors
    assert await all_assignments(db_session) == []


@pytest.mark.parametrize(
    "start,end,allocation,kind,group",
    [
        (
            "2026-10-25T02:15:00",
            "2026-10-25T03:00:00+01:00",
            "100",
            "infrastructure",
            "Machines",
        ),
        (
            "2026-10-25T02:15:00+02:00",
            "2026-10-25T02:15:00+02:00",
            "100",
            "infrastructure",
            "Machines",
        ),
        ("2026-10-07", "2026-10-05", "100", "personal", "Team A"),
        ("2026-10-05", "2026-10-06", "nan", "personal", "Team A"),
        ("2026-10-05", "2026-10-06", "inf", "personal", "Team A"),
        ("2026-10-05", "2026-10-06", "wrong", "personal", "Team A"),
        ("2026-10-05", "2026-10-06", "0", "personal", "Team A"),
        ("2026-10-05", "2026-10-06", "101", "personal", "Team A"),
        ("2026-10-05", "2026-10-06", "-5", "personal", "Team A"),
    ],
)
async def test_invalid_periods_and_allocations_never_write(
    db_session, planning_data, start, end, allocation, kind, group
):
    resource = "Shared" if kind == "infrastructure" else "Solo"
    result = await import_assignments(
        db_session,
        [HEADER, ("Build", "Paint", resource, start, end, allocation, kind, group)],
    )
    assert result.created == 0
    assert "Row 2" in result.errors[0]
    assert await all_assignments(db_session) == []


@pytest.mark.parametrize("explicit_wp", [False, True])
async def test_ambiguous_work_packages_never_write(
    db_session, planning_data, explicit_wp
):
    project, wp, _people, _machine = planning_data
    db_session.add(
        WorkPackage(
            name=wp.name if explicit_wp else "Second",
            project_id=project.id,
            start_date=wp.start_date,
            end_date=wp.end_date,
        )
    )
    await db_session.commit()
    row = (
        "Build",
        "Paint" if explicit_wp else "",
        "Solo",
        "2026-10-05",
        "2026-10-06",
        "100",
    )
    result = await import_assignments(db_session, [LEGACY_HEADER, row])
    assert result.created == 0
    assert "ambiguous" in result.errors[0]
    assert await all_assignments(db_session) == []


async def test_ambiguous_project_names_never_write(db_session, planning_data):
    db_session.add(
        Project(name="Build", start_date=date(2026, 10, 1), end_date=date(2026, 10, 31))
    )
    await db_session.commit()
    result = await import_assignments(
        db_session,
        [LEGACY_HEADER, ("Build", "Paint", "Solo", "2026-10-05", "2026-10-06", "100")],
    )
    assert result.created == 0
    assert "ambiguous" in result.errors[0]
    assert await all_assignments(db_session) == []


async def test_columns_are_located_by_header_and_ignore_case(db_session, planning_data):
    result = await import_assignments(
        db_session,
        [
            (
                " END ",
                "resource",
                "resource type",
                "resource group",
                "project",
                "allocation",
                "start",
                "work package",
            ),
            (
                "2026-10-06",
                "shared",
                "PERSONAL",
                "team b",
                "build",
                "33.5",
                "2026-10-05",
                "paint",
            ),
        ],
    )
    assert result.created == 1
    assert result.errors == []
    assert (await all_assignments(db_session))[0].resource_id == planning_data[2][1].id


async def test_duplicate_headers_reject_entire_file(db_session, planning_data):
    result = await import_assignments(
        db_session,
        [
            (*LEGACY_HEADER, "Resource"),
            ("Build", "Paint", "Solo", "2026-10-05", "2026-10-06", "100", "Shared"),
        ],
    )
    assert "Header" in result.errors[0]
    assert await all_assignments(db_session) == []


async def test_offset_variants_of_same_instant_are_duplicates(
    db_session, planning_data
):
    result = await import_assignments(
        db_session,
        [
            HEADER,
            (
                "Build",
                "Paint",
                "Shared",
                "2026-10-25T02:15:00+02:00",
                "2026-10-25T02:45:00+02:00",
                "100",
                "infrastructure",
                "Machines",
            ),
            (
                "Build",
                "Paint",
                "Shared",
                "2026-10-25T00:15:00Z",
                "2026-10-25T00:45:00Z",
                "100",
                "infrastructure",
                "Machines",
            ),
        ],
    )
    assert result.errors == []
    assert result.created == 1
    assert result.skipped == 1
