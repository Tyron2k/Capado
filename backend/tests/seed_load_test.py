"""Seed only the disposable Compose load-test database with benchmark fixtures."""

import asyncio
import subprocess
import sys

from sqlalchemy import func, select
from sqlalchemy.engine import make_url


async def main():
    from app.config import settings
    from app.database import async_session_factory, engine
    from app.models.project import Project
    from app.models.user import User
    from app.services.auth_service import hash_password
    from tests.benchmark_project_overview import seed

    url = make_url(settings.database_url)
    if (
        settings.environment != "test"
        or url.host != "db"
        or url.database != "capado_load_test"
        or url.username != "load_test"
    ):
        raise ValueError("Refusing to seed outside the isolated load-test database")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    try:
        async with async_session_factory() as session:
            if await session.scalar(select(func.count()).select_from(Project)) or (
                await session.scalar(select(func.count()).select_from(User))
            ):
                raise ValueError(
                    "Load-test database must be empty; nothing was replaced"
                )
            await seed(session, calendar=True)
            session.add(
                User(
                    email="load@example.test",
                    name="Local load-test reader",
                    role="viewer",
                    password_hash=hash_password("disposable-load-test-only"),
                    must_change_password=False,
                )
            )
            await session.commit()
        print("Seeded 83 projects, 586 packages, 30 people and 586 bookings")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
