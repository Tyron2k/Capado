"""Folder deletion audit and customer inheritance against migrated PostgreSQL."""

from datetime import date
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import models as m
from app.models.project import ProjectFolder
from app.services.project_folder_service import ProjectFolderService
from tests.test_project_integrity import client_for
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401


async def seed(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        admin = m.User(
            name="Audit admin",
            email="folder-audit@example.test",
            password_hash="test-only",
            role="admin",
        )
        customers = [m.Customer(name=f"Customer {i}") for i in range(3)]
        session.add_all([admin, *customers])
        await session.flush()
        parent = ProjectFolder(name="Parent", customer_id=customers[0].id)
        session.add(parent)
        await session.flush()
        removed = ProjectFolder(
            name="Removed", parent_id=parent.id, customer_id=customers[1].id
        )
        session.add(removed)
        await session.flush()
        child = ProjectFolder(name="Child", parent_id=removed.id)
        session.add(child)
        await session.flush()
        projects = [
            m.Project(
                name=name,
                folder_id=folder,
                customer_id=customer,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 2, 1),
            )
            for name, folder, customer in [
                ("Direct", removed.id, None),
                ("Explicit", removed.id, customers[2].id),
                ("Inherited", child.id, None),
            ]
        ]
        session.add_all(projects)
        await session.commit()
        return SimpleNamespace(
            admin=admin.id,
            parent=parent.id,
            removed=removed.id,
            child=child.id,
            projects=[p.id for p in projects],
            customers=[c.id for c in customers],
        )


@pytest.mark.parametrize("fail", [False, True])
async def test_folder_delete_audits_reparenting_and_rolls_everything_back(
    resource_database, fail
):
    data = await seed(resource_database)

    def broken(session, *_):
        if session.info.get("folder-fault"):
            raise RuntimeError("Failure after the folder changes were flushed")

    def mark(session, *_):
        if any(
            isinstance(obj, ProjectFolder) and obj.id == data.removed
            for obj in session.deleted
        ):
            session.info["folder-fault"] = True

    if fail:
        sa.event.listen(Session, "before_flush", mark)
        sa.event.listen(Session, "after_flush_postexec", broken)
    try:
        async with client_for(resource_database, data.admin) as client:
            before = [
                (await client.get(f"/api/projects/{pid}")).json()
                for pid in data.projects
            ]
            response = await client.delete(f"/api/project-folders/{data.removed}")
            after = [
                (await client.get(f"/api/projects/{pid}")).json()
                for pid in data.projects
            ]
        assert response.status_code == (500 if fail else 200), response.text
    finally:
        if fail:
            sa.event.remove(Session, "before_flush", mark)
            sa.event.remove(Session, "after_flush_postexec", broken)
    async with AsyncSession(resource_database) as session:
        logs = list(
            (
                await session.scalars(
                    sa.select(m.AuditLog).where(m.AuditLog.actor_id == data.admin)
                )
            ).all()
        )
        if fail:
            assert logs == []
            assert before == after
            assert await session.get(ProjectFolder, data.removed) is not None
            assert (
                await session.get(ProjectFolder, data.child)
            ).parent_id == data.removed
        else:
            assert response.json() == {"projects_unfiled": 2, "subfolders_moved": 1}
            assert await session.get(ProjectFolder, data.removed) is None
            assert (
                await session.get(ProjectFolder, data.child)
            ).parent_id == data.parent
            assert [p["customer_name"] for p in before] == [
                "Customer 1",
                "Customer 2",
                "Customer 1",
            ]
            assert [p["customer_name"] for p in after] == [
                None,
                "Customer 2",
                "Customer 0",
            ]
            changes = {log.entity_id: log for log in logs}
            for pid in data.projects[:2]:
                assert changes[pid].changes == {
                    "folder_id": {"from": str(data.removed), "to": None}
                }
                assert changes[pid].action == "updated"
            assert changes[data.child].changes == {
                "parent_id": {"from": str(data.removed), "to": str(data.parent)}
            }
            assert changes[data.removed].action == "deleted"
            assert len(logs) == 4


async def test_folder_audit_query_count_does_not_grow_per_project(resource_database):
    data = await seed(resource_database)
    async with AsyncSession(resource_database) as session:
        session.add_all(
            [
                m.Project(
                    name=f"Extra {i}",
                    folder_id=data.removed,
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 2, 1),
                )
                for i in range(30)
            ]
        )
        await session.commit()
    statements = []

    def record(_conn, _cursor, sql, *_):
        statements.append(sql)

    sa.event.listen(resource_database.sync_engine, "before_cursor_execute", record)
    try:
        async with AsyncSession(resource_database, expire_on_commit=False) as session:
            from app.services.audit import set_actor

            set_actor(session, data.admin)
            assert await ProjectFolderService(session).delete(data.removed) == (32, 1)
    finally:
        sa.event.remove(resource_database.sync_engine, "before_cursor_execute", record)
    assert len(statements) <= 12, statements
