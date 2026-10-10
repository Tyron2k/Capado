"""Source and destination scopes, reference integrity and failed HTTP writes."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.user import User
from tests.test_project_integrity import client_for
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401


async def seed(session, kind, role="admin", scopes=()):
    groups = {name: ResourceGroup(name=name, resource_type=kind) for name in ("A", "B")}
    groups["wrong"] = ResourceGroup(
        name="Wrong type",
        resource_type="infrastructure" if kind == "personal" else "personal",
    )
    sites = [Site(name=name) for name in ("Before", "After")]
    session.add_all([*groups.values(), *sites])
    await session.flush()
    model = PersonalResource if kind == "personal" else InfrastructureResource
    resource = model(name="Original", group_id=groups["A"].id, site_id=sites[0].id)
    user = User(
        name="Scoped user",
        email="move@example.test",
        password_hash="test-only",
        role=role,
        scope_group_ids=[groups[name].id for name in scopes],
    )
    session.add_all([resource, user])
    await session.commit()
    return model, resource.id, user.id, groups, sites


async def snapshot(engine, model, rid):
    async with AsyncSession(engine) as session:
        row = await session.get(model, rid)
        logs = (
            await session.scalars(sa.select(AuditLog).where(AuditLog.entity_id == rid))
        ).all()
        return row.name, row.group_id, row.site_id, row.updated_at, len(logs)


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize(
    "role,scopes,expected",
    [
        ("admin", (), 200),
        ("editor", ("A", "B"), 200),
        ("editor", ("A",), 403),
        ("editor", ("B",), 403),
        ("viewer", ("A", "B"), 403),
    ],
)
async def test_move_requires_both_group_scopes(
    db_session, kind, role, scopes, expected
):
    model, rid, uid, groups, sites = await seed(db_session, kind, role, scopes)
    before = await snapshot(db_session.bind, model, rid)
    async with client_for(db_session.bind, uid) as client:
        result = await client.put(
            f"/api/resources/{kind}/{rid}",
            json={
                "name": "Moved",
                "group_id": str(groups["B"].id),
                "site_id": str(sites[1].id),
            },
        )
    assert result.status_code == expected, result.text
    after = await snapshot(db_session.bind, model, rid)
    if expected == 403:
        assert after == before
    else:
        assert after[:3] == ("Moved", groups["B"].id, sites[1].id)


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_editor_can_edit_own_resource_and_clear_orthogonal_site(db_session, kind):
    model, rid, uid, groups, _sites = await seed(db_session, kind, "editor", ("A",))
    async with client_for(db_session.bind, uid) as client:
        result = await client.put(
            f"/api/resources/{kind}/{rid}", json={"name": "Edited", "site_id": None}
        )
    assert result.status_code == 200, result.text
    assert (await snapshot(db_session.bind, model, rid))[:3] == (
        "Edited",
        groups["A"].id,
        None,
    )


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize(
    "invalid,expected",
    [("missing_group", 404), ("wrong_type", 400), ("missing_site", 404)],
)
async def test_invalid_move_preserves_all_persisted_fields(
    db_session, kind, invalid, expected
):
    model, rid, uid, groups, _sites = await seed(db_session, kind)
    before = await snapshot(db_session.bind, model, rid)
    payload = {"name": "Must roll back"}
    if invalid == "missing_site":
        payload["site_id"] = str(uuid4())
    else:
        payload["group_id"] = str(
            groups["wrong"].id if invalid == "wrong_type" else uuid4()
        )
    async with client_for(db_session.bind, uid) as client:
        result = await client.put(f"/api/resources/{kind}/{rid}", json=payload)
    assert result.status_code == expected, result.text
    assert await snapshot(db_session.bind, model, rid) == before


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize(
    "invalid,expected",
    [("missing_group", 404), ("wrong_type", 400), ("missing_site", 404)],
)
async def test_invalid_creation_uses_the_same_reference_rules(
    db_session, kind, invalid, expected
):
    model, _rid, uid, groups, _sites = await seed(db_session, kind)
    payload = {"name": "Invalid", "group_id": str(groups["A"].id)}
    if invalid == "missing_site":
        payload["site_id"] = str(uuid4())
    else:
        payload["group_id"] = str(
            groups["wrong"].id if invalid == "wrong_type" else uuid4()
        )
    async with client_for(db_session.bind, uid) as client:
        result = await client.post(f"/api/resources/{kind}", json=payload)
    assert result.status_code == expected, result.text
    async with AsyncSession(db_session.bind) as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(model)
                .where(model.name == "Invalid")
            )
            == 0
        )


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_postgres_denies_destination_outside_scope_without_audit(
    resource_database, kind
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        model, rid, uid, groups, sites = await seed(session, kind, "editor", ("A",))
    before = await snapshot(resource_database, model, rid)
    async with client_for(resource_database, uid) as client:
        result = await client.put(
            f"/api/resources/{kind}/{rid}",
            json={"group_id": str(groups["B"].id), "site_id": str(sites[1].id)},
        )
    assert result.status_code == 403, result.text
    assert await snapshot(resource_database, model, rid) == before


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_source_scope_is_checked_after_a_competing_move(
    resource_database, monkeypatch, kind
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        model, rid, uid, groups, sites = await seed(session, kind, "editor", ("A",))
    original_get = AsyncSession.get
    reached = asyncio.Event()
    pid = None
    async with AsyncSession(resource_database, expire_on_commit=False) as owner:
        row = await owner.get(model, rid, with_for_update=True)
        row.group_id = groups["B"].id
        await owner.flush()

        async def getting(self, entity, key, *args, **kwargs):
            nonlocal pid
            if self is not owner and entity is model and pid is None:
                pid = await self.scalar(sa.text("SELECT pg_backend_pid()"))
                reached.set()
            return await original_get(self, entity, key, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "get", getting)
        async with client_for(resource_database, uid) as client:
            task = asyncio.create_task(
                client.put(f"/api/resources/{kind}/{rid}", json={"name": "Forbidden"})
            )
            try:
                await asyncio.wait_for(reached.wait(), timeout=8)
                async with AsyncSession(resource_database) as observer:
                    async with asyncio.timeout(8):
                        while not await observer.scalar(
                            sa.text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)"
                            ),
                            {"pid": pid},
                        ):
                            await asyncio.sleep(0.01)
                assert not task.done()
                await owner.commit()
                result = await asyncio.wait_for(task, timeout=8)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert result.status_code == 403, result.text
    assert (await snapshot(resource_database, model, rid))[:3] == (
        "Original",
        groups["B"].id,
        sites[0].id,
    )
