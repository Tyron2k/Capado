"""Calendar defaults and binding races on migrated PostgreSQL."""

import asyncio
from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.calendar import ResourceWorkProfile, WorkWeekProfile
from app.models.resource import PersonalResource
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.user import User
from app.services.working_time_service import WorkingTimeService
from tests.test_project_integrity import client_for
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database, migrate  # noqa: F401

DAY = date(2026, 1, 5)


async def seed(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        admin = User(
            name="Calendar admin",
            email="calendar@example.test",
            role="admin",
            password_hash="test-only",
        )
        group = ResourceGroup(name="Group")
        profiles = [
            WorkWeekProfile(name=f"Profile {i}", monday_minutes=minutes)
            for i, minutes in enumerate([480, 120])
        ]
        sites = [Site(name=f"Site {i}") for i in range(2)]
        session.add_all([admin, group, *profiles, *sites])
        await session.flush()
        resources = [
            PersonalResource(name=f"Person {i}", group_id=group.id) for i in range(2)
        ]
        session.add_all(resources)
        await session.commit()
        return (
            admin.id,
            group.id,
            [p.id for p in profiles],
            [s.id for s in sites],
            [r.id for r in resources],
        )


async def snapshot(engine, model):
    async with AsyncSession(engine) as session:
        values = (
            await session.execute(
                sa.select(model.id, model.name, model.is_default).order_by(model.id)
            )
        ).all()
        audit = await session.scalar(sa.select(sa.func.count()).select_from(AuditLog))
        return values, audit


@pytest.mark.parametrize("kind", ["profiles", "sites"])
async def test_configured_default_cannot_be_removed_and_replacement_is_audited(
    resource_database, kind
):
    uid, _group, profiles, sites, resources = await seed(resource_database)
    model = WorkWeekProfile if kind == "profiles" else Site
    ids = profiles if kind == "profiles" else sites
    path = "/api/work-week-profiles" if kind == "profiles" else "/api/sites"
    async with client_for(resource_database, uid) as client:
        assert (
            await client.put(f"{path}/{ids[0]}", json={"is_default": True})
        ).status_code == 200
        before = await snapshot(resource_database, model)
        response = await client.put(
            f"{path}/{ids[0]}", json={"is_default": False, "name": "Must not change"}
        )
        assert response.status_code == 400, response.text
        assert await snapshot(resource_database, model) == before
        assert (await client.delete(f"{path}/{ids[0]}")).status_code == 400
        if kind == "sites":
            response = await client.put(f"{path}/{ids[0]}", json={"is_active": False})
            assert response.status_code == 400, response.text
        assert (
            await client.put(f"{path}/{ids[1]}", json={"is_default": True})
        ).status_code == 200
    async with AsyncSession(resource_database) as session:
        assert (
            await session.scalars(sa.select(model.id).where(model.is_default.is_(True)))
        ).all() == [ids[1]]
        events = (
            await session.scalars(
                sa.select(AuditLog).where(
                    AuditLog.entity_type == model.__tablename__,
                    AuditLog.action == "updated",
                )
            )
        ).all()
        assert len(events) == 3
        assert all(event.actor_id == uid for event in events)
        assert sorted(str(event.changes["is_default"]["to"]) for event in events) == [
            "False",
            "True",
            "True",
        ]
        if kind == "profiles":
            service = WorkingTimeService(session)
            await service.prepare(resources, DAY, DAY)
            assert [service.calendar_minutes(rid, DAY) for rid in resources] == [
                120,
                120,
            ]


@pytest.mark.parametrize("kind", ["profiles", "sites"])
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_parallel_default_choices_leave_one_default(
    resource_database, monkeypatch, kind, operation
):
    uid, _group, profiles, sites, _resources = await seed(resource_database)
    table = "work_week_profiles" if kind == "profiles" else "sites"
    model = WorkWeekProfile if kind == "profiles" else Site
    path = "/api/work-week-profiles" if kind == "profiles" else "/api/sites"
    ids = profiles if kind == "profiles" else sites
    original = AsyncSession.execute
    held, seen, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    owner, pid = None, None

    async def intercept(self, statement, *args, **kwargs):
        nonlocal owner, pid
        sql = str(statement)
        if owner is not None and self is not owner and "pg_advisory_xact_lock" in sql:
            pid = (
                await original(self, sa.text("SELECT pg_backend_pid()"))
            ).scalar_one()
            seen.set()
        result = await original(self, statement, *args, **kwargs)
        if sql.startswith(f"SELECT {table}.") and f"{table}.is_default = true" in sql:
            if owner is None:
                owner = self
                held.set()
                await asyncio.wait_for(release.wait(), timeout=10)
            elif owner is not self:
                seen.set()
        return result

    monkeypatch.setattr(AsyncSession, "execute", intercept)
    tasks = []
    async with client_for(resource_database, uid) as client:
        try:
            for i in range(2):
                task = (
                    client.post(
                        path, json={"name": f"New default {i}", "is_default": True}
                    )
                    if operation == "create"
                    else client.put(f"{path}/{ids[i]}", json={"is_default": True})
                )
                tasks.append(asyncio.create_task(task))
                if i == 0:
                    await asyncio.wait_for(held.wait(), timeout=10)
            await asyncio.wait_for(seen.wait(), timeout=10)
            if pid is not None:
                async with AsyncSession(resource_database) as observer:
                    async with asyncio.timeout(5):
                        while not await observer.scalar(
                            sa.text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory' AND NOT granted)"
                            ),
                            {"pid": pid},
                        ):
                            await asyncio.sleep(0.01)
            release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert all(
        response.status_code == (201 if operation == "create" else 200)
        for response in responses
    ), [r.text for r in responses]
    async with AsyncSession(resource_database) as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(model)
                .where(model.is_default.is_(True))
            )
            == 1
        )


