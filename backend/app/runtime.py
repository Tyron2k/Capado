"""Optional backend commands using the same image as the combined server."""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from functools import cache
from pathlib import Path

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.database import DATABASE_URL, async_session_factory, engine, wait_for_db
from app.services.audit import register_audit_listener
from app.services.scheduler import run_due_jobs

logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def run_migrations() -> None:
    """Run the same Alembic upgrade as the combined server."""
    logger.info("Running database migrations...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=BACKEND_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(BACKEND_ROOT),
            "DATABASE_URL": DATABASE_URL,
        },
    )
    if result.returncode != 0:
        raise RuntimeError(f"Alembic migration failed: {result.stderr}")
    logger.info("Database migrations applied successfully.")


@cache
def _image_heads() -> frozenset[str]:
    return frozenset(ScriptDirectory(str(BACKEND_ROOT / "alembic")).get_heads())


class SchemaMismatch(RuntimeError):
    """The database revision does not match this image."""


async def require_current_schema() -> None:
    """Reject a missing, older, or newer schema without migrating it."""
    expected = _image_heads()
    async with engine.connect() as connection:
        heads = await connection.run_sync(
            lambda sync_connection: MigrationContext.configure(
                sync_connection
            ).get_current_heads()
        )
    if frozenset(heads) != expected:
        raise SchemaMismatch(
            f"Database schema mismatch: found {', '.join(sorted(heads)) or 'unversioned'}, "
            f"expected {', '.join(sorted(expected))}. Run migrations from the matching image before starting."
        )


async def _run_once(command: str) -> None:
    try:
        await wait_for_db()
        if command == "migrate":
            run_migrations()
            return
        await require_current_schema()
        register_audit_listener()
        async with async_session_factory() as session:
            started = await run_due_jobs(session, fail_on_error=True)
        logger.info("Maintenance pass complete (%d jobs started).", len(started))
    finally:
        await engine.dispose()


def main() -> None:
    """Start API-only or execute one migration or maintenance command."""
    parser = argparse.ArgumentParser(prog="python -m app.runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    api = commands.add_parser("api", help="serve the API on an already migrated schema")
    api.add_argument("--host", default="0.0.0.0")
    api.add_argument("--port", default=3001, type=int)
    commands.add_parser("migrate", help="upgrade the database to this image's schema")
    commands.add_parser("maintain", help="run a single pass of due maintenance jobs")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    if args.command == "api":
        import uvicorn

        # A supervisor would restart workers on schema mismatch instead of exiting.
        uvicorn.run(
            "app.main:create_api_app",
            factory=True,
            host=args.host,
            port=args.port,
            workers=1,
        )
    else:
        asyncio.run(_run_once(args.command))


if __name__ == "__main__":
    main()
