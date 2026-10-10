"""Assignment identity and concurrent writes against migrated PostgreSQL."""

import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.audit import AuditLog
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.resource_group import ResourceGroup
from app.models.user import User
from tests.test_project_integrity import client_for
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database, migrate  # noqa: F401

DAY = date(2026, 1, 5)


async def seed(engine, kind):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        group = ResourceGroup(name="Pool", resource_type=kind)
        user = User(
            name="Planner",
            email="assignment@example.test",
            role="admin",
            password_hash="test-only",
        )
        project = Project(name="Project", start_date=DAY, end_date=DAY)
        session.add_all([group, user, project])
        await session.flush()
        model = PersonalResource if kind == "personal" else InfrastructureResource
        resources = [model(name=f"Resource {i}", group_id=group.id) for i in range(3)]
        packages = [
            WorkPackage(
                name=f"Work {i}", project_id=project.id, start_date=DAY, end_date=DAY
            )
            for i in range(2)
        ]
        session.add_all([*resources, *packages])
        await session.commit()
        return user.id, [r.id for r in resources], [p.id for p in packages]


def payload(kind, rid, package):
    data = {
        "resource_type": kind,
        "resource_id": str(rid),
        "work_package_id": str(package),
    }
    if kind == "personal":
        data.update(
            start_date=DAY.isoformat(), end_date=DAY.isoformat(), allocation_percent=50
        )
    else:
        data.update(
            start_at=datetime(2026, 1, 5, 6, tzinfo=UTC).isoformat(),
            end_at=datetime(2026, 1, 5, 10, tzinfo=UTC).isoformat(),
        )
    return data


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_parallel_identical_assignments_have_one_winner(
    resource_database, monkeypatch, kind, operation
):
    uid, resources, packages = await seed(resource_database, kind)
    paths = []
    async with client_for(resource_database, uid) as client:
        if operation == "update":
            for rid in resources[1:]:
                response = await client.post(
                    "/api/assignments", json=payload(kind, rid, packages[0])
                )
                assert response.status_code == 201, response.text
                paths.append(f"/api/assignments/{response.json()['assignment']['id']}")
        else:
            paths = ["/api/assignments"] * 2
        original = AsyncSession.execute
        arrived, release = 0, asyncio.Event()

        async def synchronize(self, statement, *args, **kwargs):
            nonlocal arrived
            result = await original(self, statement, *args, **kwargs)
            sql = str(statement)
            if (
                sql.startswith("SELECT assignments.")
                and "assignments.resource_id =" in sql
                and "assignments.work_package_id =" in sql
            ):
                arrived += 1
                if arrived == 2:
                    release.set()
                await asyncio.wait_for(release.wait(), timeout=10)
            return result

        monkeypatch.setattr(AsyncSession, "execute", synchronize)
        request = client.post if operation == "create" else client.put
        responses = await asyncio.wait_for(
            asyncio.gather(
                *(
                    request(path, json=payload(kind, resources[0], packages[0]))
                    for path in paths
                )
            ),
            timeout=20,
        )
    assert sorted(r.status_code for r in responses) == [
        201 if operation == "create" else 200,
        409,
    ], [r.text for r in responses]
    async with AsyncSession(resource_database) as session:
        rows = (
            await session.scalars(
                sa.select(Assignment).where(Assignment.work_package_id == packages[0])
            )
        ).all()
        assert len(rows) == (1 if operation == "create" else 2)
        assert sum(row.resource_id == resources[0] for row in rows) == 1
        events = (
            await session.scalars(
                sa.select(AuditLog).where(
                    AuditLog.entity_type == "assignments",
                    AuditLog.entity_id.in_([row.id for row in rows]),
                    AuditLog.action
                    == ("created" if operation == "create" else "updated"),
                )
            )
        ).all()
        assert len(events) == 1
        assert events[0].actor_id == uid


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_sequential_identity_preview_and_independent_assignments(
    resource_database, kind
):
    uid, resources, packages = await seed(resource_database, kind)
    original = payload(kind, resources[0], packages[0])
    async with client_for(resource_database, uid) as client:
        assert (
            await client.post("/api/assignments/preview", json=original)
        ).status_code == 200
        first = await client.post("/api/assignments", json=original)
        assert first.status_code == 201, first.text
        assert (await client.post("/api/assignments", json=original)).status_code == 409
        assert (
            await client.post("/api/assignments/preview", json=original)
        ).status_code == 409
        for data in (
            payload(kind, resources[1], packages[0]),
            payload(kind, resources[0], packages[1]),
        ):
            assert (await client.post("/api/assignments", json=data)).status_code == 201
    async with AsyncSession(resource_database) as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Assignment)
                .where(Assignment.resource_id.in_(resources))
            )
            == 3
        )


