"""Erasure against a real schema: does the SQL delete the rows it means to?

THIS EXISTS BECAUSE ITS UNIT TEST SAID IT COULD NOT

``test_erase_personal_resource.py`` asserts that a DELETE was issued against every table holding
personal data, using a statement-recording double, and states its own limit plainly: it cannot tell
that the SQL is correct against an actual schema. A statement can name the right table and filter
wrongly — and for four of these tables there is no foreign key to catch it.

So this file writes real rows for TWO people, erases one, and checks that the other is untouched. That
is the assertion a double structurally cannot make: a ``WHERE`` clause missing its ``resource_id``
predicate would delete both, and the recording double would report exactly the same DELETEs.

See ``conftest.py`` for what SQLite can and cannot prove here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.models.absence import Absence, AbsenceReason, AbsenceStatus
from app.models.assignment import Assignment
from app.models.audit import AuditLog
from app.models.conflict import Conflict, ConflictCause
from app.models.project import Project, WorkPackage
from app.models.resource import PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.services import resource_service


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed_person(
    session: AsyncSession, group_id, work_package_id, name: str
) -> PersonalResource:
    """One person with an absence, an assignment, a conflict and an audit entry naming them."""
    person = PersonalResource(
        id=uuid4(),
        name=name,
        group_id=group_id,
        is_active=True,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(person)
    await session.flush()

    session.add(
        Absence(
            id=uuid4(),
            resource_id=person.id,
            resource_type=ResourceType.personal,
            reason=AbsenceReason.planned,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            allocation_percent=100.0,
            status=AbsenceStatus.confirmed,
            created_at=_now(),
            updated_at=_now(),
        )
    )
    session.add(
        Assignment(
            id=uuid4(),
            resource_id=person.id,
            resource_type=ResourceType.personal,
            work_package_id=work_package_id,
            start_date=date(2026, 9, 10),
            end_date=date(2026, 9, 20),
            allocation_percent=50.0,
            created_at=_now(),
            updated_at=_now(),
        )
    )
    session.add(
        Conflict(
            id=uuid4(),
            resource_id=person.id,
            resource_type=ResourceType.personal,
            cause=ConflictCause.over_allocation,
            start_date=date(2026, 9, 10),
            end_date=date(2026, 9, 12),
            total_assigned_percent=150.0,
            available_percent=100.0,
            detected_at=_now(),
        )
    )
    # An audit entry holding the name in clear text — the case that makes the sweep necessary.
    session.add(
        AuditLog(
            entity_type="personal_resources",
            entity_id=person.id,
            action="updated",
            changes={"name": {"from": "Old", "to": name}},
            created_at=_now(),
        )
    )
    await session.flush()
    return person


async def _count(session: AsyncSession, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return int((await session.execute(stmt)).scalar_one())


@pytest.fixture
async def two_people(db_session: AsyncSession):
    """Two people with identical data shapes. Erasing one must not touch the other."""
    group = ResourceGroup(
        id=uuid4(),
        name="Lackierer",
        resource_type="personal",
        created_at=_now(),
        updated_at=_now(),
    )
    db_session.add(group)
    project = Project(
        id=uuid4(),
        name="Werk",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 31),
        created_at=_now(),
        updated_at=_now(),
    )
    db_session.add(project)
    await db_session.flush()
    # A real work package: the assignment's foreign key is enforced in this harness, and the first
    # draft of this test used a random UUID and was rejected — which a recording double never was.
    package = WorkPackage(
        id=uuid4(),
        project_id=project.id,
        name="Lackieren",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 20),
        created_at=_now(),
        updated_at=_now(),
    )
    db_session.add(package)
    await db_session.flush()
    target = await _seed_person(db_session, group.id, package.id, "Müller")
    bystander = await _seed_person(db_session, group.id, package.id, "Schmidt")
    await db_session.commit()
    return target, bystander


class TestErasureAgainstARealSchema:
    async def test_the_person_row_is_gone(self, db_session: AsyncSession, two_people):
        target, _ = two_people
        await resource_service.erase_personal_resource(db_session, target.id)
        assert await _count(db_session, PersonalResource, id=target.id) == 0

    async def test_their_absences_assignments_and_conflicts_are_gone(
        self, db_session: AsyncSession, two_people
    ):
        target, _ = two_people
        await resource_service.erase_personal_resource(db_session, target.id)
        assert await _count(db_session, Absence, resource_id=target.id) == 0
        assert await _count(db_session, Assignment, resource_id=target.id) == 0
        assert await _count(db_session, Conflict, resource_id=target.id) == 0

    async def test_the_audit_entry_naming_them_is_gone(
        self, db_session: AsyncSession, two_people
    ):
        """The only place a name could survive an erasure."""
        target, _ = two_people
        await resource_service.erase_personal_resource(db_session, target.id)
        remaining = (
            (
                await db_session.execute(
                    select(AuditLog).where(AuditLog.entity_id == target.id)
                )
            )
            .scalars()
            .all()
        )
        assert all(entry.changes == {} for entry in remaining), (
            "an audit entry with values survived the erasure"
        )
        assert not any("Müller" in str(entry.changes) for entry in remaining)

    async def test_the_other_person_is_completely_untouched(
        self, db_session: AsyncSession, two_people
    ):
        """The assertion a recording double cannot make.

        A WHERE clause missing its resource_id predicate deletes both people, and a double watching
        statements would report the identical set of DELETEs against the identical tables.
        """
        target, bystander = two_people
        await resource_service.erase_personal_resource(db_session, target.id)
        assert await _count(db_session, PersonalResource, id=bystander.id) == 1
        assert await _count(db_session, Absence, resource_id=bystander.id) == 1
        assert await _count(db_session, Assignment, resource_id=bystander.id) == 1
        assert await _count(db_session, Conflict, resource_id=bystander.id) == 1
        surviving = (
            (
                await db_session.execute(
                    select(AuditLog).where(AuditLog.entity_id == bystander.id)
                )
            )
            .scalars()
            .all()
        )
        assert any("Schmidt" in str(e.changes) for e in surviving), (
            "the bystander's audit history was swept too"
        )

    async def test_one_marker_entry_records_that_it_happened(
        self, db_session: AsyncSession, two_people
    ):
        target, _ = two_people
        await resource_service.erase_personal_resource(db_session, target.id)
        entries = (
            (
                await db_session.execute(
                    select(AuditLog).where(AuditLog.entity_id == target.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 1
        assert entries[0].changes == {}
        assert entries[0].reason is not None

    async def test_the_report_counts_match_what_was_seeded(
        self, db_session: AsyncSession, two_people
    ):
        """One of each was created, so one of each must be reported — not two, and not zero."""
        target, _ = two_people
        report = await resource_service.erase_personal_resource(db_session, target.id)
        assert report.absences == 1
        assert report.assignments == 1
        assert report.conflicts == 1
