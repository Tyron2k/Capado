"""Keep the downloadable example compatible with actual imports and planning."""

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.services.conflict_refresh import refresh_resources
from app.services.import_export.csv_transfer import import_migration, parse_migration
from app.services.planning_readiness import get_work_package_readiness
from tests.planning_reference import MONDAY, WEDNESDAY, _clock

EXAMPLE = (
    Path(__file__).resolve().parents[2] / "docs/assets/examples/combined-planning.zip"
)


async def test_published_example_imports_and_both_documented_repairs_work(db_session):
    admin = m.User(
        email="operator@example.test",
        name="Example operator",
        role="admin",
        password_hash="unchanged-bootstrap-hash",
        must_change_password=False,
    )
    db_session.add(admin)
    await db_session.commit()
    admin_id = admin.id
    content = EXAMPLE.read_bytes()
    data = parse_migration(content)
    assert data["users"] == []
    result = await import_migration(db_session, content, admin_id)
    assert not result.errors and result.created > 0
    await db_session.refresh(admin)
    assert admin.email == "operator@example.test"
    assert admin.password_hash == "unchanged-bootstrap-hash"
    assert not admin.must_change_password
    settings = (await db_session.scalars(select(m.OrganizationSettings))).one()
    assert not settings.scheduler_enabled and not settings.smtp_enabled
    package = (await db_session.scalars(select(m.WorkPackage))).one()
    package_id = package.id
    assert (package.start_date, package.end_date) == (MONDAY, WEDNESDAY)
    before = await get_work_package_readiness(db_session, package.id)
    assert before.personnel_status == "missing_requirements"
    assert before.infrastructure_status == "conflicting"
    assert len(before.conflicts) == 2
    assert len(before.unmet_requirements) == 1
    assert before.unmet_requirements[0].gap == 1

    sam = (
        await db_session.scalars(
            select(m.PersonalResource).where(m.PersonalResource.name == "Sam Example")
        )
    ).one()
    machine_bookings = list(
        await db_session.scalars(
            select(m.Assignment)
            .where(m.Assignment.resource_type == m.ResourceType.infrastructure)
            .order_by(m.Assignment.start_at)
        )
    )
    extra = machine_bookings[0]
    assert extra.start_at == _clock(MONDAY, 21)
    db_session.add(
        m.Assignment(
            resource_type=m.ResourceType.personal,
            resource_id=sam.id,
            work_package_id=package.id,
            start_date=MONDAY,
            end_date=WEDNESDAY,
            allocation_percent=100,
        )
    )
    extra.start_at = _clock(MONDAY + timedelta(days=1), 2)
    extra.end_at = _clock(MONDAY + timedelta(days=1), 6)
    await db_session.commit()
    await refresh_resources(db_session, {sam.id, extra.resource_id})
    after = await get_work_package_readiness(db_session, package.id)
    assert after.status == "covered"
    assert not after.conflicts and not after.unmet_requirements
    assert "personnel_clock_times" in after.limits
    assert len(after.assignments) == 4

    # Reusing the migration ZIP cannot silently overwrite the newly repaired plan.
    again = await import_migration(db_session, content, admin_id)
    assert again.errors and again.created == again.updated == 0
    assert "empty destination" in again.errors[0]
    unchanged = await get_work_package_readiness(db_session, package_id)
    assert unchanged.model_dump(exclude={"checked_at"}) == after.model_dump(
        exclude={"checked_at"}
    )