@pytest.mark.parametrize("target", ["resource_id", "group_id"])
@pytest.mark.parametrize("open_end", [False, True])
async def test_parallel_overlapping_bindings_have_one_winner(
    resource_database, monkeypatch, target, open_end
):
    uid, group, profiles, _sites, resources = await seed(resource_database)
    original = AsyncSession.execute
    count, release = 0, asyncio.Event()

    async def synchronize(self, statement, *args, **kwargs):
        nonlocal count
        result = await original(self, statement, *args, **kwargs)
        sql = str(statement)
        if sql.startswith("SELECT resource_work_profiles."):
            count += 1
            if count == 2:
                release.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        return result

    monkeypatch.setattr(AsyncSession, "execute", synchronize)
    data = {
        target: str(resources[0] if target == "resource_id" else group),
        "valid_from": DAY.isoformat(),
        "valid_until": None if open_end else (DAY + timedelta(days=5)).isoformat(),
    }
    async with client_for(resource_database, uid) as client:
        responses = await asyncio.wait_for(
            asyncio.gather(
                *(
                    client.post(
                        "/api/resource-work-profiles",
                        json={**data, "profile_id": str(pid)},
                    )
                    for pid in profiles
                )
            ),
            timeout=20,
        )
    assert sorted(r.status_code for r in responses) == [201, 400], [
        r.text for r in responses
    ]
    async with AsyncSession(resource_database) as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(ResourceWorkProfile)
            )
            == 1
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_type == "resource_work_profiles")
            )
            == 1
        )


