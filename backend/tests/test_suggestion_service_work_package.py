"""Work-package-aware suggestions must respect assignment uniqueness."""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.project import Project, WorkPackage
from app.models.resource import PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.services.suggestion_service import SuggestionService


@pytest.mark.parametrize("window", ["different", "overlap", "identical"])
async def test_work_package_suggestions_exclude_only_identical_bookings(
    db_session: AsyncSession,
    window: str,
) -> None:
    """Distinct bookings remain candidates; their existing demand still counts."""
    group = ResourceGroup(name="Fictional team")
    assigned_person = PersonalResource(name="Already assigned", group_id=group.id)
    free_person = PersonalResource(name="Available", group_id=group.id)
    project = Project(
        name="Fictional project",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 7, 31),
    )
    work_package = WorkPackage(
        project_id=project.id,
        name="Fictional work package",
        start_date=project.start_date,
        end_date=project.end_date,
    )
    already_assigned = Assignment(
        resource_id=assigned_person.id,
        resource_type=ResourceType.personal,
        work_package_id=work_package.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        allocation_percent=10,
    )
    db_session.add_all([group, project])
    await db_session.flush()
    db_session.add_all([assigned_person, free_person, work_package])
    await db_session.flush()
    db_session.add(already_assigned)
    await db_session.commit()

    service = SuggestionService(db_session)
    start, end = (
        (date(2026, 6, 1), date(2026, 6, 5))
        if window == "different"
        else (date(2026, 7, 1), date(2026, 7, 2))
    )
    allocation = 10 if window == "identical" else 50
    general = await service.get_suggestions(start, end, allocation)
    scoped = await service.get_suggestions(
        start,
        end,
        allocation,
        work_package_id=work_package.id,
    )

    assert {item.resource_id for item in general} == {
        assigned_person.id,
        free_person.id,
    }
    expected = (
        {free_person.id}
        if window == "identical"
        else {assigned_person.id, free_person.id}
    )
    assert {item.resource_id for item in scoped} == expected
    if window != "identical":
        existing = next(
            item for item in scoped if item.resource_id == assigned_person.id
        )
        assert existing.average_free_capacity == (100 if window == "different" else 90)