async def test_same_uuid_in_different_resource_tables_has_distinct_identity(
    resource_database,
):
    uid, resources, packages = await seed(resource_database, "personal")
    async with AsyncSession(resource_database) as session:
        group = ResourceGroup(name="Machines", resource_type="infrastructure")
        session.add(group)
        await session.flush()
        session.add(
            InfrastructureResource(
                id=resources[0], name="Different kind", group_id=group.id
            )
        )
        await session.commit()
    async with client_for(resource_database, uid) as client:
        personal = await client.post(
            "/api/assignments", json=payload("personal", resources[0], packages[0])
        )
        assert personal.status_code == 201, personal.text
        infra = payload("infrastructure", resources[0], packages[0])
        preview = await client.post("/api/assignments/preview", json=infra)
        assert preview.status_code == 200, preview.text
        created = await client.post("/api/assignments", json=infra)
        assert created.status_code == 201, created.text


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_distinct_intervals_are_allowed_and_update_cannot_make_them_identical(
    resource_database, kind
):
    uid, resources, packages = await seed(resource_database, kind)
    original = payload(kind, resources[0], packages[0])
    other = {
        **original,
        **(
            {"allocation_percent": 75}
            if kind == "personal"
            else {"end_at": "2026-01-05T11:00:00Z"}
        ),
    }
    async with client_for(resource_database, uid) as client:
        first = await client.post("/api/assignments", json=original)
        assert first.status_code == 201, first.text
        preview = await client.post("/api/assignments/preview", json=other)
        assert preview.status_code == 200, preview.text
        second = await client.post("/api/assignments", json=other)
        assert second.status_code == 201, second.text
        aid = second.json()["assignment"]["id"]
        response = await client.put(f"/api/assignments/{aid}", json=original)
        assert response.status_code == 409, response.text
        after = await client.get(f"/api/assignments/{aid}")
        assert after.status_code == 200
        field = "allocation_percent" if kind == "personal" else "end_at"
        assert after.json()[field] == second.json()["assignment"][field]


async def test_migration_refuses_legacy_duplicates_without_removing_history(
    legacy_database,
):
    import os
    import subprocess
    import sys

    from tests.test_utc_migration_postgres import BOOKING, ROOT

    url, engine = legacy_database
    assert (await migrate(url, "002")).returncode == 0
    duplicate = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "INSERT INTO assignments SELECT :duplicate, resource_id, resource_type, work_package_id, start_date, end_date, allocation_percent, start_at, end_at, created_at, updated_at FROM assignments WHERE id=:original"
            ),
            {"duplicate": duplicate, "original": BOOKING},
        )

    async def stored():
        async with engine.connect() as connection:
            return (
                await connection.execute(
                    sa.text("SELECT * FROM assignments ORDER BY id")
                )
            ).all()

    before = await stored()
    async with engine.connect() as connection:
        history_count = await connection.scalar(
            sa.text("SELECT count(*) FROM baseline_entries")
        )
    result = await migrate(url, "003")
    assert result.returncode != 0
    assert "Identical assignment bookings prevent migration 003" in result.stderr
    assert str(BOOKING) in result.stderr and str(duplicate) in result.stderr
    assert await stored() == before
    async with engine.begin() as connection:
        assert (
            await connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == "002"
        )
        assert (
            await connection.scalar(sa.text("SELECT count(*) FROM baseline_entries"))
            == history_count
        )
        # A deliberate correction keeps both bookings and their historical IDs.
        await connection.execute(
            sa.text(
                "UPDATE assignments SET end_at=end_at+interval '1 hour' WHERE id=:id"
            ),
            {"id": duplicate},
        )
    assert (await migrate(url, "003")).returncode == 0
    after = await stored()
    assert len(after) == 2
    downgrade = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "002"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert downgrade.returncode == 0, downgrade.stderr
    assert await stored() == after
    assert (await migrate(url, "003")).returncode == 0
    assert await stored() == after


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_parallel_legacy_csv_import_reports_duplicate_and_retry_is_safe(
    resource_database, monkeypatch, kind
):
    from app.services.audit import set_actor
    from app.services.import_export.assignments import import_assignments

    uid, resources, _packages = await seed(resource_database, kind)
    original = AsyncSession.execute
    arrived, release = 0, asyncio.Event()

    async def synchronize(self, statement, *args, **kwargs):
        nonlocal arrived
        result = await original(self, statement, *args, **kwargs)
        if str(statement).startswith("SELECT assignments.") and "WHERE" not in str(
            statement
        ):
            arrived += 1
            if arrived == 2:
                release.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        return result

    monkeypatch.setattr(AsyncSession, "execute", synchronize)
    start, end = (
        (DAY.isoformat(), DAY.isoformat())
        if kind == "personal"
        else ("2026-01-05T06:00:00Z", "2026-01-05T10:00:00Z")
    )
    rows = [
        (
            "Project",
            "Work Package",
            "Resource",
            "Start",
            "End",
            "Allocation",
            "Resource Type",
            "Resource Group",
        ),
        ("Project", "Work 0", "Resource 0", start, end, "50", kind, "Pool"),
    ]

    async def importing():
        async with AsyncSession(resource_database, expire_on_commit=False) as session:
            set_actor(session, uid)
            return await import_assignments(session, rows)

    results = await asyncio.wait_for(
        asyncio.gather(importing(), importing()), timeout=20
    )
    assert sorted(result.created for result in results) == [0, 1]
    assert sum(bool(result.errors) for result in results) == 1
    assert "saved concurrently" in next(
        result.errors[0] for result in results if result.errors
    )
    retried = await importing()
    assert retried.created == 0 and retried.skipped == 1 and not retried.errors
    async with AsyncSession(resource_database) as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Assignment)
                .where(
                    Assignment.resource_id == resources[0],
                    Assignment.resource_type == kind,
                )
            )
            == 1
        )


