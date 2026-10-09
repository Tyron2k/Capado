"""Project/work-package deletion preserves history and reconciles live planning atomically."""

from datetime import date
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import models as m
from app.models.project import WorkPackageDependency
from app.services.baseline_service import snapshot_payload
from app.services.conflict_service import ConflictService
from tests.test_project_integrity import client_for
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401


async def graph(engine, *, packages=True, bookings=True):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        own = m.Project(
            name="Delete own", start_date=date(2026, 1, 5), end_date=date(2026, 1, 9)
        )
        other = m.Project(
            name="Keep other", start_date=own.start_date, end_date=own.end_date
        )
        admin = m.User(
            name="Admin",
            email="delete-admin@example.test",
            password_hash="test-only",
            role="admin",
        )
        editor = m.User(
            name="Editor",
            email="delete-editor@example.test",
            password_hash="test-only",
            role="editor",
            scope_project_ids=[own.id, other.id],
        )
        outsider = m.User(
            name="Other editor",
            email="delete-outsider@example.test",
            password_hash="test-only",
            role="editor",
            scope_project_ids=[other.id],
        )
        group = m.ResourceGroup(name="Deletion people")
        skill = m.Skill(name="Deletion skill")
        session.add_all(
            [
                own,
                other,
                admin,
                editor,
                outsider,
                group,
                skill,
                m.WorkWeekProfile(name="Deletion default", is_default=True),
            ]
        )
        await session.flush()
        person = m.PersonalResource(name="Shared person", group_id=group.id)
        session.add(person)
        baseline = m.Baseline(name="Frozen before delete")
        session.add(baseline)
        await session.flush()
        entities = [own]
        wps = []
        assignments = []
        dependencies = []
        requirement = None
        if packages:
            wps = [
                m.WorkPackage(
                    project_id=p.id,
                    name=f"Package {i}",
                    start_date=p.start_date,
                    end_date=p.end_date,
                )
                for i, p in enumerate([own, other, other])
            ]
            session.add_all(wps)
            await session.flush()
            entities.append(wps[0])
            requirement = m.WorkPackageRequirement(
                work_package_id=wps[0].id, skill_id=skill.id
            )
            dependencies = [
                WorkPackageDependency(predecessor_id=wps[0].id, successor_id=wps[1].id),
                WorkPackageDependency(predecessor_id=wps[2].id, successor_id=wps[0].id),
            ]
            session.add_all([requirement, *dependencies])
            await session.flush()
            if bookings:
                assignments = [
                    m.Assignment(
                        resource_id=person.id,
                        resource_type="personal",
                        work_package_id=wp.id,
                        start_date=wp.start_date,
                        end_date=wp.end_date,
                        allocation_percent=100 if i == 0 else 60,
                    )
                    for i, wp in enumerate(wps)
                ]
                session.add_all(assignments)
                await session.flush()
                entities.append(assignments[0])
        snapshots = []
        for obj in entities:
            entry = m.BaselineEntry(
                baseline_id=baseline.id,
                entity_type=obj.__tablename__,
                entity_id=obj.id,
                payload=snapshot_payload(obj),
            )
            session.add(entry)
            snapshots.append((entry.id, entry.payload))
        await session.commit()
        if assignments:
            await ConflictService(session).refresh_conflicts(person.id)
        return SimpleNamespace(
            own=own.id,
            other=other.id,
            admin=admin.id,
            editor=editor.id,
            outsider=outsider.id,
            wps=[w.id for w in wps],
            assignments=[a.id for a in assignments],
            dependencies=[d.id for d in dependencies],
            requirement=requirement.id if requirement else None,
            person=person.id,
            baseline=baseline.id,
            snapshots=snapshots,
        )


async def assert_kept(engine, data):
    async with AsyncSession(engine) as session:
        assert await session.get(m.Project, data.other) is not None
        assert await session.get(m.Baseline, data.baseline) is not None
        for eid, payload in data.snapshots:
            assert (await session.get(m.BaselineEntry, eid)).payload == payload
        assert (await session.get(m.User, data.outsider)).scope_project_ids == [
            data.other
        ]
        for wp_id in data.wps[1:]:
            assert await session.get(m.WorkPackage, wp_id) is not None


