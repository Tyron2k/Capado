"""Nested HTTP writes and project creation against real ORM transactions."""

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.database import get_session
from app.main import app
from app.models.audit import AuditLog
from app.models.project import Project, WorkPackage, WorkPackageDependency
from app.models.user import User
from app.services.audit import _before_flush, register_audit_listener, set_actor
from app.services.permissions import get_current_user
from app.services.project_service import ProjectService
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401


async def seed(session):
    projects = [
        Project(name=n, start_date=date(2026, 1, 1), end_date=date(2026, 2, 1))
        for n in ("Own", "Foreign")
    ]
    session.add_all(projects)
    await session.flush()
    packages = [
        WorkPackage(
            project_id=p.id,
            name=f"{p.name}-{i}",
            start_date=p.start_date,
            end_date=p.end_date,
        )
        for p in projects
        for i in range(2)
    ]
    session.add_all(packages)
    editor = User(
        name="Editor",
        email="integrity-editor@example.test",
        password_hash="test-only",
        role="editor",
        scope_project_ids=[projects[0].id],
    )
    admin = User(
        name="Admin",
        email="integrity-admin@example.test",
        password_hash="test-only",
        role="admin",
    )
    viewer = User(
        name="Viewer",
        email="integrity-viewer@example.test",
        password_hash="test-only",
        role="viewer",
    )
    session.add_all([editor, admin, viewer])
    await session.flush()
    dependency = WorkPackageDependency(
        predecessor_id=packages[3].id, successor_id=packages[2].id
    )
    session.add(dependency)
    await session.commit()
    return SimpleNamespace(
        own=projects[0].id,
        foreign=projects[1].id,
        packages=[wp.id for wp in packages],
        dependency=dependency.id,
        editor=editor.id,
        admin=admin.id,
        viewer=viewer.id,
    )


@asynccontextmanager
async def client_for(engine, user_id):
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async def identity(session: AsyncSession = Depends(get_session)):
        user = await session.get(User, user_id)
        set_actor(session, user_id)
        return user

    old = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_current_user] = identity
    registered = sa.event.contains(Session, "before_flush", _before_flush)
    register_audit_listener()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)
        if not registered:
            sa.event.remove(Session, "before_flush", _before_flush)


@pytest.mark.parametrize("role", ["editor", "admin"])
@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_wrong_project_cannot_address_a_work_package(db_session, role, method):
    data = await seed(db_session)
    async with client_for(db_session.bind, getattr(data, role)) as client:
        response = await client.request(
            method,
            f"/api/projects/{data.own}/work-packages/{data.packages[2]}",
            **({"json": {"name": "Tampered"}} if method == "PUT" else {}),
        )
    assert response.status_code == 404
    async with AsyncSession(db_session.bind) as check:
        assert (await check.get(WorkPackage, data.packages[2])).name == "Foreign-0"
        assert (
            await check.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == data.packages[2])
            )
            == 0
        )


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
async def test_actual_foreign_project_remains_forbidden_for_editor(db_session, method):
    data = await seed(db_session)
    async with client_for(db_session.bind, data.editor) as client:
        response = await client.request(
            method,
            f"/api/projects/{data.foreign}/work-packages/{data.packages[2]}",
            **({"json": {"name": "Tampered"}} if method == "PUT" else {}),
        )
        assert response.status_code == 403
        assert (
            await client.get(
                f"/api/projects/{data.foreign}/work-packages/{data.packages[2]}"
            )
        ).status_code == 200


@pytest.mark.parametrize(
    "wrong_parent,method",
    [("project", method) for method in ("GET", "POST", "PUT", "DELETE")]
    + [("successor", method) for method in ("PUT", "DELETE")],
)
async def test_dependencies_require_both_nested_parents(
    db_session, method, wrong_parent
):
    data = await seed(db_session)
    if wrong_parent == "project":
        project, package = data.own, data.packages[2]
    else:
        project, package = data.foreign, data.packages[3]
    # An admin is unrestricted by scope, but must still use the real successor URL.
    user = data.admin if wrong_parent == "successor" else data.editor
    url = f"/api/projects/{project}/work-packages/{package}/dependencies"
    if method in {"PUT", "DELETE"}:
        url += f"/{data.dependency}"
    payload = (
        {"predecessor_id": str(data.packages[1])}
        if method == "POST"
        else {"lag_working_days": 9}
    )
    async with client_for(db_session.bind, user) as client:
        response = await client.request(
            method, url, **({"json": payload} if method in {"PUT", "POST"} else {})
        )
    assert response.status_code == 404
    async with AsyncSession(db_session.bind) as check:
        assert (
            await check.get(WorkPackageDependency, data.dependency)
        ).lag_working_days == 0
        assert (
            await check.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == data.dependency)
            )
            == 0
        )