@pytest.mark.parametrize(
    "kind,change",
    [
        ("personal", "separate"),
        ("personal", "overlap"),
        ("personal", "allocation"),
        ("infrastructure", "separate"),
        ("infrastructure", "overlap"),
    ],
)
async def test_multiple_bookings_preview_capacity_csv_and_individual_edit(
    resource_database, kind, change
):
    from app.models.base import column_values
    from app.models.calendar import WorkWeekProfile
    from app.models.conflict import Conflict
    from app.services.capacity_service import CapacityService
    from app.services.import_export import csv_transfer
    from app.services.import_export.csv_format import _read_csv
    from tests.test_utc_migration_postgres import BOOKING

    uid, resources, packages = await seed(resource_database, kind)
    async with AsyncSession(resource_database) as session:
        # The migration fixture contains an unbacked legacy booking unrelated to this plan.
        await session.execute(sa.delete(Assignment).where(Assignment.id == BOOKING))
        session.add(
            WorkWeekProfile(name="Default", monday_minutes=480, is_default=True)
        )
        await session.commit()
    first = payload(kind, resources[0], packages[0])
    second = dict(first)
    if kind == "personal":
        if change == "separate":
            second.update(start_date="2026-01-06", end_date="2026-01-06")
        elif change == "overlap":
            second.update(end_date="2026-01-06", allocation_percent=70)
        else:
            second.update(allocation_percent=70)
    else:
        if change == "separate":
            second.update(
                start_at="2026-01-05T10:00:00Z", end_at="2026-01-05T12:00:00Z"
            )
        else:
            second.update(
                start_at="2026-01-05T09:00:00Z", end_at="2026-01-05T11:00:00Z"
            )
    async with client_for(resource_database, uid) as client:
        one = await client.post("/api/assignments", json=first)
        assert one.status_code == 201, one.text
        preview = await client.post("/api/assignments/preview", json=second)
        assert preview.status_code == 200, preview.text
        two = await client.post("/api/assignments", json=second)
        assert two.status_code == 201, two.text
        ids = {one.json()["assignment"]["id"], two.json()["assignment"]["id"]}
        listing = await client.get(
            "/api/assignments",
            params={
                "resource_id": str(resources[0]),
                "work_package_id": str(packages[0]),
            },
        )
        assert {row["id"] for row in listing.json()["items"]} == ids
    async with AsyncSession(resource_database) as session:
        conflicts = (
            await session.scalars(
                sa.select(Conflict).where(Conflict.resource_id == resources[0])
            )
        ).all()
        assert len(conflicts) == (0 if change == "separate" else 1)
        if kind == "personal":
            assert await CapacityService(session).get_assigned_percent(
                resources[0], DAY
            ) == (50 if change == "separate" else 120)
        before = [
            column_values(row)
            for row in (
                await session.scalars(
                    sa.select(Assignment)
                    .where(Assignment.resource_id == resources[0])
                    .order_by(Assignment.id)
                )
            ).all()
        ]
        exported = await csv_transfer.export_area(session, "assignments")
        result = await csv_transfer.import_area_rows(
            session, "assignments", _read_csv(exported), admin_id=uid
        )
        assert not result.errors, result.errors
        assert result.created == 0 and result.updated == 2
        after = [
            column_values(row)
            for row in (
                await session.scalars(
                    sa.select(Assignment)
                    .where(Assignment.resource_id == resources[0])
                    .order_by(Assignment.id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        ]
        assert after == before
    async with client_for(resource_database, uid) as client:
        # Editing one booking addresses its ID and leaves its sibling unchanged.
        sibling_before = (
            await client.get(f"/api/assignments/{one.json()['assignment']['id']}")
        ).json()
        changed = await client.put(
            f"/api/assignments/{two.json()['assignment']['id']}",
            json={**second, "work_package_id": str(packages[1])},
        )
        assert changed.status_code == 200, changed.text
        original = await client.get(
            f"/api/assignments/{one.json()['assignment']['id']}"
        )
        assert original.json() == sibling_before
        assert original.json()["work_package_id"] == str(packages[0])
