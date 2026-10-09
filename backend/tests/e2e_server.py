"""Own a disposable PostgreSQL/API lifetime for actual browser workflows.

No public test endpoint, production credentials, or existing database is used.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import asyncpg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT.parent / "frontend" / ".e2e-state.json"
PASSWORD = "browser-tests-only"


def environment(url):
    # Allowlist excludes inherited SMTP/OIDC/developer configuration.
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "PYTHONPATH": str(ROOT),
        "ENVIRONMENT": "test",
        "DATABASE_URL": url,
        "JWT_SECRET_KEY": "capado-browser-tests-only-never-production-credentials",
        "CORS_ORIGINS": '["http://127.0.0.1:38600"]',
        "PYTHONUNBUFFERED": "1",
    }


def guarded_url(value):
    url = make_url(value)
    if url.host != "127.0.0.1" or not (url.database or "").startswith("capado_e2e_"):
        raise ValueError("Refusing to reset outside the disposable E2E namespace")
    return url


async def seed(value):
    guarded_url(value)
    os.environ.update(environment(value))
    # Import after configuration; use actual application models and auth.
    from sqlalchemy import text

    import app.models
    from app.database import async_session_factory, engine
    from app.models.base import ORMModel
    from app.models.calendar import WorkWeekProfile
    from app.models.project import Project, WorkPackage
    from app.models.resource import PersonalResource
    from app.models.resource_group import ResourceGroup
    from app.models.user import User
    from app.services.auth_service import hash_password

    today = datetime.now(UTC).astimezone(ZoneInfo("Europe/Berlin")).date()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=4)
    async with async_session_factory() as session:
        # Whole owned DB, in one transaction, blocking scheduler writes too.
        names = ", ".join(
            f'"{table.name}"' for table in ORMModel.metadata.sorted_tables
        )
        await session.execute(text(f"TRUNCATE {names} CASCADE"))
        group = ResourceGroup(name="Browser team")
        profile = WorkWeekProfile(name="Browser standard", is_default=True)
        session.add_all([group, profile])
        await session.flush()
        person = PersonalResource(name="Browser Person", group_id=group.id)
        owned = Project(name="Owned project", start_date=start, end_date=end)
        foreign = Project(name="Foreign project", start_date=start, end_date=end)
        session.add_all([person, owned, foreign])
        await session.flush()
        session.add_all(
            [
                WorkPackage(
                    name="Owned package",
                    project_id=owned.id,
                    start_date=start,
                    end_date=end,
                ),
                WorkPackage(
                    name="Second package",
                    project_id=owned.id,
                    start_date=start,
                    end_date=end,
                ),
                WorkPackage(
                    name="Foreign package",
                    project_id=foreign.id,
                    start_date=start,
                    end_date=end,
                ),
                User(
                    email="editor@example.test",
                    name="Browser Editor",
                    role="editor",
                    password_hash=hash_password(PASSWORD),
                    must_change_password=False,
                    scope_group_ids=[group.id],
                    scope_project_ids=[owned.id],
                ),
            ]
        )
        await session.commit()
        data = json.loads(STATE.read_text())
        data.update(
            start=str(start), end=str(end), foreign=str(foreign.id), owned=str(owned.id)
        )
        STATE.write_text(json.dumps(data))
    await engine.dispose()


async def serve():
    name = f"capado-e2e-{uuid4().hex[:12]}"
    database = f"capado_e2e_{uuid4().hex}"
    api = None
    stop = asyncio.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(signum, stop.set)
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--label",
                "capado.e2e=true",
                "-e",
                "POSTGRES_USER=browser",
                "-e",
                f"POSTGRES_PASSWORD={PASSWORD}",
                "-e",
                f"POSTGRES_DB={database}",
                "-p",
                "127.0.0.1::5432",
                "postgres:18",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        port = (
            subprocess.check_output(["docker", "port", name, "5432/tcp"], text=True)
            .strip()
            .split(":")[-1]
        )
        url = f"postgresql+asyncpg://browser:{PASSWORD}@127.0.0.1:{port}/{database}"
        for _ in range(120):
            try:
                connection = await asyncpg.connect(url.replace("+asyncpg", ""))
                await connection.close()
                break
            except (OSError, asyncpg.PostgresError):
                await asyncio.sleep(0.25)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        STATE.write_text(json.dumps({"url": url, "container": name}))
        api = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "38601",
            cwd=ROOT,
            env=environment(url),
        )
        waiter = asyncio.create_task(stop.wait())
        process = asyncio.create_task(api.wait())
        await asyncio.wait([waiter, process], return_when=asyncio.FIRST_COMPLETED)
        waiter.cancel()
        if api.returncode is not None and not stop.is_set():
            raise RuntimeError(f"API exited unexpectedly ({api.returncode})")
    finally:
        if api and api.returncode is None:
            api.terminate()
            with suppress(TimeoutError):
                await asyncio.wait_for(api.wait(), timeout=5)
            if api.returncode is None:
                api.kill()
                await api.wait()
        subprocess.run(
            ["docker", "rm", "--force", name], check=False, stdout=subprocess.DEVNULL
        )
        STATE.unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        asyncio.run(serve())
    elif sys.argv[1:] == ["reset"]:
        asyncio.run(seed(json.loads(STATE.read_text())["url"]))
    else:
        raise SystemExit("Usage: python -m tests.e2e_server {serve|reset}")
