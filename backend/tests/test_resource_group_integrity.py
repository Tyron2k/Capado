"""Resource-group graph validation, real lock contention and profile inheritance."""

import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.calendar import ResourceWorkProfile, WorkWeekProfile
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.resource_group import ResourceGroup
from app.models.user import User
from app.services.working_time_service import WorkingTimeService
from tests.test_project_integrity import client_for
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401

DAY = date(2026, 1, 5)


async def seed(session, kind):
    roots = [ResourceGroup(name=name, resource_type=kind) for name in ("A", "B")]
    child = ResourceGroup(name="Child", resource_type=kind, parent_id=roots[0].id)
    wrong = ResourceGroup(
        name="Wrong",
        resource_type="infrastructure" if kind == "personal" else "personal",
    )
    admin = User(
        name="Group admin",
        email="groups@example.test",
        role="admin",
        password_hash="test-only",
    )
    session.add_all([*roots, child, wrong, admin])
    await session.commit()
    return roots[0].id, roots[1].id, child.id, wrong.id, admin.id


async def snapshot(engine, group_id):
    async with AsyncSession(engine) as session:
        group = await session.get(ResourceGroup, group_id)
        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLog)
            .where(AuditLog.entity_id == group_id)
        )
        return group.name, group.parent_id, group.updated_at, count


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize(
    "invalid,expected",
    [
        ("self", 400),
        ("cycle", 400),
        ("long_cycle", 400),
        ("wrong_type", 400),
        ("missing", 404),
    ],
)
async def test_invalid_parent_leaves_name_parent_timestamp_and_audit_unchanged(
    db_session, kind, invalid, expected
):
    a, b, child, wrong, uid = await seed(db_session, kind)
    if invalid == "long_cycle":
        node = await db_session.get(ResourceGroup, b)
        node.parent_id = child
        await db_session.commit()
    target = {
        "self": a,
        "cycle": child,
        "long_cycle": b,
        "wrong_type": wrong,
        "missing": uuid4(),
    }[invalid]
    before = await snapshot(db_session.bind, a)
    async with client_for(db_session.bind, uid) as client:
        response = await client.put(
            f"/api/resource-groups/{a}",
            json={"name": "Must not change", "parent_id": str(target)},
        )
    assert response.status_code == expected, response.text
    assert await snapshot(db_session.bind, a) == before


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize("invalid,expected", [("wrong_type", 400), ("missing", 404)])
async def test_group_creation_rejects_invalid_parent(
    db_session, kind, invalid, expected
):
    _a, _b, _child, wrong, uid = await seed(db_session, kind)
    async with client_for(db_session.bind, uid) as client:
        response = await client.post(
            "/api/resource-groups",
            json={
                "name": "Invalid",
                "resource_type": kind,
                "parent_id": str(wrong if invalid == "wrong_type" else uuid4()),
            },
        )
    assert response.status_code == expected, response.text
    async with AsyncSession(db_session.bind) as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(ResourceGroup)
                .where(ResourceGroup.name == "Invalid")
            )
            == 0
        )


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_valid_parent_change_and_explicit_null_detach_are_audited(
    db_session, kind
):
    a, b, child, _wrong, uid = await seed(db_session, kind)
    async with client_for(db_session.bind, uid) as client:
        changed = await client.put(
            f"/api/resource-groups/{child}", json={"parent_id": str(b)}
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["parent_id"] == str(b)
        detached = await client.put(
            f"/api/resource-groups/{child}", json={"parent_id": None}
        )
        assert detached.status_code == 200, detached.text
        assert detached.json()["parent_id"] is None
    async with AsyncSession(db_session.bind) as session:
        assert (await session.get(ResourceGroup, child)).parent_id is None
        events = (
            await session.scalars(
                sa.select(AuditLog)
                .where(AuditLog.entity_id == child, AuditLog.action == "updated")
                .order_by(AuditLog.recorded_at)
            )
        ).all()
        assert len(events) == 2
        assert all(event.actor_id == uid for event in events)
        assert [event.changes["parent_id"] for event in events] == [
            {"from": str(a), "to": str(b)},
            {"from": str(b), "to": None},
        ]


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_opposing_parent_changes_are_serialized_on_postgres(
    resource_database, monkeypatch, kind
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        a, b, _child, _wrong, uid = await seed(session, kind)
    original_get, original_execute = AsyncSession.get, AsyncSession.execute
    held, seen, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    owner, pid = None, None

    async def getting(self, entity, key, *args, **kwargs):
        nonlocal owner
        row = await original_get(self, entity, key, *args, **kwargs)
        if entity is ResourceGroup:
            if owner is None:
                owner = self
                held.set()
                await asyncio.wait_for(release.wait(), timeout=10)
            elif self is not owner:
                seen.set()
        return row

    async def executing(self, statement, *args, **kwargs):
        nonlocal pid
        if (
            owner is not None
            and self is not owner
            and "pg_advisory_xact_lock" in str(statement)
        ):
            pid = (
                await original_execute(self, sa.text("SELECT pg_backend_pid()"))
            ).scalar_one()
            seen.set()
        return await original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "get", getting)
    monkeypatch.setattr(AsyncSession, "execute", executing)
    tasks = []
    async with client_for(resource_database, uid) as client:
        try:
            tasks.append(
                asyncio.create_task(
                    client.put(f"/api/resource-groups/{a}", json={"parent_id": str(b)})
                )
            )
            await asyncio.wait_for(held.wait(), timeout=10)
            tasks.append(
                asyncio.create_task(
                    client.put(f"/api/resource-groups/{b}", json={"parent_id": str(a)})
                )
            )
            await asyncio.wait_for(seen.wait(), timeout=10)
            if pid is not None:
                async with AsyncSession(resource_database) as observer:
                    async with asyncio.timeout(5):
                        while not await observer.scalar(
                            sa.text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory' AND NOT granted)"
                            ),
                            {"pid": pid},
                        ):
                            await asyncio.sleep(0.01)
                assert not any(task.done() for task in tasks)
            release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert sorted(response.status_code for response in responses) == [200, 400], [
        response.text for response in responses
    ]
    async with AsyncSession(resource_database) as session:
        rows = (
            await session.scalars(
                sa.select(ResourceGroup).where(ResourceGroup.id.in_([a, b]))
            )
        ).all()
        assert sum(row.parent_id is not None for row in rows) == 1


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_profile_inheritance_after_reparenting_and_detaching(
    resource_database, kind
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        a, b, child, _wrong, uid = await seed(session, kind)
        profiles = [
            WorkWeekProfile(
                name=name, monday_minutes=minutes, is_default=name == "Default"
            )
            for name, minutes in [
                ("Default", 480),
                ("A", 240),
                ("B", 120),
                ("Own", 600),
            ]
        ]
        session.add_all(profiles)
        await session.flush()
        model = PersonalResource if kind == "personal" else InfrastructureResource
        nested = ResourceGroup(name="Third level", resource_type=kind, parent_id=child)
        session.add(nested)
        await session.flush()
        resources = [
            model(name=name, group_id=nested.id) for name in ("Inherited", "Individual")
        ]
        session.add_all(resources)
        await session.flush()
        session.add_all(
            [
                ResourceWorkProfile(
                    group_id=a, profile_id=profiles[1].id, valid_from=DAY
                ),
                ResourceWorkProfile(
                    group_id=b, profile_id=profiles[2].id, valid_from=DAY
                ),
                ResourceWorkProfile(
                    resource_id=resources[1].id,
                    profile_id=profiles[3].id,
                    valid_from=DAY,
                ),
            ]
        )
        await session.commit()
        ids = [resource.id for resource in resources]

    async def minutes():
        async with AsyncSession(resource_database) as session:
            service = WorkingTimeService(session)
            await service.prepare(ids, DAY, DAY)
            return [service.calendar_minutes(rid, DAY) for rid in ids]

    assert await minutes() == [240, 600]
    async with client_for(resource_database, uid) as client:
        response = await client.put(
            f"/api/resource-groups/{child}", json={"parent_id": str(b)}
        )
        assert response.status_code == 200, response.text
        assert await minutes() == [120, 600]
        response = await client.put(
            f"/api/resource-groups/{child}", json={"parent_id": None}
        )
        assert response.status_code == 200, response.text
    assert await minutes() == [480, 600]


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
async def test_deep_groups_round_trip_through_http_and_csv(db_session, kind):
    from app.services.import_export import csv_format, csv_transfer

    a, _b, child, _wrong, uid = await seed(db_session, kind)
    async with client_for(db_session.bind, uid) as client:
        for depth in range(3, 7):
            response = await client.post(
                "/api/resource-groups",
                json={
                    "name": f"Level {depth}",
                    "resource_type": kind,
                    "parent_id": str(child),
                },
            )
            assert response.status_code == 201, response.text
            child = response.json()["id"]
    area = "personnel" if kind == "personal" else "infrastructure"
    rows = csv_format._read_csv(await csv_transfer.export_area(db_session, area))
    result = await csv_transfer.import_area_rows(db_session, area, rows)
    assert not result.errors
    assert (await db_session.get(ResourceGroup, a)).parent_id is None


async def test_reparenting_refreshes_conflicts_of_nested_resources(resource_database):
    from app.models.assignment import Assignment
    from app.models.conflict import Conflict
    from app.models.project import Project, WorkPackage
    from app.services.conflict_refresh import refresh_resources

    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        a, b, child, _wrong, uid = await seed(session, "personal")
        grandchild = ResourceGroup(name="Nested", parent_id=child)
        full = WorkWeekProfile(name="Full", monday_minutes=480, is_default=True)
        reduced = WorkWeekProfile(name="Reduced", monday_minutes=120)
        project = Project(name="Plan", start_date=DAY, end_date=DAY)
        session.add_all([grandchild, full, reduced, project])
        await session.flush()
        resource = PersonalResource(name="Nested person", group_id=grandchild.id)
        package = WorkPackage(
            name="Work", project_id=project.id, start_date=DAY, end_date=DAY
        )
        session.add_all([resource, package])
        await session.flush()
        session.add_all(
            [
                ResourceWorkProfile(group_id=b, profile_id=reduced.id, valid_from=DAY),
                Assignment(
                    resource_id=resource.id,
                    resource_type="personal",
                    work_package_id=package.id,
                    start_date=DAY,
                    end_date=DAY,
                    allocation_percent=100,
                ),
            ]
        )
        await session.commit()
        rid = resource.id
        assert await refresh_resources(session, [rid]) == 0
    async with client_for(resource_database, uid) as client:
        response = await client.put(
            f"/api/resource-groups/{child}", json={"parent_id": str(b)}
        )
        assert response.status_code == 200, response.text
    async with AsyncSession(resource_database) as session:
        conflicts = (
            await session.scalars(
                sa.select(Conflict).where(Conflict.resource_id == rid)
            )
        ).all()
        assert len(conflicts) == 1
        assert conflicts[0].available_percent == 25


async def test_csv_waits_for_graph_write_while_metadata_edit_remains_independent(
    resource_database,
):
    from app.services.graph_locks import lock_graph
    from app.services.import_export import csv_format, csv_transfer

    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        _a, b, _child, _wrong, uid = await seed(session, "personal")
        rows = csv_format._read_csv(
            await csv_transfer.export_area(session, "personnel")
        )
    async with AsyncSession(resource_database) as holder:
        await lock_graph(holder, "resource_groups")
        async with AsyncSession(resource_database) as importer:
            task = asyncio.create_task(
                csv_transfer.import_area_rows(importer, "personnel", rows)
            )
            try:
                async with AsyncSession(resource_database) as observer:
                    async with asyncio.timeout(5):
                        while not await observer.scalar(
                            sa.text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted AND classid=1128353863 AND objid=3)"
                            )
                        ):
                            await asyncio.sleep(0.01)
                async with client_for(resource_database, uid) as client:
                    response = await asyncio.wait_for(
                        client.put(
                            f"/api/resource-groups/{b}", json={"name": "Metadata only"}
                        ),
                        timeout=5,
                    )
                    assert response.status_code == 200, response.text
                assert not task.done()
                await holder.rollback()
                result = await asyncio.wait_for(task, timeout=10)
                assert not result.errors
            finally:
                await holder.rollback()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def deletion_state(engine):
    """Compare the hierarchy, calendars, bookings, conflicts and complete audit."""
    from app.models.base import ORMModel

    async with engine.connect() as connection:
        return {
            name: list(
                (await connection.execute(sa.select(table).order_by(table.c.id))).all()
            )
            for name in (
                "resource_groups",
                "personal_resources",
                "infrastructure_resources",
                "resource_work_profiles",
                "work_week_profiles",
                "assignments",
                "conflicts",
                "audit_log",
            )
            for table in [ORMModel.metadata.tables[name]]
        }


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize(
    "dependency", ["personal", "infrastructure", "child", "deep", "profile"]
)
async def test_group_deletion_rejects_dependencies_without_changes(
    resource_database, kind, dependency
):
    from app.models.assignment import Assignment
    from app.models.project import Project, WorkPackage
    from app.services.conflict_refresh import refresh_resources

    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        root, target, _child, _wrong, uid = await seed(session, kind)
        group = await session.get(ResourceGroup, target)
        group.parent_id = root
        profile = WorkWeekProfile(name="Inherited", monday_minutes=480)
        session.add(profile)
        await session.flush()
        session.add(
            ResourceWorkProfile(group_id=root, profile_id=profile.id, valid_from=DAY)
        )
        if dependency in {"personal", "infrastructure"}:
            model = (
                PersonalResource if dependency == "personal" else InfrastructureResource
            )
            session.add(model(name="Direct resource", group_id=target))
        elif dependency in {"child", "deep"}:
            nested = ResourceGroup(
                name="Assembly", resource_type=kind, parent_id=target
            )
            session.add(nested)
            await session.flush()
            if dependency == "deep":
                descendant = ResourceGroup(
                    name="Deep", resource_type=kind, parent_id=nested.id
                )
                session.add(descendant)
                await session.flush()
                nested = descendant
            model = PersonalResource if kind == "personal" else InfrastructureResource
            person = model(name="Inherited resource", group_id=nested.id)
            project = Project(name="Plan", start_date=DAY, end_date=DAY)
            session.add_all([person, project])
            await session.flush()
            work = WorkPackage(
                name="Work", project_id=project.id, start_date=DAY, end_date=DAY
            )
            session.add(work)
            await session.flush()
            session.add(
                Assignment(
                    resource_type=kind,
                    resource_id=person.id,
                    work_package_id=work.id,
                    **(
                        {"start_date": DAY, "end_date": DAY, "allocation_percent": 150}
                        if kind == "personal"
                        else {
                            "start_at": datetime(2026, 1, 5, 6, tzinfo=UTC),
                            "end_at": datetime(2026, 1, 5, 18, tzinfo=UTC),
                        }
                    ),
                )
            )
            if kind == "infrastructure":
                second = WorkPackage(
                    name="Overlapping work",
                    project_id=project.id,
                    start_date=DAY,
                    end_date=DAY,
                )
                session.add(second)
                await session.flush()
                session.add(
                    Assignment(
                        resource_type=kind,
                        resource_id=person.id,
                        work_package_id=second.id,
                        start_at=datetime(2026, 1, 5, 6, tzinfo=UTC),
                        end_at=datetime(2026, 1, 5, 18, tzinfo=UTC),
                    )
                )
        else:
            session.add(
                ResourceWorkProfile(
                    group_id=target, profile_id=profile.id, valid_from=DAY
                )
            )
        await session.commit()
        if dependency in {"child", "deep"}:
            service = WorkingTimeService(session)
            await service.prepare([person.id], DAY, DAY)
            assert service.calendar_minutes(person.id, DAY) == 480
            assert await refresh_resources(session, [person.id]) == 1
    before = await deletion_state(resource_database)
    async with client_for(resource_database, uid) as client:
        response = await client.delete(f"/api/resource-groups/{target}")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]
    assert await deletion_state(resource_database) == before
    if dependency in {"child", "deep"}:
        async with AsyncSession(resource_database) as session:
            service = WorkingTimeService(session)
            await service.prepare([person.id], DAY, DAY)
            assert service.calendar_minutes(person.id, DAY) == 480


