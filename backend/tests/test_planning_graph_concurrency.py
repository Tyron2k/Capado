"""Force competing graph snapshots, or a contender at the new lock boundary."""

import asyncio
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import (
    Project,
    ProjectFolder,
    WorkPackage,
    WorkPackageDependency,
)
from app.models.user import User
from app.services.project_folder_service import ProjectFolderService
from app.services.work_package_dependency_service import WorkPackageDependencyService
from tests.test_project_integrity import client_for
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401


@pytest.mark.parametrize("kind", ["dependency", "folder"])
async def test_opposing_http_writes_cannot_create_a_cycle(
    resource_database, monkeypatch, kind
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        user = User(
            name="Graph admin",
            email="graph-admin@example.test",
            role="admin",
            password_hash="test-only",
        )
        project = Project(
            name="Graph", start_date=date(2026, 1, 1), end_date=date(2026, 2, 1)
        )
        session.add_all([user, project])
        await session.flush()
        nodes = (
            [
                WorkPackage(
                    project_id=project.id,
                    name=name,
                    start_date=project.start_date,
                    end_date=project.end_date,
                )
                for name in ("A", "B")
            ]
            if kind == "dependency"
            else [ProjectFolder(name=name) for name in ("A", "B")]
        )
        session.add_all(nodes)
        await session.commit()
        user_id, project_id, ids = user.id, project.id, [node.id for node in nodes]
    service = (
        WorkPackageDependencyService if kind == "dependency" else ProjectFolderService
    )
    method = "_all_edges" if kind == "dependency" else "_tree"
    original_read = getattr(service, method)
    original_execute = AsyncSession.execute
    first_read = asyncio.Event()
    release_first = asyncio.Event()
    first_session = None

    async def read_snapshot(self, *args, **kwargs):
        nonlocal first_session
        snapshot = await original_read(self, *args, **kwargs)
        if first_session is None:
            first_session = self.session
            first_read.set()
            await asyncio.wait_for(release_first.wait(), timeout=8)
        else:
            # Old code reaches the second snapshot while the first is still uncommitted.
            release_first.set()
        return snapshot

    async def contender(self, statement, *args, **kwargs):
        if (
            first_session is not None
            and self is not first_session
            and "pg_advisory_xact_lock" in str(statement)
        ):
            # Fixed code must wait here, before reading the graph. Release the owner
            # without forcing both requests through a barrier inside the lock.
            release_first.set()
        return await original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(service, method, read_snapshot)
    monkeypatch.setattr(AsyncSession, "execute", contender)
    async with client_for(resource_database, user_id) as client:

        async def write(child, parent):
            if kind == "dependency":
                return await client.post(
                    f"/api/projects/{project_id}/work-packages/{child}/dependencies",
                    json={"predecessor_id": str(parent)},
                )
            return await client.put(
                f"/api/project-folders/{child}", json={"parent_id": str(parent)}
            )

        first = asyncio.create_task(write(ids[1], ids[0]))
        await asyncio.wait_for(first_read.wait(), timeout=8)
        second = asyncio.create_task(write(ids[0], ids[1]))
        responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=15)
    assert sorted(response.status_code for response in responses) == (
        [201, 400] if kind == "dependency" else [200, 400]
    ), [response.text for response in responses]
    assert (
        "circular" in responses[1].text.lower()
        if kind == "dependency"
        else "sub-folder" in responses[1].text.lower()
    )
    async with AsyncSession(resource_database) as session:
        if kind == "dependency":
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(WorkPackageDependency)
                    .where(WorkPackageDependency.successor_id.in_(ids))
                )
                == 1
            )
        else:
            rows = list(
                (
                    await session.scalars(
                        sa.select(ProjectFolder).where(ProjectFolder.id.in_(ids))
                    )
                ).all()
            )
            assert sum(folder.parent_id is not None for folder in rows) == 1


@pytest.mark.parametrize("held", ["dependencies", "folders"])
async def test_graph_locks_leave_other_graphs_and_metadata_writes_independent(
    resource_database, held
):
    from app.services.graph_locks import lock_graph

    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        user = User(
            name="Independent admin",
            email="independent@example.test",
            role="admin",
            password_hash="test-only",
        )
        folders = [
            ProjectFolder(name=name) for name in ("Independent A", "Independent B")
        ]
        session.add_all([user, *folders])
        await session.commit()
        uid = user.id
        a, b = [folder.id for folder in folders]
    async with AsyncSession(resource_database) as owner:
        await lock_graph(owner, held)
        async with client_for(resource_database, uid) as client:
            patch = (
                {"parent_id": str(a)}
                if held == "dependencies"
                else {"name": "Renamed without hierarchy change"}
            )
            response = await asyncio.wait_for(
                client.put(f"/api/project-folders/{b}", json=patch), timeout=5
            )
            assert response.status_code == 200, response.text
        await owner.rollback()