async def test_inclusive_boundaries_independent_targets_and_resolution(
    resource_database,
):
    uid, group, profiles, _sites, resources = await seed(resource_database)
    async with client_for(resource_database, uid) as client:
        base = {
            "profile_id": str(profiles[0]),
            "resource_id": str(resources[0]),
            "valid_from": DAY.isoformat(),
            "valid_until": DAY.isoformat(),
        }
        assert (
            await client.post("/api/resource-work-profiles", json=base)
        ).status_code == 201
        assert (
            await client.post(
                "/api/resource-work-profiles", json={**base, "valid_until": None}
            )
        ).status_code == 400
        assert (
            await client.post(
                "/api/resource-work-profiles",
                json={
                    **base,
                    "valid_from": (DAY + timedelta(days=1)).isoformat(),
                    "valid_until": None,
                },
            )
        ).status_code == 201
        assert (
            await client.post(
                "/api/resource-work-profiles",
                json={**base, "resource_id": str(resources[1])},
            )
        ).status_code == 201
        assert (
            await client.post(
                "/api/resource-work-profiles",
                json={
                    "profile_id": str(profiles[1]),
                    "group_id": str(group),
                    "valid_from": DAY.isoformat(),
                    "valid_until": None,
                },
            )
        ).status_code == 201
    async with AsyncSession(resource_database) as session:
        service = WorkingTimeService(session)
        await service.prepare(resources, DAY, DAY + timedelta(days=2))
        assert [service.calendar_minutes(rid, DAY) for rid in resources] == [480, 480]
        assert (
            service.profile_for(resources[1], DAY + timedelta(days=2)).id == profiles[1]
        )


@pytest.mark.parametrize(
    "problem",
    [
        "profile_defaults",
        "site_defaults",
        "inactive_site",
        "resource_overlap",
        "group_overlap",
    ],
)
async def test_calendar_migration_reports_legacy_conflicts_and_preserves_data(
    legacy_database, problem
):
    import os
    import subprocess
    import sys

    from tests.test_utc_migration_postgres import ROOT

    url, engine = legacy_database
    assert (await migrate(url, "003")).returncode == 0
    _uid, group, profiles, sites, resources = await seed(engine)
    binding_ids = []
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if problem in {"profile_defaults", "site_defaults"}:
            model = WorkWeekProfile if problem == "profile_defaults" else Site
            await session.execute(sa.update(model).values(is_default=True))
        elif problem == "inactive_site":
            await session.execute(
                sa.update(Site)
                .where(Site.id == sites[0])
                .values(is_default=True, is_active=False)
            )
        else:
            for pid in profiles:
                binding = ResourceWorkProfile(
                    profile_id=pid,
                    valid_from=DAY,
                    valid_until=None,
                    **(
                        {"group_id": group}
                        if problem == "group_overlap"
                        else {"resource_id": resources[0]}
                    ),
                )
                session.add(binding)
                binding_ids.append(binding.id)
            await session.commit()
        await session.commit()

    async def records():
        async with engine.connect() as connection:
            return [
                list(
                    (
                        await connection.execute(
                            sa.text(f"SELECT * FROM {table} ORDER BY id")
                        )
                    ).all()
                )
                for table in (
                    "sites",
                    "work_week_profiles",
                    "resource_work_profiles",
                    "audit_log",
                    "baseline_entries",
                )
            ]

    before = await records()
    failed = await migrate(url, "004")
    assert failed.returncode != 0
    assert "Calendar integrity conflicts prevent migration 004" in failed.stderr
    expected_ids = (
        profiles
        if problem == "profile_defaults"
        else sites
        if problem == "site_defaults"
        else [sites[0]]
        if problem == "inactive_site"
        else binding_ids
    )
    assert all(str(identifier) in failed.stderr for identifier in expected_ids)
    assert await records() == before
    async with engine.begin() as connection:
        assert (
            await connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == "003"
        )
        if problem.endswith("defaults"):
            model = WorkWeekProfile if problem == "profile_defaults" else Site
            await connection.execute(
                sa.update(model).values(
                    is_default=model.id
                    == (profiles[0] if problem == "profile_defaults" else sites[0])
                )
            )
        elif problem == "inactive_site":
            await connection.execute(
                sa.update(Site).values(is_default=Site.id == sites[1])
            )
        else:
            await connection.execute(
                sa.update(ResourceWorkProfile)
                .where(ResourceWorkProfile.id == binding_ids[0])
                .values(valid_until=DAY)
            )
            await connection.execute(
                sa.update(ResourceWorkProfile)
                .where(ResourceWorkProfile.id == binding_ids[1])
                .values(valid_from=DAY + timedelta(days=1), valid_until=None)
            )
    corrected = await records()
    upgraded = await migrate(url, "004")
    assert upgraded.returncode == 0, upgraded.stderr
    assert await records() == corrected
    downgraded = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "003"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert downgraded.returncode == 0, downgraded.stderr
    assert await records() == corrected
    assert (await migrate(url, "004")).returncode == 0
    assert await records() == corrected