@pytest.mark.parametrize(
    "role,expected", [("admin", 204), ("editor", 403), ("viewer", 403)]
)
async def test_empty_group_deletion_permissions_and_audit(
    resource_database, role, expected
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        _root, target, _child, _wrong, uid = await seed(session, "personal")
        actor = await session.get(User, uid)
        actor.role = role
        actor.scope_group_ids = [target]
        await session.commit()
    before = await deletion_state(resource_database)
    async with client_for(resource_database, uid) as client:
        response = await client.delete(f"/api/resource-groups/{target}")
    assert response.status_code == expected, response.text
    if expected == 403:
        assert await deletion_state(resource_database) == before
    else:
        async with AsyncSession(resource_database) as session:
            assert await session.get(ResourceGroup, target) is None
            deleted = (
                await session.scalars(
                    sa.select(AuditLog).where(
                        AuditLog.entity_id == target, AuditLog.action == "deleted"
                    )
                )
            ).one()
            assert deleted.actor_id == uid
        response = None
        async with client_for(resource_database, uid) as client:
            response = await client.delete(f"/api/resource-groups/{target}")
        assert response.status_code == 404


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize(
    "change", ["foreign_parent", "owned_parent", "detach", "same_parent"]
)
async def test_editor_cannot_restructure_even_owned_groups(
    resource_database, kind, change
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        root, target, child, _wrong, uid = await seed(session, kind)
        actor = await session.get(User, uid)
        actor.role = "editor"
        actor.scope_group_ids = [root] + (
            [target, child] if change == "owned_parent" else []
        )
        await session.commit()
    before = await deletion_state(resource_database)
    value = str(target) if change in {"foreign_parent", "owned_parent"} else None
    async with client_for(resource_database, uid) as client:
        response = await client.put(
            f"/api/resource-groups/{root}",
            json={"name": "Forbidden", "parent_id": value},
        )
    assert response.status_code == 403, response.text
    assert await deletion_state(resource_database) == before
    async with client_for(resource_database, uid) as client:
        rename = await client.put(
            f"/api/resource-groups/{root}", json={"name": "Allowed rename"}
        )
    assert rename.status_code == 200, rename.text
    assert rename.json()["name"] == "Allowed rename"


async def test_group_delete_and_profile_binding_are_serialized(
    resource_database, monkeypatch
):
    """A binding committed while deletion waits is seen before dependency checks."""
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        _root, target, _child, _wrong, uid = await seed(session, "personal")
        profile = WorkWeekProfile(name="Binding")
        session.add(profile)
        await session.commit()
        profile_id = profile.id
    original_get = AsyncSession.get
    reached, pid = asyncio.Event(), None
    async with AsyncSession(resource_database) as holder:
        await holder.execute(
            sa.select(ResourceGroup)
            .where(ResourceGroup.id == target)
            .with_for_update(read=True, key_share=True)
        )
        holder.add(
            ResourceWorkProfile(group_id=target, profile_id=profile_id, valid_from=DAY)
        )
        await holder.flush()

        async def getting(self, entity, key, *args, **kwargs):
            nonlocal pid
            if self is not holder and entity is ResourceGroup and key == target:
                pid = await self.scalar(sa.text("SELECT pg_backend_pid()"))
                reached.set()
            return await original_get(self, entity, key, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "get", getting)
        async with client_for(resource_database, uid) as client:
            task = asyncio.create_task(client.delete(f"/api/resource-groups/{target}"))
            try:
                await asyncio.wait_for(reached.wait(), 10)
                async with AsyncSession(resource_database) as observer:
                    async with asyncio.timeout(5):
                        while not await observer.scalar(
                            sa.text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)"
                            ),
                            {"pid": pid},
                        ):
                            await asyncio.sleep(0.01)
                assert not task.done()
                await holder.commit()
                response = await asyncio.wait_for(task, 10)
            finally:
                await holder.rollback()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert response.status_code == 409, response.text
    async with AsyncSession(resource_database) as session:
        assert await session.get(ResourceGroup, target) is not None
        assert (
            await session.scalars(
                sa.select(ResourceWorkProfile).where(
                    ResourceWorkProfile.group_id == target
                )
            )
        ).one()