@pytest.mark.parametrize("role", ["editor", "admin"])
async def test_editor_can_manage_own_work_and_cross_project_predecessor(
    db_session, role
):
    data = await seed(db_session)
    path = f"/api/projects/{data.own}/work-packages/{data.packages[0]}"
    async with client_for(db_session.bind, getattr(data, role)) as client:
        assert (await client.put(path, json={"name": "Valid"})).status_code == 200
        created = await client.post(
            path + "/dependencies", json={"predecessor_id": str(data.packages[3])}
        )
        assert created.status_code == 201
        dep_path = path + "/dependencies/" + created.json()["id"]
        assert (
            await client.put(dep_path, json={"lag_working_days": 2})
        ).status_code == 200
        assert (await client.delete(dep_path)).status_code == 204
        assert (await client.delete(path)).status_code == 204


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
async def test_editor_cannot_write_dependencies_in_foreign_project(db_session, method):
    data = await seed(db_session)
    path = f"/api/projects/{data.foreign}/work-packages/{data.packages[2]}/dependencies"
    if method != "POST":
        path += f"/{data.dependency}"
    payload = (
        {"predecessor_id": str(data.packages[0])}
        if method == "POST"
        else {"lag_working_days": 5}
    )
    async with client_for(db_session.bind, data.editor) as client:
        response = await client.request(
            method, path, **({"json": payload} if method != "DELETE" else {})
        )
    assert response.status_code == 403
    async with AsyncSession(db_session.bind) as check:
        assert (
            await check.get(WorkPackageDependency, data.dependency)
        ).lag_working_days == 0
        assert (
            await check.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.actor_id == data.editor)
            )
            == 0
        )


async def creation_case(engine, role, fail):
    async with AsyncSession(engine, expire_on_commit=False) as seed_session:
        data = await seed(seed_session)
    if fail:

        def fail_scope(session, *_):
            editor = next(
                (
                    obj
                    for obj in session.identity_map.values()
                    if isinstance(obj, User) and obj.id == data.editor
                ),
                None,
            )
            if editor is not None and len(editor.scope_project_ids or []) > 1:
                raise RuntimeError(
                    "Injected failure after SQL writes but before commit"
                )

        sa.event.listen(Session, "after_flush_postexec", fail_scope)

    commits = []

    def committed(session):
        commits.append(True)

    sa.event.listen(Session, "after_commit", committed)
    try:
        async with client_for(engine, getattr(data, role)) as client:
            response = await client.post(
                "/api/projects",
                json={
                    "name": "Atomic creation",
                    "start_date": "2026-01-01",
                    "end_date": "2026-02-01",
                },
            )
        assert response.status_code == (
            500 if fail else 403 if role == "viewer" else 201
        )
        async with AsyncSession(engine) as check:
            project = await check.scalar(
                sa.select(Project).where(Project.name == "Atomic creation")
            )
            editor = await check.get(User, data.editor)
            if fail or role == "viewer":
                assert project is None and editor.scope_project_ids == [data.own]
                assert commits == []
                # Includes flushed creation audit rows: none may escape the failed transaction.
                assert (
                    await check.scalar(
                        sa.select(sa.func.count())
                        .select_from(AuditLog)
                        .where(AuditLog.actor_id == getattr(data, role))
                    )
                    == 0
                )
            else:
                assert project is not None and commits == [True]
                assert (project.id in editor.scope_project_ids) == (role == "editor")
                log = await check.scalar(
                    sa.select(AuditLog).where(AuditLog.entity_id == project.id)
                )
                assert log is not None and log.actor_id == getattr(data, role)
    finally:
        sa.event.remove(Session, "after_commit", committed)
        if fail:
            sa.event.remove(Session, "after_flush_postexec", fail_scope)


@pytest.mark.parametrize(
    "role,fail",
    [("editor", False), ("admin", False), ("viewer", False), ("editor", True)],
)
async def test_creation_is_atomic_with_scope_and_audit(db_session, role, fail):
    await creation_case(db_session.bind, role, fail)


@pytest.mark.parametrize(
    "role,fail", [("editor", False), ("admin", False), ("editor", True)]
)
async def test_creation_with_real_postgres_arrays_and_audit(
    resource_database, role, fail
):
    await creation_case(resource_database, role, fail)


async def test_concurrent_editor_creations_retain_both_scopes(
    resource_database, monkeypatch
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        data = await seed(session)
    original = ProjectService.create
    ready = asyncio.Event()
    arrived = 0

    async def simultaneous(self, *args, **kwargs):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=5)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ProjectService, "create", simultaneous)
    async with client_for(resource_database, data.editor) as client:
        responses = await asyncio.gather(
            *[
                client.post(
                    "/api/projects",
                    json={
                        "name": name,
                        "start_date": "2026-01-01",
                        "end_date": "2026-02-01",
                    },
                )
                for name in ("Concurrent one", "Concurrent two")
            ]
        )
    assert all(response.status_code == 201 for response in responses)
    async with AsyncSession(resource_database) as session:
        editor = await session.get(User, data.editor)
        assert set(map(str, editor.scope_project_ids)) == {
            str(data.own),
            *(response.json()["id"] for response in responses),
        }