@pytest.mark.parametrize("kind", ["profiles", "sites"])
async def test_failed_default_swap_rolls_back_both_flags_and_audit(
    resource_database, monkeypatch, kind
):
    uid, _group, profiles, sites, _resources = await seed(resource_database)
    path = "/api/work-week-profiles" if kind == "profiles" else "/api/sites"
    ids = profiles if kind == "profiles" else sites
    model = WorkWeekProfile if kind == "profiles" else Site
    async with client_for(resource_database, uid) as client:
        assert (
            await client.put(f"{path}/{ids[0]}", json={"is_default": True})
        ).status_code == 200
        before = await snapshot(resource_database, model)

        async def fail(_self):
            raise RuntimeError(
                "Simulated commit failure after clearing previous default"
            )

        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession, "commit", fail)
            assert (
                await client.put(f"{path}/{ids[1]}", json={"is_default": True})
            ).status_code == 500
        assert await snapshot(resource_database, model) == before
        assert (
            await client.put(f"{path}/{ids[1]}", json={"is_default": True})
        ).status_code == 200


async def test_waiting_binding_does_not_block_another_target(resource_database):
    uid, _group, profiles, _sites, resources = await seed(resource_database)
    async with AsyncSession(resource_database) as holder:
        holder.add(
            ResourceWorkProfile(
                resource_id=resources[0], profile_id=profiles[0], valid_from=DAY
            )
        )
        await holder.flush()
        async with client_for(resource_database, uid) as client:
            body = {
                "profile_id": str(profiles[1]),
                "valid_from": DAY.isoformat(),
                "valid_until": None,
            }
            blocked = asyncio.create_task(
                client.post(
                    "/api/resource-work-profiles",
                    json={**body, "resource_id": str(resources[0])},
                )
            )
            try:
                async with AsyncSession(resource_database) as observer:
                    async with asyncio.timeout(5):
                        while not await observer.scalar(
                            sa.text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks l JOIN pg_stat_activity a USING(pid) WHERE a.datname=current_database() AND NOT l.granted)"
                            )
                        ):
                            await asyncio.sleep(0.01)
                independent = await asyncio.wait_for(
                    client.post(
                        "/api/resource-work-profiles",
                        json={**body, "resource_id": str(resources[1])},
                    ),
                    timeout=5,
                )
                assert independent.status_code == 201, independent.text
                assert not blocked.done()
                await holder.rollback()
                response = await asyncio.wait_for(blocked, timeout=10)
                assert response.status_code == 201, response.text
            finally:
                await holder.rollback()
                if not blocked.done():
                    blocked.cancel()
                await asyncio.gather(blocked, return_exceptions=True)


