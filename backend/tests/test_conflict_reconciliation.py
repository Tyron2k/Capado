"""Real-schema regression coverage for imported bookings and reconciliation.

SQLite verifies transaction rollback and the stored results. PostgreSQL lock
semantics are checked separately; SQLite does not exercise advisory locks.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlmodel import select

from app.models.assignment import Assignment
from app.models.conflict import Conflict, ConflictAssignment
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource
from app.models.resource_group import ResourceGroup
from app.services.conflict_refresh import refresh_resources
from app.services.conflict_service import ConflictService
from app.services.gantt_resource_service import GanttResourceService, _assignment_dates
from app.services.import_export.assignments import import_assignments
from app.services.time_zone import local_wall_time_to_utc, planning_zone


def _local(value: datetime) -> datetime:
    return local_wall_time_to_utc(value, planning_zone())


@pytest.fixture
async def bookings(db_session):
    group = ResourceGroup(name="Paint shop", resource_type="infrastructure")
    db_session.add(group)
    await db_session.commit()
    track = InfrastructureResource(name="Track 74", group_id=group.id)
    db_session.add(track)
    packages = []
    for name in ("Train A", "Train B"):
        project = Project(
            name=name, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
        )
        db_session.add(project)
        await db_session.flush()
        package = WorkPackage(
            project_id=project.id,
            name="Inspection",
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 20),
        )
        db_session.add(package)
        packages.append(package)
    await db_session.commit()
    return group, track, packages


async def _import(db_session):
    return await import_assignments(
        db_session,
        [
            ("Project", "Work Package", "Resource", "Start", "End", "Allocation"),
            ("Train A", "Inspection", "Track 74", "2026-08-17", "2026-08-21", "100"),
            ("Train B", "Inspection", "Track 74", "2026-08-12", "2026-08-21", "100"),
        ],
    )


async def test_import_detects_overlap_and_gantt_uses_actual_booking(
    db_session, bookings
):
    group, track, _ = bookings
    result = await _import(db_session)
    assert result.created == 2
    assert result.conflicts_found == 1
    assert not result.conflict_check_failed
    conflict = (await db_session.execute(select(Conflict))).scalars().one()
    assert (conflict.start_date, conflict.end_date) == (
        date(2026, 8, 17),
        date(2026, 8, 21),
    )
    gantt = await GanttResourceService(db_session).get_infra_group_gantt_data(group.id)
    bars = [p.work_packages[0] for p in gantt.projects]
    assert all(b.has_conflict for b in bars)
    assert [(b.start_date, b.end_date) for b in bars] == [
        (date(2026, 8, 17), date(2026, 8, 21)),
        (date(2026, 8, 12), date(2026, 8, 21)),
    ]
    # Rechecking preserves identities consumed by open conflict detail panels.
    assert await refresh_resources(db_session) == 1
    again = (await db_session.execute(select(Conflict))).scalars().one()
    assert again.id == conflict.id


async def test_duplicate_only_import_repairs_missing_conflicts(db_session, bookings):
    await _import(db_session)
    service = ConflictService(db_session)
    await service._delete_conflicts_for_resource(bookings[1].id)
    await db_session.commit()
    result = await _import(db_session)
    assert result.skipped == 2
    assert result.created == 0
    assert result.conflicts_found == 1


async def test_failed_replacement_retains_previous_results(
    db_session, bookings, monkeypatch
):
    await _import(db_session)
    old = (await db_session.execute(select(Conflict))).scalars().one()
    old_id = old.id
    assignment = (await db_session.execute(select(Assignment))).scalars().first()
    assignment.end_at += timedelta(days=1)
    db_session.add(assignment)
    await db_session.commit()
    service = ConflictService(db_session)

    async def fail(_):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(service, "_save_conflict_periods", fail)
    # Force a changed result to exercise DELETE followed by failure.
    assignment.start_at = _local(datetime(2026, 8, 18, 6))
    db_session.add(assignment)
    await db_session.commit()
    with pytest.raises(RuntimeError):
        await service.refresh_conflicts(bookings[1].id)
    assert (await db_session.execute(select(Conflict.id))).scalars().one() == old_id
    assert (
        len((await db_session.execute(select(ConflictAssignment))).scalars().all()) == 2
    )


async def test_import_reports_check_failure_without_claiming_import_failed(
    db_session, bookings, monkeypatch
):
    async def fail(*args):
        raise RuntimeError("simulated check failure")

    monkeypatch.setattr("app.services.import_export.common.refresh_resources", fail)
    result = await _import(db_session)
    assert result.created == 2
    assert result.errors == []
    assert result.conflict_check_failed
    assert result.conflicts_found is None
    assert len((await db_session.execute(select(Assignment))).scalars().all()) == 2


async def test_back_to_back_bookings_and_midnight_end(db_session, bookings):
    _, track, packages = bookings
    for package, start, end in [
        (
            packages[0],
            _local(datetime(2026, 8, 17, 6)),
            _local(datetime(2026, 8, 17, 12)),
        ),
        (
            packages[1],
            _local(datetime(2026, 8, 17, 12)),
            _local(datetime(2026, 8, 18, 0)),
        ),
    ]:
        a = Assignment(
            resource_id=track.id,
            resource_type="infrastructure",
            work_package_id=package.id,
            start_at=start,
            end_at=end,
        )
        db_session.add(a)
        assert _assignment_dates(a) == (date(2026, 8, 17), date(2026, 8, 17))
    await db_session.commit()
    assert await refresh_resources(db_session) == 0


async def test_unrelated_booking_does_not_inherit_overlap(db_session, bookings):
    _, track, packages = bookings
    # The second booking bridges the others, but the last starts exactly when
    # the overlapping portion ends and must never appear among conflict links.
    a = Assignment(
        resource_id=track.id,
        resource_type="infrastructure",
        work_package_id=packages[0].id,
        start_at=_local(datetime(2026, 8, 17, 6)),
        end_at=_local(datetime(2026, 8, 17, 10)),
    )
    b = Assignment(
        resource_id=track.id,
        resource_type="infrastructure",
        work_package_id=packages[1].id,
        start_at=_local(datetime(2026, 8, 17, 8)),
        end_at=_local(datetime(2026, 8, 17, 12)),
    )
    c = Assignment(
        resource_id=track.id,
        resource_type="infrastructure",
        work_package_id=packages[0].id,
        start_at=_local(datetime(2026, 8, 17, 12)),
        end_at=_local(datetime(2026, 8, 17, 14)),
    )
    db_session.add_all([a, b, c])
    await db_session.commit()
    assert await refresh_resources(db_session) == 1
    links = (await db_session.execute(select(ConflictAssignment))).scalars().all()
    assert {link.assignment_id for link in links} == {a.id, b.id}
