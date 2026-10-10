"""Persisted writes, failed derived transactions and PostgreSQL scheduler retry."""

import logging
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.audit import AuditLog
from app.models.calendar import WorkWeekProfile
from app.models.conflict import Conflict, ConflictAssignment
from app.models.resource import InfrastructureResource, PersonalResource
from app.models.resource_group import ResourceGroup
from app.models.scheduled_job_run import JobRunStatus, ScheduledJobRun
from app.models.site import Site
from app.services import scheduler
from app.services.conflict_refresh import CONFLICT_CHECK_JOB, refresh_resources
from app.services.conflict_service import ConflictService
from tests.test_assignment_integrity import DAY, payload, seed
from tests.test_project_integrity import client_for
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401


async def fail_derived_write(self, rid, _periods):
    """Fail after a real derived write; its row and audit must roll back."""
    self.session.add(
        Conflict(
            resource_id=rid,
            resource_type="personal",
            start_date=DAY,
            end_date=DAY,
            total_assigned_percent=999,
            available_percent=1,
        )
    )
    await self.session.flush()
    raise RuntimeError("Simulated derived persistence failure")


async def conflict_signature(engine, rid):
    async with AsyncSession(engine) as session:
        conflicts = (
            await session.scalars(
                sa.select(Conflict)
                .where(Conflict.resource_id == rid)
                .order_by(Conflict.id)
            )
        ).all()
        ids = [row.id for row in conflicts]
        links = (
            await session.execute(
                sa.select(
                    ConflictAssignment.conflict_id, ConflictAssignment.assignment_id
                )
                .where(ConflictAssignment.conflict_id.in_(ids))
                .order_by(
                    ConflictAssignment.conflict_id, ConflictAssignment.assignment_id
                )
            )
        ).all()
        return [
            (row.id, row.total_assigned_percent, row.available_percent)
            for row in conflicts
        ], links


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_failed_refresh_returns_success_for_committed_assignment(
    resource_database, monkeypatch, caplog, kind, operation
):
    uid, resources, packages = await seed(resource_database, kind)
    async with AsyncSession(resource_database) as session:
        session.add(WorkWeekProfile(name="Default", is_default=True))
        await session.commit()
    async with client_for(resource_database, uid) as client:
        assert (
            await client.post(
                "/api/assignments", json=payload(kind, resources[0], packages[0])
            )
        ).status_code == 201
        target = payload(kind, resources[0], packages[1])
        if kind == "personal":
            target["allocation_percent"] = 80
        aid = None
        if operation != "create":
            created = await client.post(
                "/api/assignments", json=payload(kind, resources[0], packages[1])
            )
            assert created.status_code == 201, created.text
            aid = created.json()["assignment"]["id"]
        before = await conflict_signature(resource_database, resources[0])
        with monkeypatch.context() as patch, caplog.at_level(logging.ERROR):
            patch.setattr(ConflictService, "_replace_periods", fail_derived_write)
            if operation == "create":
                response = await client.post("/api/assignments", json=target)
            elif operation == "update":
                response = await client.put(f"/api/assignments/{aid}", json=target)
            else:
                response = await client.delete(f"/api/assignments/{aid}")
        async with AsyncSession(resource_database) as session:
            rows = (
                await session.scalars(
                    sa.select(Assignment).where(Assignment.resource_id == resources[0])
                )
            ).all()
            assert len(rows) == (1 if operation == "delete" else 2)
            if operation != "delete" and kind == "personal":
                assert (
                    next(
                        row for row in rows if row.work_package_id == packages[1]
                    ).allocation_percent
                    == 80
                )
            assert not (
                await session.scalars(
                    sa.select(Conflict).where(Conflict.total_assigned_percent == 999)
                )
            ).all()
            events = (
                await session.scalars(
                    sa.select(AuditLog).where(AuditLog.entity_type == "conflicts")
                )
            ).all()
            assert not any(
                event.changes.get("total_assigned_percent", {}).get("to") == 999
                for event in events
            )
        expected_conflicts = ([], []) if operation == "delete" else before
        assert (
            await conflict_signature(resource_database, resources[0])
            == expected_conflicts
        )
        assert (
            response.status_code
            == {"create": 201, "update": 200, "delete": 204}[operation]
        ), response.text
        assert "after committed write" in caplog.text
        assert "Simulated derived persistence failure" in caplog.text
        async with AsyncSession(resource_database) as retry:
            await refresh_resources(retry, [resources[0]])
        repaired = await conflict_signature(resource_database, resources[0])
        async with AsyncSession(resource_database) as retry:
            await refresh_resources(retry, [resources[0]])
        assert await conflict_signature(resource_database, resources[0]) == repaired
        if operation != "delete":
            assert repaired[0]  # The successful retry detects the actual overbooking.
            assert (
                await client.post("/api/assignments", json=target)
            ).status_code == 409


