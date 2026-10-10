"""Restore a real PostgreSQL dump, upgrade it and start the native application."""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import models as m
from app.models.base import ORMModel
from app.services.auth_service import hash_password
from app.services.conflict_refresh import refresh_resources
from tests.test_csv_migration import source  # noqa: F401
from tests.test_utc_migration_postgres import (  # noqa: F401
    BOOKING,
    ROOT,
    legacy_database,
    migrate,
)


@pytest.fixture
async def db_session(legacy_database):
    """Use only the fixture's disposable database at the actual main revision 002."""
    url, engine = legacy_database
    migrated = await migrate(url, "002")
    assert migrated.returncode == 0, migrated.stderr
    async with AsyncSession(engine, expire_on_commit=False) as session:
        # Complete the old migration fixture's polymorphic booking reference.
        assert sa.engine.make_url(url).database.startswith("capado_timezone_test_")
        # The CSV source fixture supplies its own synthetic singleton settings.
        await session.execute(sa.delete(m.OrganizationSettings))
        booking = await session.get(m.Assignment, BOOKING)
        group = m.ResourceGroup(
            name="Legacy machine group", resource_type="infrastructure"
        )
        session.add(group)
        await session.flush()
        session.add(
            m.InfrastructureResource(
                id=booking.resource_id, name="Legacy machine", group_id=group.id
            )
        )
        await session.commit()
        yield session


async def database_records(engine):
    """Compare every application table and column, including blobs and auth data."""
    async with engine.connect() as connection:
        records = {}
        for name, table in sorted(ORMModel.metadata.tables.items()):
            statement = table.select().order_by(*table.primary_key.columns)
            records[name] = [
                dict(row) for row in (await connection.execute(statement)).mappings()
            ]
        return records


