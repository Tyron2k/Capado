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
