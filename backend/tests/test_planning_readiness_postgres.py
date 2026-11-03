"""Current readiness must remain read-only even when saved conflicts are stale."""

from datetime import timedelta

from sqlalchemy import event, select

from app.models.assignment import Assignment
from app.models.conflict import Conflict
from app.models.resource import ResourceType
from app.services.conflict_refresh import refresh_after_commit, refresh_resources
from app.services.conflict_service import ConflictService
from app.services.planning_readiness import get_work_package_readiness
from tests.planning_reference import MONDAY, _clock, _seed_plan
from tests.test_combined_planning_postgres import combined_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401


async def test_direct_check_uses_committed_repair_despite_failed_saved_conflict_refresh(
    combined_database,
    monkeypatch,
):
    session, engine = combined_database
    plan = await _seed_plan(session)
    extra = Assignment(
        resource_id=plan.machine.id,
        resource_type=ResourceType.infrastructure,
        work_package_id=plan.package.id,
        start_at=_clock(MONDAY, 21),
        end_at=_clock(MONDAY + timedelta(days=1), 1),
    )
    session.add(extra)
    await session.commit()
    await refresh_resources(session, plan.resource_ids)
    old = {c.id for c in (await session.scalars(select(Conflict))).all()}
    assert len(old) == 2
    extra.start_at = _clock(MONDAY + timedelta(days=1), 2)
    extra.end_at = _clock(MONDAY + timedelta(days=1), 6)
    await session.commit()

    async def fail_saving(self, periods):
        raise RuntimeError("synthetic persistence failure")

    with monkeypatch.context() as patch:
        patch.setattr(ConflictService, "_save_conflict_periods", fail_saving)
        await refresh_after_commit(session, {plan.machine.id})

    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        result = await get_work_package_readiness(session, plan.package.id)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert result.conflicts == []
    assert result.infrastructure_status == "covered"
    assert result.status == "not_fully_assessable"
    assert {"INSERT", "UPDATE", "DELETE"}.isdisjoint(statements)
    assert {c.id for c in (await session.scalars(select(Conflict))).all()} == old
    assert not session.new and not session.dirty


async def test_overview_check_includes_competing_package_but_not_unrelated_history(
    combined_database,
):
    session, _ = combined_database
    plan = await _seed_plan(session, windows=False)
    # A long competing booking is clipped only in transient calculation inputs.
    # Its persisted dates remain unchanged and do not expand the check's loop.
    extra = Assignment(
        resource_id=plan.people[0].id,
        resource_type=ResourceType.personal,
        work_package_id=plan.package.id,
        start_date=MONDAY - timedelta(days=10000),
        end_date=MONDAY + timedelta(days=10000),
        allocation_percent=50,
    )
    # Put it on a different work package so its long dates do not define the
    # selected package's own actual booking span.
    from app.models.project import WorkPackage

    other = WorkPackage(
        name="Competing plan",
        project_id=plan.package.project_id,
        start_date=extra.start_date,
        end_date=extra.end_date,
    )
    session.add(other)
    await session.flush()
    extra.work_package_id = other.id
    session.add(extra)
    await session.commit()
    result = await get_work_package_readiness(session, plan.package.id)
    assert result.personnel_status == "conflicting"
    assert "capacity_window_limit" not in result.limits
    assert len(result.conflicts) == 1
    assert set(result.conflicts[0].assignment_ids) == {
        plan.crew_bookings[0].id,
        extra.id,
    }
    assert (extra.end_date - extra.start_date).days == 20000
    assert not session.new and not session.dirty
