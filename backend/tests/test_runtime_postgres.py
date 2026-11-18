"""Exercise the optional backend commands against migrated PostgreSQL."""

import asyncio
import os
import sys
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scheduled_job_run import JobRunStatus, ScheduledJobRun
from app.services.conflict_refresh import CONFLICT_CHECK_JOB
from app.services.scheduler import lock_maintenance_for_migration
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401

BACKEND_ROOT = Path(__file__).resolve().parents[1]


async def _start(url: str, *args: str) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.runtime",
        *args,
        cwd=BACKEND_ROOT,
        env={**os.environ, "ENVIRONMENT": "test", "DATABASE_URL": url},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )


async def _run(url: str, *args: str) -> tuple[int | None, str]:
    process = await _start(url, *args)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=45)
        return process.returncode, output.decode()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def test_api_requires_migration_and_loses_readiness_if_revision_changes(
    legacy_database,
):
    url, engine = legacy_database
    code, log = await _run(url, "api", "--host", "127.0.0.1", "--port", "0")
    assert code != 0
    assert "Database schema mismatch: found 001" in log
    async with engine.connect() as connection:
        assert (
            await connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "001"
        )

    for code, log in await asyncio.gather(_run(url, "migrate"), _run(url, "migrate")):
        assert code == 0, log

    # Exercise an actual Uvicorn restart and HTTP check after the failed startup.
    api = await _start(url, "api", "--host", "127.0.0.1", "--port", "0")
    try:
        assert api.stdout is not None
        async with asyncio.timeout(30):
            while line := await api.stdout.readline():
                if b"Uvicorn running on http://" in line:
                    origin = line.decode().split("Uvicorn running on ", 1)[1].split()[0]
                    break
            else:
                raise AssertionError("API exited before listening.")
        async with httpx.AsyncClient(base_url=origin) as client:
            assert (await client.get("/api/health")).json() == {"status": "ok"}
            async with AsyncSession(engine) as session:
                assert await session.scalar(select(ScheduledJobRun.id).limit(1)) is None
                await session.execute(
                    text("UPDATE alembic_version SET version_num = 'future'")
                )
                await session.commit()
            health = await client.get("/api/health")
            assert health.status_code == 503
            assert health.json() == {"status": "not_ready"}
    finally:
        if api.returncode is None:
            api.terminate()
            try:
                await asyncio.wait_for(api.communicate(), timeout=10)
            except TimeoutError:
                api.kill()
                await api.communicate()


async def test_maintenance_respects_shared_locks_and_skips_completed_work(
    legacy_database,
):
    url, engine = legacy_database
    code, log = await _run(url, "migrate")
    assert code == 0, log

    async with AsyncSession(engine) as importing:
        await lock_maintenance_for_migration(importing)
        code, log = await _run(url, "maintain")
        assert code == 0, log
        assert "0 jobs started" in log
        assert await importing.scalar(select(ScheduledJobRun.id).limit(1)) is None

    for code, log in await asyncio.gather(_run(url, "maintain"), _run(url, "maintain")):
        assert code == 0, log
    code, log = await _run(url, "maintain")
    assert code == 0, log
    async with AsyncSession(engine) as session:
        statuses = await session.scalars(
            select(ScheduledJobRun.status).where(
                ScheduledJobRun.job_name == CONFLICT_CHECK_JOB
            )
        )
        assert statuses.all() == [JobRunStatus.succeeded]