async def test_failed_leaf_deletion_rolls_back_group_and_audit(
    resource_database, monkeypatch
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        _root, target, _child, _wrong, uid = await seed(session, "personal")
    before = await deletion_state(resource_database)

    async def fail(session):
        await session.flush()
        raise RuntimeError("Simulated failure after audited deletion")

    monkeypatch.setattr(AsyncSession, "commit", fail)
    async with client_for(resource_database, uid) as client:
        response = await client.delete(f"/api/resource-groups/{target}")
    assert response.status_code == 500
    assert await deletion_state(resource_database) == before


async def test_binding_waiting_for_deleted_group_returns_404(
    resource_database, monkeypatch
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        _root, target, _child, _wrong, uid = await seed(session, "personal")
        profile = WorkWeekProfile(name="Profile")
        session.add(profile)
        await session.commit()
        profile_id = profile.id
    original_scalar = AsyncSession.scalar
    reached, pid = asyncio.Event(), None
    async with AsyncSession(resource_database) as holder:
        group = await holder.get(ResourceGroup, target, with_for_update=True)

        async def reading(self, statement, *args, **kwargs):
            nonlocal pid
            if (
                self is not holder
                and "FROM resource_groups" in str(statement)
                and getattr(statement, "_for_update_arg", None) is not None
            ):
                pid = await original_scalar(self, sa.text("SELECT pg_backend_pid()"))
                reached.set()
            return await original_scalar(self, statement, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "scalar", reading)
        async with client_for(resource_database, uid) as client:
            task = asyncio.create_task(
                client.post(
                    "/api/resource-work-profiles",
                    json={
                        "group_id": str(target),
                        "profile_id": str(profile_id),
                        "valid_from": DAY.isoformat(),
                    },
                )
            )
            try:
                await asyncio.wait_for(reached.wait(), 10)
                async with AsyncSession(resource_database) as observer:
                    async with asyncio.timeout(5):
                        while not await observer.scalar(
                            sa.text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)"
                            ),
                            {"pid": pid},
                        ):
                            await asyncio.sleep(0.01)
                assert not task.done()
                await holder.delete(group)
                await holder.commit()
                response = await asyncio.wait_for(task, 10)
            finally:
                await holder.rollback()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert response.status_code == 404, response.text
    async with AsyncSession(resource_database) as session:
        assert not (
            await session.scalars(
                sa.select(ResourceWorkProfile).where(
                    ResourceWorkProfile.group_id == target
                )
            )
        ).all()