async def pg_tool(tool, url, *options, data=None):
    """Use matching native clients or the explicitly configured test PG container."""
    parsed = sa.engine.make_url(url)
    assert parsed.database.startswith(("capado_timezone_test_", "capado_restore_test_"))
    container = os.environ.get("TEST_POSTGRES_CONTAINER")
    env = {**os.environ, "PGPASSWORD": parsed.password or ""}
    if container:
        executable = shutil.which("docker")
        assert executable, "Docker is required with TEST_POSTGRES_CONTAINER"
        command = [
            executable,
            "exec",
            "-i",
            "--env",
            "PGPASSWORD",
            container,
            tool,
            "--host=127.0.0.1",
            "--port=5432",
        ]
    else:
        executable = shutil.which(tool)
        assert executable, (
            "Install matching PostgreSQL clients or set TEST_POSTGRES_CONTAINER to the test service container"
        )
        command = [executable, f"--host={parsed.host}", f"--port={parsed.port or 5432}"]
    command.extend([f"--username={parsed.username}", *options])
    result = await asyncio.to_thread(
        subprocess.run,
        command,
        input=data,
        capture_output=True,
        env=env,
        cwd=ROOT,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


async def verify_running_application(url, refs, password, tmp_path):
    """Start the actual lifespan/migrations, authenticate, then read restored data."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    env = {
        "PATH": str(Path(sys.executable).parent)
        + os.pathsep
        + os.environ.get("PATH", ""),
        "ENVIRONMENT": "test",
        "DATABASE_URL": url,
        "JWT_SECRET_KEY": "offline-restored-capado-test-only",
    }
    log_path = tmp_path / "restored-startup.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", timeout=10
            ) as client:
                async with asyncio.timeout(30):
                    while True:
                        assert process.poll() is None, log_path.read_text()
                        try:
                            if (await client.get("/api/health")).status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(0.05)
                login = await client.post(
                    "/api/auth/login",
                    json={"email": "admin@example.test", "password": password},
                )
                assert login.status_code == 200
                headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
                for path in (
                    "/api/projects",
                    "/api/assignments",
                    "/api/work-week-profiles",
                    "/api/baselines",
                    "/api/users/me",
                    "/api/capacity/overview?startDate=2099-01-05&endDate=2099-01-08",
                    f"/api/resources/personal/{refs['person']}",
                ):
                    response = await client.get(path, headers=headers)
                    assert response.status_code == 200, (path, response.text)
                assert (
                    await client.get(
                        f"/api/resources/personal/{refs['person']}", headers=headers
                    )
                ).json()["id"] == str(refs["person"])
                editor = await client.post(
                    "/api/auth/login",
                    json={"email": "editor@example.test", "password": password},
                )
                assert editor.status_code == 200
                denied = await client.put(
                    f"/api/resources/personal/{refs['person']}",
                    json={"group_id": str(refs["forbidden_group"])},
                    headers={
                        "Authorization": f"Bearer {editor.json()['access_token']}"
                    },
                )
                assert denied.status_code == 403
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
    startup = log_path.read_text()
    assert "Database migrations applied successfully" in startup
    assert "Backend ready" in startup


@pytest.mark.parametrize("backup_revision", ["002", "head"])
async def test_real_dump_restore_upgrade_and_authenticated_application(
    legacy_database, db_session, source, tmp_path, backup_revision
):
    source_url, source_engine = legacy_database
    password = "restore-only-synthetic-test-password"
    admin = await db_session.get(m.User, source["admin"])
    admin.password_hash = hash_password(password)
    editor = await db_session.scalar(
        sa.select(m.User).where(m.User.email == "editor@example.test")
    )
    editor.password_hash = hash_password(password)
    person = await db_session.get(m.PersonalResource, source["person"])
    group = await db_session.get(m.ResourceGroup, person.group_id)
    source["forbidden_group"] = group.parent_id
    # Real startup must remain offline: no scheduled maintenance or mail delivery.
    await db_session.execute(
        sa.update(m.OrganizationSettings).values(
            scheduler_enabled=False, smtp_enabled=False
        )
    )
    db_session.add(
        m.RefreshToken(
            user_id=admin.id,
            token_hash="f" * 64,
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()
    await refresh_resources(db_session, [source["person"], source["machine"]])
    if backup_revision == "head":
        original_data = await database_records(source_engine)
        upgraded_source = await migrate(source_url, "head")
        assert upgraded_source.returncode == 0, upgraded_source.stderr
        assert await database_records(source_engine) == original_data
    before = await database_records(source_engine)
    for name in (
        "projects",
        "work_packages",
        "personal_resources",
        "infrastructure_resources",
        "assignments",
        "work_week_profiles",
        "resource_work_profiles",
        "users",
        "audit_log",
        "baselines",
        "baseline_entries",
        "work_package_dependencies",
        "conflicts",
        "conflict_assignments",
        "refresh_tokens",
    ):
        assert before[name], name
    async with source_engine.connect() as connection:
        assert await connection.scalar(
            sa.text("SELECT version_num FROM alembic_version")
        ) == ("002" if backup_revision == "002" else "004")

    dump = await pg_tool(
        "pg_dump",
        source_url,
        f"--dbname={sa.engine.make_url(source_url).database}",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
    )
    assert dump.startswith(b"PGDMP")
    (tmp_path / "synthetic-backup.dump").write_bytes(dump)
    contents = await pg_tool("pg_restore", source_url, "--list", data=dump)
    assert contents.count(b"TABLE DATA") >= len(ORMModel.metadata.tables)

    server = os.environ["TEST_POSTGRES_URL"]
    admin_engine = create_async_engine(server, isolation_level="AUTOCOMMIT")
    name = "capado_restore_test_" + uuid4().hex
    restored_url = (
        sa.engine.make_url(server)
        .set(database=name)
        .render_as_string(hide_password=False)
    )
    restored_engine = create_async_engine(restored_url)
    async with admin_engine.connect() as connection:
        await connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    try:
        await pg_tool(
            "pg_restore",
            restored_url,
            f"--dbname={name}",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "--single-transaction",
            data=dump,
        )
        assert await database_records(restored_engine) == before
        upgraded = await migrate(restored_url, "head")
        assert upgraded.returncode == 0, upgraded.stderr
        async with restored_engine.connect() as connection:
            assert (
                await connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                )
                == "004"
            )
            assert (
                await connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_constraint WHERE conname IN ('ex_work_profiles_resource_period','ex_work_profiles_group_period')"
                    )
                )
                == 2
            )
        assert await database_records(restored_engine) == before
        await verify_running_application(restored_url, source, password, tmp_path)
        after_api = await database_records(restored_engine)
        assert len(after_api["refresh_tokens"]) == len(before["refresh_tokens"]) + 2
        old_token_ids = {row["id"] for row in before["refresh_tokens"]}
        new_token_ids = {
            row["id"] for row in after_api["refresh_tokens"]
        } - old_token_ids
        old_audit_ids = {row["id"] for row in before["audit_log"]}
        new_audit = [
            row for row in after_api["audit_log"] if row["id"] not in old_audit_ids
        ]
        assert len(new_audit) == 2
        assert {row["entity_id"] for row in new_audit} == new_token_ids
        assert all(
            row["entity_type"] == "refresh_tokens" and row["action"] == "created"
            for row in new_audit
        )
        after_api["audit_log"] = [
            row for row in after_api["audit_log"] if row["id"] in old_audit_ids
        ]
        after_api["refresh_tokens"] = before["refresh_tokens"]
        assert after_api == before
        # Restore/startup must never change the source database either.
        assert await database_records(source_engine) == before
    finally:
        await restored_engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin_engine.dispose()
