"""Reproduce the PR85 overview fixtures and profile actual PostgreSQL reads.

Manual: TEST_POSTGRES_URL=<dedicated local test admin> uv run python -m
 tests.benchmark_project_overview --output /tmp/overview-before.json [--calendar]
Only a newly created capado_overview_benchmark_ database is written or dropped.
"""

import argparse
import asyncio
import cProfile
import hashlib
import json
import os
import pstats
import statistics
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid4, uuid5

BACKEND = Path(__file__).resolve().parents[1]
SHAPES = [("small", 3, 2, 2), ("medium", 20, 5, 8), ("large", 60, 8, 20)]


def stable_id(name):
    return uuid5(NAMESPACE_URL, "capado-overview-fixture/" + name)


async def seed(session, calendar):
    from app import models as m

    group = m.ResourceGroup(id=stable_id("group"), name="Synthetic review group")
    session.add(group)
    if calendar:
        session.add(
            m.WorkWeekProfile(id=stable_id("profile"), name="Standard", is_default=True)
        )
    await session.flush()
    cases = []
    # Cumulative data also checks selected projects ignore unrelated records.
    for size, count, packages_per_project, people_count in SHAPES:
        projects = [
            m.Project(
                id=stable_id(f"{size}/project/{i}"),
                name=f"{size} {i}",
                start_date=date(2026, 1, 5),
                end_date=date(2026, 3, 27),
            )
            for i in range(count)
        ]
        people = [
            m.PersonalResource(
                id=stable_id(f"{size}/person/{i}"),
                name=f"{size} person {i}",
                group_id=group.id,
            )
            for i in range(people_count)
        ]
        session.add_all([*projects, *people])
        await session.flush()
        packages = [
            m.WorkPackage(
                id=stable_id(f"{size}/project/{i}/package/{j}"),
                project_id=project.id,
                name=f"{size} package {j}",
                start_date=project.start_date + timedelta(days=j * 7),
                end_date=project.start_date + timedelta(days=j * 7 + 4),
                lead_time_working_days=3,
            )
            for i, project in enumerate(projects)
            for j in range(packages_per_project)
        ]
        session.add_all(packages)
        await session.flush()
        assignments = [
            m.Assignment(
                id=stable_id(f"{size}/assignment/{i}"),
                resource_id=people[i % people_count].id,
                resource_type="personal",
                work_package_id=package.id,
                start_date=package.start_date,
                end_date=package.end_date,
                allocation_percent=25,
            )
            for i, package in enumerate(packages)
        ]
        session.add_all(assignments)
        await session.flush()
        for i, assignment in enumerate(assignments[::10]):
            conflict = m.Conflict(
                id=stable_id(f"{size}/conflict/{i}"),
                resource_id=assignment.resource_id,
                resource_type="personal",
                start_date=assignment.start_date,
                end_date=assignment.end_date,
                total_assigned_percent=150,
                available_percent=100,
            )
            session.add(conflict)
            await session.flush()
            session.add(
                m.ConflictAssignment(
                    conflict_id=conflict.id, assignment_id=assignment.id
                )
            )
        await session.commit()
        cases.append((size, projects, len(packages), people_count))
    return cases


async def run(admin_url, output, calendar):
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.services.project_overview_service import ProjectOverviewService

    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    name = "capado_overview_benchmark_" + uuid4().hex
    url = (
        sa.engine.make_url(admin_url)
        .set(database=name)
        .render_as_string(hide_password=False)
    )
    engine = None
    created = False
    try:
        async with admin.connect() as connection:
            await connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
            created = True
        # env.py uses explicit DATABASE_URL and models, with no dotenv reader.
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env={**os.environ, "DATABASE_URL": url},
            check=True,
            capture_output=True,
        )
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            cases = await seed(session, calendar)
        statements = []
        sa.event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            lambda _c, _r, sql, *_: statements.append(sql),
        )
        results = []
        for size, projects, package_count, people_count in cases:
            ids = [project.id for project in projects]

            async def overview(session, ids=ids):
                return await ProjectOverviewService(session).get_overview(
                    ids, today=date(2026, 1, 12)
                )

            async with AsyncSession(engine) as session:
                await overview(
                    session
                )  # Warm code/driver separately from measurements.
            walls, cpus, counts, hashes = [], [], [], []
            for _ in range(5):
                async with AsyncSession(engine) as session:
                    await session.execute(sa.text("SELECT 1"))
                    statements.clear()
                    wall, cpu = time.perf_counter(), time.process_time()
                    response = await overview(session)
                    cpus.append((time.process_time() - cpu) * 1000)
                    walls.append((time.perf_counter() - wall) * 1000)
                    counts.append(len(statements))
                    payload = sorted(
                        response.model_dump(mode="json")["projects"],
                        key=lambda p: p["project_id"],
                    )
                    hashes.append(
                        hashlib.sha256(
                            json.dumps(payload, sort_keys=True).encode()
                        ).hexdigest()
                    )
            assert len(set(hashes)) == 1, "Non-deterministic overview payload"
            profile = cProfile.Profile()
            async with AsyncSession(engine) as session:
                await session.execute(sa.text("SELECT 1"))
                profile.enable()
                await overview(session)
                profile.disable()
            profile_path = output.with_name(f"{output.stem}-{size}.pstats")
            profile.dump_stats(profile_path)
            stats = pstats.Stats(profile)
            top = sorted(
                stats.stats.items(), key=lambda item: item[1][2], reverse=True
            )[:15]
            result = {
                "size": size,
                "projects": len(projects),
                "work_packages": package_count,
                "resources": people_count,
                "median_ms": round(statistics.median(walls), 2),
                "cpu_ms": round(statistics.median(cpus), 2),
                "queries": counts,
                "sha256": hashes[0],
                "profile": str(profile_path),
                "top_self": [
                    {
                        "function": f"{Path(key[0]).name}:{key[1]}:{key[2]}",
                        "calls": value[1],
                        "self_ms": round(value[2] * 1000, 2),
                        "cumulative_ms": round(value[3] * 1000, 2),
                    }
                    for key, value in top
                ],
            }
            results.append(result)
            print(
                json.dumps({k: v for k, v in result.items() if k != "top_self"}),
                flush=True,
            )
        output.write_text(
            json.dumps({"calendar": calendar, "cases": results}, indent=2) + "\n"
        )
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            async with admin.connect() as connection:
                await connection.execute(
                    sa.text(f'DROP DATABASE "{name}" WITH (FORCE)')
                )
        await admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--calendar",
        action="store_true",
        help="Also exercise a standard working-week profile; original PR85 fixtures omit it",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    from sqlalchemy.engine import make_url

    admin_url = os.environ.get("TEST_POSTGRES_URL", "")
    if not admin_url or make_url(admin_url).host not in ("127.0.0.1", "localhost"):
        parser.error(
            "TEST_POSTGRES_URL must name a dedicated loopback PostgreSQL test administrator"
        )
    # Services import from an empty cwd with explicit non-operational settings.
    # No developer .env, inherited SMTP/OIDC credentials, or production API starts.
    os.environ.clear()
    os.environ.update(
        ENVIRONMENT="test",
        DATABASE_URL=admin_url,
        JWT_SECRET_KEY="overview-benchmark-only-never-production-auth",
        PYTHONPATH=str(BACKEND),
    )
    sys.path.insert(0, str(BACKEND))
    with TemporaryDirectory(prefix="capado-overview-profile-") as directory:
        os.chdir(directory)
        asyncio.run(run(admin_url, output, args.calendar))


if __name__ == "__main__":
    main()
