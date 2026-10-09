"""All native mappings retain the migrated schema, relationships and audit transactions."""

from datetime import UTC, date, datetime

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Assignment,
    AuditLog,
    InfrastructureResource,
    PersonalResource,
    Project,
    ResourceGroup,
    ResourceType,
    WorkPackage,
)
from app.models.base import ORMModel, column_values
from app.services.audit import set_actor
from app.services.baseline_service import snapshot_payload
from tests.test_resource_group_orm import resource_database
from tests.test_utc_migration_postgres import legacy_database


async def test_all_mappings_match_migrated_postgres(resource_database):
    def differences(connection):
        return compare_metadata(
            MigrationContext.configure(connection), ORMModel.metadata
        )

    async with resource_database.connect() as connection:
        assert await connection.run_sync(differences) == []


async def test_connected_models_keep_identity_relationships_and_atomic_audit(
    resource_database,
):
    async with AsyncSession(resource_database, expire_on_commit=False) as session:
        group = ResourceGroup(name="Typed team")
        person = PersonalResource(name="Person", group_id=group.id)
        machine = InfrastructureResource(name="Machine", group_id=group.id)
        project = Project(
            name="Native plan", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        )
        package = WorkPackage(
            name="Assembly",
            project_id=project.id,
            start_date=project.start_date,
            end_date=project.end_date,
        )
        assignment = Assignment(
            resource_id=person.id,
            resource_type=ResourceType.personal,
            work_package_id=package.id,
            start_date=package.start_date,
            end_date=package.end_date,
            allocation_percent=50,
        )
        session.add(group)
        await session.flush()
        session.add_all([person, machine, project])
        await session.flush()
        session.add(package)
        await session.flush()
        session.add(assignment)
        await session.commit()
        project_id, assignment_id = project.id, assignment.id
        assert all(
            row.created_at.tzinfo is UTC
            for row in (person, machine, project, package, assignment)
        )
        session.expunge_all()
        loaded = (
            await session.scalars(
                sa.select(Project)
                .where(Project.id == project_id)
                .options(
                    selectinload(Project.work_packages).selectinload(
                        WorkPackage.assignments
                    )
                )
            )
        ).one()
        loaded_package = loaded.work_packages[0]
        loaded_assignment = loaded_package.assignments[0]
        assert loaded_package.project is loaded
        assert loaded_assignment.work_package is loaded_package
        assert loaded_assignment.id == assignment_id
        assert "work_packages" not in column_values(loaded)
        assert "assignments" not in snapshot_payload(loaded_package)
        old_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLog)
            .where(AuditLog.entity_id == assignment_id)
        )
        loaded_assignment.allocation_percent = 75
        await session.flush()
        await session.rollback()
        session.expunge_all()
        assert (await session.get(Assignment, assignment_id)).allocation_percent == 50
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == assignment_id)
            )
            == old_count
        )
        saved = await session.get(Assignment, assignment_id)
        saved.allocation_percent = 75
        await session.commit()
        log = (
            await session.scalars(
                sa.select(AuditLog)
                .where(AuditLog.entity_id == assignment_id)
                .order_by(AuditLog.recorded_at.desc())
            )
        ).first()
        assert log.changes == {"allocation_percent": {"from": 50, "to": 75}}