@pytest.mark.parametrize(
    "table,graph",
    [("work_package_dependencies", "dependencies"), ("project_folders", "folders")],
)
async def test_csv_destination_uses_the_same_structural_lock(
    resource_database, monkeypatch, table, graph
):
    from app.services.graph_locks import lock_graph
    from app.services.import_export import ENTITIES
    from app.services.import_export.csv_storage import _lock_destination

    entities = tuple(entity for entity in ENTITIES if entity.name == table)
    assert len(entities) == 1
    original = AsyncSession.execute
    contender_at_lock = asyncio.Event()
    async with (
        AsyncSession(resource_database) as owner,
        AsyncSession(resource_database) as importer,
    ):
        await lock_graph(owner, graph)
        pid = await importer.scalar(sa.text("SELECT pg_backend_pid()"))

        async def executing(self, statement, *args, **kwargs):
            if self is importer and "pg_advisory_xact_lock" in str(statement):
                contender_at_lock.set()
            return await original(self, statement, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "execute", executing)
        task = asyncio.create_task(_lock_destination(importer, entities))
        try:
            await asyncio.wait_for(contender_at_lock.wait(), timeout=5)
            # Observe the actual server wait rather than guessing from a slow coroutine.
            for _ in range(100):
                waiting = await owner.scalar(
                    sa.text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory' AND NOT granted)"
                    ),
                    {"pid": pid},
                )
                if waiting:
                    break
                await asyncio.sleep(0.01)
            assert waiting and not task.done()
            await owner.rollback()
            await asyncio.wait_for(task, timeout=5)
            await importer.rollback()
        finally:
            await owner.rollback()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_deleting_package_waits_for_dependency_validation_and_write(
    resource_database, monkeypatch
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        admin = User(
            name="Lifecycle admin",
            email="lifecycle@example.test",
            role="admin",
            password_hash="test-only",
        )
        project = Project(
            name="Lifecycle", start_date=date(2026, 1, 1), end_date=date(2026, 2, 1)
        )
        session.add_all([admin, project])
        await session.flush()
        nodes = [
            WorkPackage(
                project_id=project.id,
                name=name,
                start_date=project.start_date,
                end_date=project.end_date,
            )
            for name in ("A", "B")
        ]
        session.add_all(nodes)
        await session.commit()
        uid, pid, ids = admin.id, project.id, [n.id for n in nodes]
    inspected = asyncio.Event()
    resume = asyncio.Event()
    creating_session = None
    protected_session = None
    original_read = WorkPackageDependencyService._all_edges
    original_execute = AsyncSession.execute
    original_refresh = AsyncSession.refresh

    async def snapshot(self):
        nonlocal creating_session
        rows = await original_read(self)
        creating_session = self.session
        inspected.set()
        await asyncio.wait_for(resume.wait(), timeout=8)
        return rows

    async def executing(self, statement, *args, **kwargs):
        nonlocal protected_session
        row_lock = getattr(statement, "_for_update_arg", None)
        if row_lock is not None and row_lock.key_share:
            protected_session = self
        if (
            creating_session is not None
            and self is not creating_session
            and (
                protected_session is creating_session
                or "pg_advisory_xact_lock" in str(statement)
            )
        ):
            # The creator holds its endpoint rows: allow it to finish when deletion
            # enters. Without protection deletion must finish first to expose the race.
            resume.set()
        return await original_execute(self, statement, *args, **kwargs)

    async def refreshing(self, *args, **kwargs):
        # PR86 locks the package through refresh before its first execute call.
        # Observe that boundary too, without releasing an unprotected creator.
        if (
            creating_session is not None
            and self is not creating_session
            and protected_session is creating_session
        ):
            resume.set()
        return await original_refresh(self, *args, **kwargs)

    monkeypatch.setattr(WorkPackageDependencyService, "_all_edges", snapshot)
    monkeypatch.setattr(AsyncSession, "execute", executing)
    monkeypatch.setattr(AsyncSession, "refresh", refreshing)
    async with client_for(resource_database, uid) as client:
        creator = asyncio.create_task(
            client.post(
                f"/api/projects/{pid}/work-packages/{ids[1]}/dependencies",
                json={"predecessor_id": str(ids[0])},
            )
        )
        await asyncio.wait_for(inspected.wait(), timeout=8)

        async def removing():
            response = await client.delete(
                f"/api/projects/{pid}/work-packages/{ids[0]}"
            )
            resume.set()
            return response

        created, deleted = await asyncio.wait_for(
            asyncio.gather(creator, removing()), timeout=15
        )
    assert created.status_code == 201, created.text
    assert deleted.status_code == 204, deleted.text
    async with AsyncSession(resource_database) as session:
        assert await session.get(WorkPackage, ids[0]) is None
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(WorkPackageDependency)
                .where(WorkPackageDependency.successor_id == ids[1])
            )
            == 0
        )
