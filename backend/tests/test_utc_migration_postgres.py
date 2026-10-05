"""Exercise real Alembic upgrades in disposable PostgreSQL databases.

Set TEST_POSTGRES_URL to a test server where the account can CREATE DATABASE.
Never migrates the supplied database: each test creates and drops its own database.
CI supplies PostgreSQL; local runs without a test server explicitly skip this module.
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.assignment import Assignment
from app.services.baseline_service import diff_payloads, snapshot_payload

ROOT = Path(__file__).resolve().parents[1]
BOOKING = UUID("11111111-1111-1111-1111-111111111111")
BASELINE = UUID("22222222-2222-2222-2222-222222222222")
PROJECT = UUID("33333333-3333-3333-3333-333333333333")
PACKAGE = UUID("44444444-4444-4444-4444-444444444444")


async def test_small_area_import_allows_concurrent_unrelated_history_writes(
    legacy_database, monkeypatch
):
    """Scoped table locks leave independent edits writable during an import."""
    from app import models as m
    from app.services.import_export import skills
    from app.services.import_export.csv_format import _read_csv
    from app.services.import_export.csv_transfer import import_area_rows

    url, engine = legacy_database
    assert (await migrate(url, "head")).returncode == 0
    original = skills.write_import
    concurrent_id = uuid4()

    async def write_with_unrelated_edit(session, batch, context):
        result = await original(session, batch, context)
        async with AsyncSession(engine) as writer:
            await writer.execute(sa.text("SET LOCAL lock_timeout TO '250ms'"))
            writer.add(
                m.AuditLog(
                    id=concurrent_id,
                    entity_type="projects",
                    entity_id=uuid4(),
                    action="created",
                )
            )
            await writer.commit()
        return result

    monkeypatch.setattr(skills, "write_import", write_with_unrelated_edit)
    record = m.Skill(name="Independent import", resource_type="personal").model_dump()
    content = skills.export_csv({"skills": [record], "skill_attributes": []})
    async with AsyncSession(engine) as session:
        result = await import_area_rows(session, "skills", _read_csv(content))
        assert not result.errors and result.created == 1
        assert await session.get(m.AuditLog, concurrent_id) is not None
        assert await session.get(m.Skill, record["id"]) is not None


async def test_zip_export_keeps_one_snapshot_across_dedicated_exporters(
    legacy_database, monkeypatch
):
    """A concurrent edit between exporters cannot produce a mixed-time archive."""
    from app import models as m
    from app.services.import_export import skills
    from app.services.import_export.csv_format import _read_csv
    from app.services.import_export.csv_transfer import (
        export_migration,
        parse_migration,
    )

    url, engine = legacy_database
    assert (await migrate(url, "head")).returncode == 0
    site = m.Site(name="Before")
    user = m.User(
        name="Before",
        email="snapshot@example.test",
        role="admin",
        password_hash="test-only",
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        group = m.ResourceGroup(name="Machines", resource_type="infrastructure")
        session.add_all([site, user, group])
        await session.flush()
        booking = await session.get(Assignment, BOOKING)
        session.add(
            m.InfrastructureResource(
                id=booking.resource_id, name="Machine", group_id=group.id
            )
        )
        await session.commit()
    original = skills.load_export
    calls = 0

    async def edit_between_exporters(snapshot):
        nonlocal calls
        calls += 1
        async with AsyncSession(engine) as writer:
            await writer.execute(
                sa.update(m.Site).where(m.Site.id == site.id).values(name="After")
            )
            await writer.execute(
                sa.update(m.User).where(m.User.id == user.id).values(name="After")
            )
            await writer.commit()
        return await original(snapshot)

    monkeypatch.setattr(skills, "load_export", edit_between_exporters)
    async with AsyncSession(engine) as session:
        data = parse_migration(await export_migration(session))
    assert calls == 1
    assert (
        next(row for row in data["sites"] if row["id"] == site.id)["name"] == "Before"
    )
    assert (
        next(row for row in data["users"] if row["id"] == user.id)["name"] == "Before"
    )
    async with AsyncSession(engine) as session:
        assert (await session.get(m.Site, site.id)).name == "After"
        assert (await session.get(m.User, user.id)).name == "After"


async def migrate(url: str, revision: str) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env={
            **os.environ,
            "DATABASE_URL": url,
            "CAPADO_LEGACY_BOOKING_TIME_ZONE": "Europe/Berlin",
        },
        capture_output=True,
        text=True,
        timeout=45,
    )


@pytest_asyncio.fixture
async def legacy_database():
    server = os.environ.get("TEST_POSTGRES_URL")
    if not server:
        pytest.skip("TEST_POSTGRES_URL is required for real PostgreSQL migration tests")
    admin = create_async_engine(server, isolation_level="AUTOCOMMIT")
    name = "capado_timezone_test_" + uuid4().hex
    url = (
        sa.engine.make_url(server)
        .set(database=name)
        .render_as_string(hide_password=False)
    )
    engine = create_async_engine(url)
    async with admin.connect() as connection:
        await connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
        # Detect conversions that accidentally depend on the server/session timezone.
        await connection.execute(
            sa.text(f"ALTER DATABASE \"{name}\" SET timezone TO 'America/New_York'")
        )
    try:
        result = await migrate(url, "001")
        assert result.returncode == 0, result.stderr
        async with engine.begin() as connection:
            await connection.run_sync(seed_legacy)
        yield url, engine
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


def seed_legacy(connection):
    metadata = sa.MetaData()
    metadata.reflect(connection)
    tables = metadata.tables
    technical = datetime(2026, 7, 1, 12, 34, 56)
    common = {"created_at": technical, "updated_at": technical}
    dates = {
        "start_date": datetime(2026, 1, 1).date(),
        "end_date": datetime(2026, 12, 31).date(),
    }
    connection.execute(
        tables["projects"]
        .insert()
        .values(id=PROJECT, name="Migration test", **dates, **common)
    )
    connection.execute(
        tables["work_packages"]
        .insert()
        .values(
            id=PACKAGE,
            project_id=PROJECT,
            name="Work",
            completed_at=technical,
            **dates,
            **common,
        )
    )
    connection.execute(
        tables["assignments"]
        .insert()
        .values(
            id=BOOKING,
            resource_id=uuid4(),
            resource_type="infrastructure",
            work_package_id=PACKAGE,
            start_at=datetime(2026, 7, 1, 8),
            end_at=datetime(2026, 7, 1, 10),
            **common,
        )
    )
    connection.execute(
        tables["baselines"]
        .insert()
        .values(id=BASELINE, name="Before UTC", created_at=technical)
    )
    connection.execute(
        tables["baseline_entries"]
        .insert()
        .values(
            id=uuid4(),
            baseline_id=BASELINE,
            entity_type="assignments",
            entity_id=BOOKING,
            payload={
                "start_at": "2026-07-01T08:00:00",
                "end_at": "2026-07-01T10:00:00",
                "start_date": None,
            },
        )
    )
    connection.execute(
        tables["baseline_entries"]
        .insert()
        .values(
            id=uuid4(),
            baseline_id=BASELINE,
            entity_type="work_packages",
            entity_id=PACKAGE,
            payload={"completed_at": technical.isoformat(), "start_date": "2026-01-01"},
        )
    )
    connection.execute(
        tables["audit_log"]
        .insert()
        .values(
            id=uuid4(),
            entity_type="assignments",
            entity_id=BOOKING,
            action="updated",
            recorded_at=technical,
            changes={
                "start_at": {
                    "from": "2026-01-15T08:00:00",
                    "to": "2026-07-01T08:00:00",
                },
                "start_date": {"from": None, "to": "2026-07-01"},
            },
        )
    )
    connection.execute(
        tables["organization_settings"]
        .insert()
        .values(id=uuid4(), updated_at=technical)
    )


async def test_upgrade_preserves_instants_and_baseline_meaning(legacy_database):
    url, engine = legacy_database
    result = await migrate(url, "head")
    assert result.returncode == 0, result.stderr
    async with AsyncSession(engine) as session:
        booking = await session.get(Assignment, BOOKING)
        assert booking.start_at == datetime(2026, 7, 1, 6, tzinfo=UTC)
        assert booking.end_at == datetime(2026, 7, 1, 8, tzinfo=UTC)
        assert booking.created_at == datetime(2026, 7, 1, 12, 34, 56, tzinfo=UTC)
        payload = (
            await session.execute(
                sa.text(
                    "SELECT payload FROM baseline_entries WHERE entity_type = 'assignments'"
                )
            )
        ).scalar_one()
        assert diff_payloads(payload, snapshot_payload(booking)) == {}
        completed = (
            await session.execute(
                sa.text(
                    "SELECT payload FROM baseline_entries WHERE entity_type = 'work_packages'"
                )
            )
        ).scalar_one()
        assert completed == {
            "completed_at": "2026-07-01T12:34:56+00:00",
            "start_date": "2026-01-01",
        }
        changes = (
            await session.execute(sa.text("SELECT changes FROM audit_log"))
        ).scalar_one()
        assert changes["start_at"] == {
            "from": "2026-01-15T07:00:00+00:00",
            "to": "2026-07-01T06:00:00+00:00",
        }
        assert changes["start_date"] == {"from": None, "to": "2026-07-01"}
        assert (
            await session.execute(
                sa.text("SELECT time_zone FROM organization_settings")
            )
        ).scalar_one() == "Europe/Berlin"
        assert (
            await session.execute(
                sa.text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND data_type='timestamp without time zone'"
                )
            )
        ).scalar_one() == 0
    # Starting the new release again must not convert anything twice.
    assert (await migrate(url, "head")).returncode == 0


@pytest.mark.parametrize("source", ["booking", "baseline", "audit"])
@pytest.mark.parametrize("invalid", ["2026-03-29T02:30:00", "2026-10-25T02:30:00"])
async def test_ambiguous_history_rolls_back_the_entire_upgrade(
    legacy_database, source, invalid
):
    url, engine = legacy_database
    async with engine.begin() as connection:
        if source == "booking":
            await connection.execute(
                sa.text("UPDATE assignments SET start_at=:value"),
                {"value": datetime.fromisoformat(invalid)},
            )
        elif source == "baseline":
            await connection.execute(
                sa.text(
                    "UPDATE baseline_entries SET payload=CAST(:value AS json) WHERE entity_type='assignments'"
                ),
                {"value": json.dumps({"start_at": invalid})},
            )
        else:
            await connection.execute(
                sa.text("UPDATE audit_log SET changes=CAST(:value AS json)"),
                {"value": json.dumps({"start_at": {"from": None, "to": invalid}})},
            )
    result = await migrate(url, "head")
    assert result.returncode != 0
    assert "UTC migration stopped" in result.stderr
    async with engine.connect() as connection:
        assert (
            await connection.execute(sa.text("SELECT version_num FROM alembic_version"))
        ).scalar_one() == "001"
        assert (
            await connection.execute(
                sa.text(
                    "SELECT data_type FROM information_schema.columns WHERE table_name='assignments' AND column_name='start_at'"
                )
            )
        ).scalar_one() == "timestamp without time zone"
        assert (
            await connection.execute(
                sa.text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_name='organization_settings' AND column_name='time_zone'"
                )
            )
        ).scalar_one() == 0
        # If audit validation failed after baseline conversion, that conversion rolled back too.
        if source == "audit":
            payload = (
                await connection.execute(
                    sa.text(
                        "SELECT payload FROM baseline_entries WHERE entity_type='assignments'"
                    )
                )
            ).scalar_one()
            assert payload["start_at"] == "2026-07-01T08:00:00"


async def test_csv_migration_preserves_real_postgres_instants_and_history(
    legacy_database,
):
    """Exercise archive locks, enum/array bindings and atomic inserts on migrated PostgreSQL."""
    from app.models.baseline import Baseline
    from app.models.calendar import ResourceWorkProfile, WorkWeekProfile
    from app.models.resource import InfrastructureResource, PersonalResource
    from app.models.resource_group import ResourceGroup
    from app.models.user import User
    from app.services.import_export.csv_format import _read_csv
    from app.services.import_export.csv_transfer import (
        export_area,
        export_migration,
        import_area_rows,
        import_migration,
    )

    url, source_engine = legacy_database
    assert (await migrate(url, "head")).returncode == 0
    admin_engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    target_name = "capado_csv_test_" + uuid4().hex
    target_url = (
        sa.engine.make_url(url)
        .set(database=target_name)
        .render_as_string(hide_password=False)
    )
    async with admin_engine.connect() as connection:
        await connection.execute(sa.text(f'CREATE DATABASE "{target_name}"'))
        await connection.execute(
            sa.text(f"ALTER DATABASE \"{target_name}\" SET timezone TO 'Asia/Tokyo'")
        )
    target_engine = create_async_engine(target_url)
    try:
        result = await migrate(target_url, "head")
        assert result.returncode == 0, result.stderr
        async with AsyncSession(source_engine, expire_on_commit=False) as source:
            booking = await source.get(Assignment, BOOKING)
            infra_group = ResourceGroup(name="Machines", resource_type="infrastructure")
            people_group = ResourceGroup(name="People", resource_type="personal")
            source.add_all([infra_group, people_group])
            await source.flush()
            profile = WorkWeekProfile(name="Infrastructure hours", monday_minutes=360)
            source.add(profile)
            await source.flush()
            binding = ResourceWorkProfile(
                group_id=infra_group.id,
                profile_id=profile.id,
                valid_from=booking.start_at.date(),
            )
            source.add(binding)
            person = PersonalResource(name="Planner", group_id=people_group.id)
            source.add_all(
                [
                    person,
                    InfrastructureResource(
                        id=booking.resource_id, name="Machine", group_id=infra_group.id
                    ),
                ]
            )
            await source.flush()
            editor = User(
                email="editor@example.test",
                name="Planner",
                role="editor",
                password_hash="excluded",
                resource_id=person.id,
                scope_group_ids=[people_group.id],
                scope_project_ids=[PROJECT],
            )
            source.add(editor)
            booking.start_at = datetime(2026, 7, 1, 6, 15, 23, 123456, UTC)
            booking.end_at = datetime(2026, 7, 1, 8, 45, 23, 654321, UTC)
            await source.commit()
            editor_id, people_group_id, person_id = (
                editor.id,
                people_group.id,
                person.id,
            )
            archive = await export_migration(source)
        async with AsyncSession(target_engine, expire_on_commit=False) as target:
            admin = User(
                email="bootstrap@example.test",
                name="Admin",
                role="admin",
                password_hash="unusable",
            )
            target.add(admin)
            await target.commit()
            result = await import_migration(target, archive, admin.id)
            assert result.errors == []
            assert not result.conflict_check_failed
            restored = await target.get(Assignment, BOOKING)
            assert restored.start_at == datetime(2026, 7, 1, 6, 15, 23, 123456, UTC)
            assert restored.end_at == datetime(2026, 7, 1, 8, 45, 23, 654321, UTC)
            assert (await target.get(Baseline, BASELINE)).created_by is None
            restored_editor = await target.get(User, editor_id)
            assert restored_editor.scope_group_ids == [people_group_id]
            assert restored_editor.scope_project_ids == [PROJECT]
            assert restored_editor.resource_id == person_id
            assert (
                restored_editor.password_hash == ""
                and restored_editor.must_change_password
            )
            assert (
                await target.execute(sa.text("SELECT count(*) FROM baseline_entries"))
            ).scalar_one() == 2
            # Standalone updates exercise the same writer, real UUID arrays and
            # timezone-aware values after the destination is already populated.
            content = await export_area(target, "assignments")
            rows = _read_csv(content)
            start_column = rows[1].index("start_at")
            rows[2][start_column] = "2026-07-01T15:30:23.222333+09:00"
            changed = await import_area_rows(target, "assignments", rows, admin.id)
            assert not changed.errors and changed.updated == 1
            await target.refresh(restored)
            assert restored.start_at == datetime(2026, 7, 1, 6, 30, 23, 222333, UTC)
            infra_rows = _read_csv(await export_area(target, "infrastructure"))
            assert any(row[0] == "resource_work_profiles" for row in infra_rows[2:])
            updated_infra = await import_area_rows(
                target, "infrastructure", infra_rows, admin.id
            )
            assert not updated_infra.errors
            # A populated target rejects repeat restores rather than duplicating data.
            again = await import_migration(target, archive, admin.id)
            assert again.created == 0 and "empty destination" in again.errors[0]
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(
                sa.text(f'DROP DATABASE "{target_name}" WITH (FORCE)')
            )
        await admin_engine.dispose()
