"""Typed ORM pilot against the migrated PostgreSQL schema and real HTTP auth."""

from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest_asyncio
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload
from sqlmodel import SQLModel

from app.database import get_session
from app.main import app
from app.models.audit import AuditLog
from app.models.resource import ResourceType
from app.models.resource_group import ResourceGroup
from app.models.user import User
from app.schemas.resource import ResourceGroupTransfer
from app.services.audit import _before_flush, register_audit_listener, set_actor
from app.services.auth_service import create_access_token
from tests.test_utc_migration_postgres import legacy_database, migrate


def test_constructor_defaults_are_eager_and_csv_validation_is_separate():
    group = ResourceGroup(name="Pilot")
    other = ResourceGroup(name="Pilot")
    assert isinstance(group.id, UUID) and group.id != other.id
    assert (
        group.created_at.utcoffset()
        == group.updated_at.utcoffset()
        == UTC.utcoffset(None)
    )
    assert group.resource_type is ResourceType.personal
    assert group.parent_id is None
    assert group != other  # ORM identity, not value equality.
    record = ResourceGroupTransfer.model_validate(group, from_attributes=True)
    assert record.id == group.id and record.resource_type is ResourceType.personal
    assert ResourceGroup.metadata is SQLModel.metadata


@pytest_asyncio.fixture
async def resource_database(legacy_database):
    url, engine = legacy_database
    result = await migrate(url, "head")
    assert result.returncode == 0, result.stderr
    already_registered = sa.event.contains(Session, "before_flush", _before_flush)
    register_audit_listener()
    try:
        yield engine
    finally:
        if not already_registered:
            sa.event.remove(Session, "before_flush", _before_flush)


async def test_postgres_schema_defaults_relationship_tracking_and_rollback(
    resource_database,
):
    def schema_diff(connection):
        context = MigrationContext.configure(
            connection,
            opts={
                "include_object": lambda obj, name, kind, reflected, compare_to: (
                    kind != "table" or name == "resource_groups"
                ),
            },
        )
        return compare_metadata(context, SQLModel.metadata)

    async with resource_database.connect() as connection:
        assert await connection.run_sync(schema_diff) == []
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        actor = User(
            name="Pilot admin",
            email="pilot@example.test",
            role="admin",
            password_hash="test-only",
        )
        session.add(actor)
        await session.commit()
        set_actor(session, actor.id)
        parent = ResourceGroup(name="Parent", resource_type=ResourceType.infrastructure)
        session.add(parent)
        await session.flush()
        child = ResourceGroup(
            name="Child", resource_type=ResourceType.infrastructure, parent_id=parent.id
        )
        session.add(child)
        await session.commit()
        child_id, parent_id = child.id, parent.id
        session.expunge_all()
        loaded = (
            await session.scalars(
                sa.select(ResourceGroup)
                .where(ResourceGroup.id == child_id)
                .options(selectinload(ResourceGroup.parent))
            )
        ).one()
        assert loaded.parent.id == parent_id
        assert loaded.resource_type is ResourceType.infrastructure
        assert loaded.created_at.tzinfo is not None
        loaded.name = "Committed"
        await session.commit()
        logs = list(
            (
                await session.scalars(
                    sa.select(AuditLog).where(AuditLog.entity_id == child_id)
                )
            ).all()
        )
        assert len(logs) == 2 and all(log.actor_id == actor.id for log in logs)
        assert logs[-1].changes == {"name": {"from": "Child", "to": "Committed"}}
        loaded.name = "Rolled back"
        await session.flush()
        await session.rollback()
        session.expunge_all()
        assert (await session.get(ResourceGroup, child_id)).name == "Committed"
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == child_id)
            )
        ) == 2
        # Core inserts used by transfer paths retain the eager ORM defaults too.
        created_id = (
            await session.execute(
                sa.insert(ResourceGroup)
                .values(name="Core default")
                .returning(ResourceGroup.id)
            )
        ).scalar_one()
        await session.commit()
        created = await session.get(ResourceGroup, created_id)
        assert created.resource_type is ResourceType.personal
        assert isinstance(created.created_at, datetime) and created.parent_id is None


async def test_postgres_http_scopes_preserve_audit_actor_and_denied_writes(
    resource_database,
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        group = ResourceGroup(name="Scoped")
        outside = ResourceGroup(name="Outside")
        session.add_all([group, outside])
        await session.flush()
        editor = User(
            name="Editor",
            email="editor-pilot@example.test",
            role="editor",
            password_hash="test-only",
            must_change_password=False,
            scope_group_ids=[group.id],
        )
        viewer = User(
            name="Viewer",
            email="viewer-pilot@example.test",
            role="viewer",
            password_hash="test-only",
            must_change_password=False,
        )
        session.add_all([editor, viewer])
        await session.commit()
        group_id, outside_id, editor_id = group.id, outside.id, editor.id
        editor_token = create_access_token(editor.id, editor.role, {})
        viewer_token = create_access_token(viewer.id, viewer.role, {})

    async def request_session():
        async with AsyncSession(resource_database, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = request_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"Authorization": f"Bearer {editor_token}"}
            allowed = await client.put(
                f"/api/resource-groups/{group_id}",
                json={"name": "Allowed"},
                headers=headers,
            )
            assert (
                allowed.status_code == 200
                and allowed.json()["resource_type"] == "personal"
            )
            denied = await client.put(
                f"/api/resource-groups/{outside_id}",
                json={"name": "Denied"},
                headers=headers,
            )
            assert denied.status_code == 403
            denied = await client.put(
                f"/api/resource-groups/{group_id}",
                json={"name": "Viewer"},
                headers={"Authorization": f"Bearer {viewer_token}"},
            )
            assert denied.status_code == 403
    finally:
        app.dependency_overrides.pop(get_session, None)
    async with AsyncSession(resource_database) as session:
        assert (await session.get(ResourceGroup, group_id)).name == "Allowed"
        assert (await session.get(ResourceGroup, outside_id)).name == "Outside"
        updated = (
            await session.scalars(
                sa.select(AuditLog).where(
                    AuditLog.entity_id == group_id, AuditLog.action == "updated"
                )
            )
        ).one()
        assert updated.actor_id == editor_id