@pytest.mark.parametrize("kind", ["profiles", "sites"])
async def test_csv_default_swap_is_atomic_and_cannot_remove_configured_default(
    resource_database, kind
):
    from app.services.import_export import csv_format, csv_transfer
    from app.services.import_export.csv_storage import load_data
    from app.services.import_export.working_time import CSV_AREA, export_csv

    uid, _group, profiles, sites, _resources = await seed(resource_database)
    path = "/api/work-week-profiles" if kind == "profiles" else "/api/sites"
    ids = profiles if kind == "profiles" else sites
    model = WorkWeekProfile if kind == "profiles" else Site
    async with client_for(resource_database, uid) as client:
        assert (
            await client.put(f"{path}/{ids[0]}", json={"is_default": True})
        ).status_code == 200
    async with AsyncSession(resource_database) as session:
        data = await load_data(session, CSV_AREA.entities)
        records = data[model.__tablename__]
        for row in records:
            row["is_default"] = False
        before = await snapshot(resource_database, model)
        result = await csv_transfer.import_area_rows(
            session, CSV_AREA.name, csv_format._read_csv(export_csv(data))
        )
        assert result.created == result.updated == 0 and result.errors
        assert await snapshot(resource_database, model) == before
        for row in records:
            row["is_default"] = row["id"] == ids[1]
        # Deliberately put the new default first: write order must not affect success.
        records.sort(key=lambda row: not row["is_default"])
        result = await csv_transfer.import_area_rows(
            session, CSV_AREA.name, csv_format._read_csv(export_csv(data))
        )
        assert not result.errors, result.errors
    async with AsyncSession(resource_database) as session:
        assert (
            await session.scalars(sa.select(model.id).where(model.is_default.is_(True)))
        ).all() == [ids[1]]


@pytest.mark.parametrize("kind", ["profiles", "sites"])
async def test_database_rejects_a_second_default_even_outside_the_service(
    resource_database, kind
):
    from sqlalchemy.exc import IntegrityError

    _uid, _group, profiles, sites, _resources = await seed(resource_database)
    model = WorkWeekProfile if kind == "profiles" else Site
    ids = profiles if kind == "profiles" else sites
    async with resource_database.begin() as connection:
        await connection.execute(
            sa.update(model).where(model.id == ids[0]).values(is_default=True)
        )
    with pytest.raises(IntegrityError) as failure:
        async with resource_database.begin() as connection:
            await connection.execute(
                sa.update(model).where(model.id == ids[1]).values(is_default=True)
            )
    assert (
        failure.value.orig.__cause__.constraint_name
        == f"uq_{model.__tablename__}_default"
    )
    async with AsyncSession(resource_database) as session:
        assert (
            await session.scalars(sa.select(model.id).where(model.is_default.is_(True)))
        ).all() == [ids[0]]


async def test_existing_postgres_period_guard_already_rejects_reverse_dates(
    legacy_database,
):
    from sqlalchemy.exc import IntegrityError

    url, engine = legacy_database
    assert (await migrate(url, "003")).returncode == 0
    _uid, _group, profiles, _sites, resources = await seed(engine)
    with pytest.raises(IntegrityError) as failure:
        async with AsyncSession(engine) as session:
            session.add(
                ResourceWorkProfile(
                    resource_id=resources[0],
                    profile_id=profiles[0],
                    valid_from=DAY,
                    valid_until=DAY - timedelta(days=1),
                )
            )
            await session.commit()
    assert (
        failure.value.orig.__cause__.constraint_name
        == "ck_resource_work_profiles_validity_order"
    )
    async with AsyncSession(engine) as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(ResourceWorkProfile)
            )
            == 0
        )
    assert (await migrate(url, "004")).returncode == 0