@pytest.mark.parametrize(
    "packages,bookings", [(False, False), (True, False), (True, True)]
)
async def test_project_delete_cleans_live_graph_and_preserves_snapshots(
    resource_database, packages, bookings
):
    data = await graph(resource_database, packages=packages, bookings=bookings)
    async with client_for(resource_database, data.admin) as client:
        response = await client.delete(f"/api/projects/{data.own}")
    assert response.status_code == 204, response.text
    await assert_kept(resource_database, data)
    async with AsyncSession(resource_database) as session:
        assert await session.get(m.Project, data.own) is None
        assert (await session.get(m.User, data.editor)).scope_project_ids == [
            data.other
        ]
        for model, ids in [
            (m.WorkPackage, data.wps[:1]),
            (m.Assignment, data.assignments[:1]),
            (WorkPackageDependency, data.dependencies),
            (m.WorkPackageRequirement, [data.requirement] if data.requirement else []),
        ]:
            for eid in ids:
                assert await session.get(model, eid) is None
                logs = (
                    await session.scalars(
                        sa.select(m.AuditLog).where(
                            m.AuditLog.entity_id == eid, m.AuditLog.action == "deleted"
                        )
                    )
                ).all()
                assert len(logs) == 1 and logs[0].actor_id == data.admin
        if bookings:
            conflicts = (
                await session.scalars(
                    sa.select(m.Conflict).where(m.Conflict.resource_id == data.person)
                )
            ).all()
            assert len(conflicts) == 1 and conflicts[0].total_assigned_percent == 120
            links = (
                await session.scalars(
                    sa.select(m.ConflictAssignment).where(
                        m.ConflictAssignment.conflict_id == conflicts[0].id
                    )
                )
            ).all()
            assert {link.assignment_id for link in links} == set(data.assignments[1:])


async def test_work_package_delete_uses_same_audited_cleanup(resource_database):
    data = await graph(resource_database)
    async with client_for(resource_database, data.editor) as client:
        response = await client.delete(
            f"/api/projects/{data.own}/work-packages/{data.wps[0]}"
        )
    assert response.status_code == 204, response.text
    await assert_kept(resource_database, data)
    async with AsyncSession(resource_database) as session:
        assert await session.get(m.Project, data.own) is not None
        assert await session.get(m.Assignment, data.assignments[0]) is None
        assert await session.get(m.WorkPackageRequirement, data.requirement) is None
        for eid in data.dependencies:
            assert await session.get(WorkPackageDependency, eid) is None


async def test_failed_delete_rolls_back_plan_scope_conflicts_and_audit(
    resource_database,
):
    data = await graph(resource_database)
    async with AsyncSession(resource_database) as session:
        before = list(
            (
                await session.scalars(
                    sa.select(m.Conflict).where(m.Conflict.resource_id == data.person)
                )
            ).all()
        )
        conflict_ids = {c.id for c in before}

    def fail_after_flush(session, *_):
        project = session.info.get("delete_fault")
        if project:
            raise RuntimeError("Injected failure after deletion SQL")
        if any(
            isinstance(obj, m.Project) and obj.id == data.own for obj in session.deleted
        ):
            session.info["delete_fault"] = True

    def fail_commit(session, *_):
        if session.info.get("delete_fault"):
            raise RuntimeError("Injected failure before commit")

    sa.event.listen(Session, "before_flush", fail_after_flush)
    sa.event.listen(Session, "after_flush_postexec", fail_commit)
    try:
        async with client_for(resource_database, data.admin) as client:
            response = await client.delete(f"/api/projects/{data.own}")
        assert response.status_code == 500
    finally:
        sa.event.remove(Session, "before_flush", fail_after_flush)
        sa.event.remove(Session, "after_flush_postexec", fail_commit)
    await assert_kept(resource_database, data)
    async with AsyncSession(resource_database) as session:
        assert await session.get(m.Project, data.own) is not None
        assert (await session.get(m.User, data.editor)).scope_project_ids == [
            data.own,
            data.other,
        ]
        assert await session.get(m.Assignment, data.assignments[0]) is not None
        assert (
            set(
                (
                    await session.scalars(
                        sa.select(m.Conflict.id).where(
                            m.Conflict.resource_id == data.person
                        )
                    )
                ).all()
            )
            == conflict_ids
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(m.AuditLog)
                .where(m.AuditLog.actor_id == data.admin)
            )
            == 0
        )


async def test_unauthorized_delete_changes_nothing(resource_database):
    data = await graph(resource_database)
    async with client_for(resource_database, data.outsider) as client:
        assert (await client.delete(f"/api/projects/{data.own}")).status_code == 403
    async with AsyncSession(resource_database) as session:
        assert await session.get(m.Project, data.own) is not None
        assert await session.get(m.Assignment, data.assignments[0]) is not None
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(m.AuditLog)
                .where(m.AuditLog.actor_id == data.outsider)
            )
            == 0
        )