async def test_calendar_write_succeeds_when_its_followup_refresh_fails(
    resource_database, monkeypatch, caplog
):
    uid, _resources, _packages = await seed(resource_database, "personal")
    async with client_for(resource_database, uid) as client:
        with monkeypatch.context() as patch, caplog.at_level(logging.ERROR):
            patch.setattr(ConflictService, "_replace_periods", fail_derived_write)
            response = await client.post(
                "/api/sites", json={"name": "Saved despite refresh failure"}
            )
        async with AsyncSession(resource_database) as session:
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(Site)
                    .where(Site.name == "Saved despite refresh failure")
                )
                == 1
            )
            assert not (
                await session.scalars(
                    sa.select(Conflict).where(Conflict.total_assigned_percent == 999)
                )
            ).all()
        assert response.status_code == 201, response.text
        assert response.json()["name"] == "Saved despite refresh failure"
        assert "after committed write" in caplog.text


async def test_scheduler_records_failure_then_retries_and_refresh_is_idempotent(
    resource_database, monkeypatch
):
    uid, resources, packages = await seed(resource_database, "infrastructure")
    async with client_for(resource_database, uid) as client:
        for package in packages:
            assert (
                await client.post(
                    "/api/assignments",
                    json=payload("infrastructure", resources[0], package),
                )
            ).status_code == 201
    before = await conflict_signature(resource_database, resources[0])
    now = datetime(2026, 1, 5, 12, tzinfo=UTC)
    with monkeypatch.context() as patch:
        patch.setattr(
            scheduler, "JOBS", {CONFLICT_CHECK_JOB: scheduler._conflict_check_job}
        )
        patch.setattr(ConflictService, "_replace_periods", fail_derived_write)
        async with AsyncSession(resource_database, expire_on_commit=False) as session:
            assert await scheduler.run_due_jobs(session, now) == [CONFLICT_CHECK_JOB]
    async with AsyncSession(resource_database) as session:
        runs = (await session.scalars(sa.select(ScheduledJobRun))).all()
        assert len(runs) == 1 and runs[0].status == JobRunStatus.failed
        assert "Simulated derived persistence failure" in runs[0].detail
    assert await conflict_signature(resource_database, resources[0]) == before

    with monkeypatch.context() as patch:
        patch.setattr(
            scheduler, "JOBS", {CONFLICT_CHECK_JOB: scheduler._conflict_check_job}
        )
        async with AsyncSession(resource_database, expire_on_commit=False) as session:
            assert await scheduler.run_due_jobs(session, now) == [CONFLICT_CHECK_JOB]
            assert await scheduler.run_due_jobs(session, now) == []
    async with AsyncSession(resource_database) as session:
        assert sorted(
            (await session.scalars(sa.select(ScheduledJobRun.status))).all()
        ) == [JobRunStatus.failed, JobRunStatus.succeeded]
    assert await conflict_signature(resource_database, resources[0]) == before


@pytest.mark.parametrize("kind", ["personal", "infrastructure"])
@pytest.mark.parametrize("entity", ["resource", "group"])
async def test_resource_and_group_updates_keep_committed_input_on_refresh_failure(
    resource_database, monkeypatch, caplog, kind, entity
):
    uid, resources, _packages = await seed(resource_database, kind)
    model = PersonalResource if kind == "personal" else InfrastructureResource
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        resource = await session.get(model, resources[0])
        source = resource.group_id
        parent = ResourceGroup(name="New parent", resource_type=kind)
        site = Site(name="New place")
        session.add_all([parent, site])
        await session.commit()
        target_id = source if entity == "group" else resources[0]
        changes = {
            "name": "Committed input",
            **(
                {"parent_id": str(parent.id)}
                if entity == "group"
                else {"site_id": str(site.id)}
            ),
        }
    async with client_for(resource_database, uid) as client:
        with monkeypatch.context() as patch, caplog.at_level(logging.ERROR):
            patch.setattr(ConflictService, "_replace_periods", fail_derived_write)
            path = (
                f"/api/resource-groups/{source}"
                if entity == "group"
                else f"/api/resources/{kind}/{resources[0]}"
            )
            response = await client.put(path, json=changes)
    async with AsyncSession(resource_database) as session:
        persisted = await session.get(
            ResourceGroup if entity == "group" else model, target_id
        )
        assert persisted.name == "Committed input"
        assert (
            persisted.parent_id == parent.id
            if entity == "group"
            else persisted.site_id == site.id
        )
        assert not (
            await session.scalars(
                sa.select(Conflict).where(Conflict.total_assigned_percent == 999)
            )
        ).all()
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Committed input"
    assert "after committed write" in caplog.text