@pytest.mark.parametrize("kind", ["profiles", "sites"])
@pytest.mark.parametrize("abort", [False, True])
async def test_csv_default_swap_import_marker_history_and_rollback(
    resource_database, monkeypatch, kind, abort
):
    from app.models.base import column_values
    from app.services.import_export import csv_format, csv_transfer, history
    from app.services.import_export.csv_storage import load_data
    from app.services.import_export.working_time import CSV_AREA, export_csv

    uid, _group, profiles, sites, _resources = await seed(resource_database)
    model = WorkWeekProfile if kind == "profiles" else Site
    ids = profiles if kind == "profiles" else sites
    path = "/api/work-week-profiles" if kind == "profiles" else "/api/sites"
    async with client_for(resource_database, uid) as client:
        assert (
            await client.put(f"{path}/{ids[0]}", json={"is_default": True})
        ).status_code == 200

    async def audit_rows():
        async with AsyncSession(resource_database) as session:
            return {
                row.id: column_values(row)
                for row in (await session.scalars(sa.select(AuditLog))).all()
            }

    old_audit = await audit_rows()
    old_flags = await snapshot(resource_database, model)
    original_marker = history.write_import_marker
    marker_reached = False
    if abort:

        async def fail_after_marker(session, context):
            nonlocal marker_reached
            await original_marker(session, context)
            marker_reached = True
            raise ValueError("Simulated failure after the import marker was written")

        monkeypatch.setattr(history, "write_import_marker", fail_after_marker)
    async with AsyncSession(resource_database) as session:
        data = await load_data(session, CSV_AREA.entities)
        for row in data[model.__tablename__]:
            row["is_default"] = row["id"] == ids[1]
        result = await csv_transfer.import_area_rows(
            session, CSV_AREA.name, csv_format._read_csv(export_csv(data)), admin_id=uid
        )
    after = await audit_rows()
    if abort:
        assert (
            marker_reached and result.errors and result.created == result.updated == 0
        )
        assert after == old_audit
        assert await snapshot(resource_database, model) == old_flags
    else:
        assert not result.errors, result.errors
        assert {key: after[key] for key in old_audit} == old_audit
        new = [row for key, row in after.items() if key not in old_audit]
        assert len(new) == 1
        assert new[0]["entity_type"] == "csv_import" and new[0]["actor_id"] == uid
        assert new[0]["action"] == "created" and new[0]["reason"]
        assert (
            new[0]["changes"] == {}
        )  # One operation marker, not invented per-row history.
        async with AsyncSession(resource_database) as session:
            assert (
                await session.scalars(
                    sa.select(model.id).where(model.is_default.is_(True))
                )
            ).all() == [ids[1]]


async def test_calendar_extension_requires_database_create_and_rolls_back(
    legacy_database,
):
    """Test a table-owning migration role without superuser/DB CREATE privileges."""
    from uuid import uuid4

    from sqlalchemy.engine import make_url

    url, engine = legacy_database
    assert (await migrate(url, "003")).returncode == 0
    role = "capado_migration_test_" + uuid4().hex
    limited_url = (
        make_url(url)
        .set(username=role, password="synthetic-migration-test-only")
        .render_as_string(hide_password=False)
    )
    parsed = make_url(url)
    assert parsed.database.startswith("capado_timezone_test_")
    # Identifiers are generated locally, never supplied by users or a real deployment.
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                f"CREATE ROLE {role} LOGIN PASSWORD 'synthetic-migration-test-only'"
            )
        )
    try:
        async with engine.begin() as connection:
            names = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            for name in names:
                assert name.replace("_", "").isalnum()
                await connection.execute(
                    sa.text(f'ALTER TABLE "{name}" OWNER TO {role}')
                )
            await connection.execute(
                sa.text(f"GRANT USAGE, CREATE ON SCHEMA public TO {role}")
            )
            assert not await connection.scalar(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='btree_gist')"
                )
            )
            before = {
                name: list(
                    (
                        await connection.execute(
                            sa.text(f'SELECT * FROM "{name}" ORDER BY 1')
                        )
                    ).all()
                )
                for name in names
            }
        failed = await migrate(limited_url, "004")
        assert failed.returncode != 0
        assert (
            "permission denied to create extension" in failed.stderr
            and "btree_gist" in failed.stderr
        )
        async with engine.begin() as connection:
            after = {
                name: list(
                    (
                        await connection.execute(
                            sa.text(f'SELECT * FROM "{name}" ORDER BY 1')
                        )
                    ).all()
                )
                for name in names
            }
            assert after == before
            assert not await connection.scalar(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='btree_gist')"
                )
            )
            assert not await connection.scalar(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ex_work_profiles_group_period')"
                )
            )
            await connection.execute(
                sa.text(f'GRANT CREATE ON DATABASE "{parsed.database}" TO {role}')
            )
        succeeded = await migrate(limited_url, "004")
        assert succeeded.returncode == 0, succeeded.stderr
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                )
                == "004"
            )
            assert await connection.scalar(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='btree_gist')"
                )
            )
            for name in names:
                if name != "alembic_version":
                    assert (
                        list(
                            (
                                await connection.execute(
                                    sa.text(f'SELECT * FROM "{name}" ORDER BY 1')
                                )
                            ).all()
                        )
                        == before[name]
                    )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(f'REASSIGN OWNED BY {role} TO "{parsed.username}"')
            )
            await connection.execute(sa.text(f"DROP OWNED BY {role}"))
            await connection.execute(sa.text(f"DROP ROLE {role}"))


