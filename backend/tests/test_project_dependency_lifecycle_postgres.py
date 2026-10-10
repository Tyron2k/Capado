"""Actual PostgreSQL lock ordering across dependency creation and project erasure."""

import asyncio
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.models.project import WorkPackageDependency
from app.services import project_service
from app.services.baseline_service import snapshot_payload
from app.services.work_package_dependency_service import WorkPackageDependencyService
from tests.test_project_integrity import client_for
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401


@pytest.mark.parametrize("first", ["dependency", "deletion"])
async def test_dependency_and_whole_project_deletion_serialize(
    resource_database, monkeypatch, first
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        own = m.Project(
            name="Deleted", start_date=date(2026, 1, 5), end_date=date(2026, 1, 9)
        )
        other = m.Project(
            name="Survives", start_date=own.start_date, end_date=own.end_date
        )
        editor = m.User(
            name="Scoped editor",
            email="project-race@example.test",
            password_hash="test-only",
            role="editor",
            scope_project_ids=[own.id, other.id],
        )
        baseline = m.Baseline(name="Historical")
        session.add_all([own, other, editor, baseline])
        await session.flush()
        nodes = [
            m.WorkPackage(
                name=project.name,
                project_id=project.id,
                start_date=project.start_date,
                end_date=project.end_date,
            )
            for project in (own, other)
        ]
        session.add_all(nodes)
        await session.flush()
        entry = m.BaselineEntry(
            baseline_id=baseline.id,
            entity_type="work_packages",
            entity_id=nodes[0].id,
            payload=snapshot_payload(nodes[0]),
        )
        session.add(entry)
        await session.commit()
        uid, deleted, kept = editor.id, own.id, other.id
        predecessor, successor = [node.id for node in nodes]
        entry_id, frozen = entry.id, entry.payload

    held, blocked, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}
    original_read = WorkPackageDependencyService._all_edges
    original_cleanup = project_service._delete_work_packages
    original_execute = AsyncSession.execute
    original_scalars = AsyncSession.scalars

    async def snapshot(self):
        rows = await original_read(self)
        if first == "dependency":
            held.set()  # Both endpoint key-share locks are already held.
            await asyncio.wait_for(release.wait(), timeout=8)
        return rows

    async def cleanup(session, packages):
        if first == "deletion":
            held.set()  # Project, package and editor scope locks are held.
            await asyncio.wait_for(release.wait(), timeout=8)
        return await original_cleanup(session, packages)

    async def executing(self, statement, *args, **kwargs):
        lock = getattr(statement, "_for_update_arg", None)
        if first == "deletion" and lock is not None and lock.key_share:
            pids["creator"] = (
                await original_execute(self, sa.text("SELECT pg_backend_pid()"))
            ).scalar_one()
            blocked.set()
        return await original_execute(self, statement, *args, **kwargs)

    async def scalars(self, statement, *args, **kwargs):
        lock = getattr(statement, "_for_update_arg", None)
        entities = [
            item.get("entity") for item in getattr(statement, "column_descriptions", [])
        ]
        if first == "dependency" and lock is not None and m.WorkPackage in entities:
            pids["deleter"] = (
                await original_execute(self, sa.text("SELECT pg_backend_pid()"))
            ).scalar_one()
            blocked.set()
        return await original_scalars(self, statement, *args, **kwargs)

    monkeypatch.setattr(WorkPackageDependencyService, "_all_edges", snapshot)
    monkeypatch.setattr(project_service, "_delete_work_packages", cleanup)
    monkeypatch.setattr(AsyncSession, "execute", executing)
    monkeypatch.setattr(AsyncSession, "scalars", scalars)
    tasks = []
    async with client_for(resource_database, uid) as client:

        async def create():
            return await client.post(
                f"/api/projects/{kept}/work-packages/{successor}/dependencies",
                json={"predecessor_id": str(predecessor)},
            )

        async def delete():
            return await client.delete(f"/api/projects/{deleted}")

        try:
            winner = asyncio.create_task(
                create() if first == "dependency" else delete()
            )
            tasks.append(winner)
            await asyncio.wait_for(held.wait(), timeout=8)
            contender = asyncio.create_task(
                delete() if first == "dependency" else create()
            )
            tasks.append(contender)
            await asyncio.wait_for(blocked.wait(), timeout=8)
            # Observe a real PostgreSQL lock wait, not timing a slow coroutine.
            pid = pids["deleter" if first == "dependency" else "creator"]
            async with AsyncSession(resource_database) as observer:
                async with asyncio.timeout(5):
                    while not await observer.scalar(
                        sa.text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)"
                        ),
                        {"pid": pid},
                    ):
                        await asyncio.sleep(0.01)
            assert not winner.done() and not contender.done()
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=8)
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    created, removed = results if first == "dependency" else results[::-1]
    assert removed.status_code == 204, removed.text
    assert created.status_code == (201 if first == "dependency" else 404), created.text
    async with AsyncSession(resource_database) as session:
        assert await session.get(m.Project, deleted) is None
        assert await session.get(m.WorkPackage, predecessor) is None
        assert await session.get(m.Project, kept) is not None
        assert await session.get(m.WorkPackage, successor) is not None
        assert (await session.get(m.User, uid)).scope_project_ids == [kept]
        assert (await session.get(m.BaselineEntry, entry_id)).payload == frozen
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(WorkPackageDependency)
            )
            == 0
        )
        logs = (
            await session.scalars(
                sa.select(m.AuditLog).where(
                    m.AuditLog.entity_type == "work_package_dependencies"
                )
            )
        ).all()
        assert {log.action for log in logs} == (
            {"created", "deleted"} if first == "dependency" else set()
        )
        assert all(log.actor_id == uid for log in logs)
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(m.AuditLog)
                .where(m.AuditLog.entity_id == deleted, m.AuditLog.action == "deleted")
            )
            == 1
        )
