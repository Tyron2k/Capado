"""Qualification coverage and candidate eligibility on migrated PostgreSQL."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource import ResourceType
from app.models.work_package_requirement import RequirementMode
from app.services.unmet_requirements_service import get_unmet_requirements
from tests.test_requirement_coverage_audit import DAY, _mismatches, _seed_case
from tests.test_utc_migration_postgres import legacy_database, migrate  # noqa: F401


@pytest.mark.parametrize("kind", [ResourceType.personal, ResourceType.infrastructure])
async def test_coverage_excludes_expired_assigned_and_suggested_resources(
    legacy_database, kind
):
    url, engine = legacy_database
    migration = await migrate(url, "head")
    assert migration.returncode == 0, migration.stderr
    async with AsyncSession(engine, expire_on_commit=False) as session:
        package, bookings = await _seed_case(
            session,
            kind=kind,
            quantity=2,
            minimum_level=3,
            people=[
                {"level": 3},
                {"valid_until": DAY - timedelta(days=1)},
                {"valid_until": DAY - timedelta(days=1)},
            ],
        )
        await session.delete(bookings.pop())
        await session.commit()
        assert await _mismatches(session, package, bookings) == {bookings[1].id}
        unmet = await get_unmet_requirements(session, resource_type=kind.value)
        assert len(unmet) == 1
        assert unmet[0].assigned_quantity == 1
        assert unmet[0].gap == 1
        assert unmet[0].suggestions == []


@pytest.mark.parametrize(
    "mode,allocation,quantity,expected",
    [
        (RequirementMode.headcount, 100, 2, 1),
        (RequirementMode.effort_fte, 50, 1, 0.5),
    ],
)
async def test_temporal_personnel_coverage_uses_the_daily_bottleneck(
    legacy_database, mode, allocation, quantity, expected
):
    url, engine = legacy_database
    migration = await migrate(url, "head")
    assert migration.returncode == 0, migration.stderr
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await _seed_case(
            session,
            mode=mode,
            quantity=quantity,
            people=[
                {"start_date": DAY, "end_date": DAY, "allocation": allocation},
                {"start_date": DAY + timedelta(days=1), "allocation": allocation},
            ],
        )
        unmet = await get_unmet_requirements(session, resource_type="personal")
        assert len(unmet) == 1
        assert unmet[0].assigned_quantity == expected
        assert unmet[0].gap == quantity - expected