@pytest.mark.parametrize("first", ["deletion", "binding"])
async def test_profile_deletion_and_binding_keep_references_safe(
    resource_database, monkeypatch, first
):
    uid, _group, profiles, _sites, resources = await seed(resource_database)
    original_get = AsyncSession.get
    reached, pid = asyncio.Event(), None
    async with AsyncSession(resource_database) as holder:
        await holder.execute(
            sa.select(WorkWeekProfile)
            .where(WorkWeekProfile.id == profiles[0])
            .with_for_update(read=True, key_share=True)
            if first == "binding"
            else sa.select(WorkWeekProfile)
            .where(WorkWeekProfile.id == profiles[0])
            .with_for_update()
        )
        if first == "binding":
            holder.add(
                ResourceWorkProfile(
                    resource_id=resources[0], profile_id=profiles[0], valid_from=DAY
                )
            )
            await holder.flush()

        async def looking(self, entity, key, *args, **kwargs):
            nonlocal pid
            if self is not holder and entity is WorkWeekProfile and key == profiles[0]:
                pid = await self.scalar(sa.text("SELECT pg_backend_pid()"))
                reached.set()
            return await original_get(self, entity, key, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "get", looking)
        async with client_for(resource_database, uid) as client:
            task = asyncio.create_task(
                client.delete(f"/api/work-week-profiles/{profiles[0]}")
                if first == "binding"
                else client.post(
                    "/api/resource-work-profiles",
                    json={
                        "resource_id": str(resources[0]),
                        "profile_id": str(profiles[0]),
                        "valid_from": DAY.isoformat(),
                    },
                )
            )
            try:
                await asyncio.wait_for(reached.wait(), 5)
                async with AsyncSession(resource_database) as observer:
                    async with asyncio.timeout(5):
                        while not await observer.scalar(
                            sa.text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)"
                            ),
                            {"pid": pid},
                        ):
                            await asyncio.sleep(0.01)
                assert not task.done()
                if first == "deletion":
                    await holder.delete(await holder.get(WorkWeekProfile, profiles[0]))
                await holder.commit()
                response = await asyncio.wait_for(task, 10)
            finally:
                await holder.rollback()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert response.status_code == (400 if first == "binding" else 404), response.text
    async with AsyncSession(resource_database) as session:
        assert (await session.get(WorkWeekProfile, profiles[0]) is not None) == (
            first == "binding"
        )
        bindings = (
            await session.scalars(
                sa.select(ResourceWorkProfile).where(
                    ResourceWorkProfile.profile_id == profiles[0]
                )
            )
        ).all()
        assert len(bindings) == (1 if first == "binding" else 0)
        events = (
            await session.scalars(
                sa.select(AuditLog).where(
                    AuditLog.entity_type == "resource_work_profiles",
                    AuditLog.action == "created",
                )
            )
        ).all()
        assert len(events) == (1 if first == "binding" else 0)
        assert all(
            event.actor_id is None for event in events
        )  # Rejected HTTP write creates no audit.
