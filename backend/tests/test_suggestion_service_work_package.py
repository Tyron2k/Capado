"""Work-package-aware suggestions must respect assignment uniqueness."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.project import Project, WorkPackage
from app.models.resource import PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.services.suggestion_service import SuggestionService


async def test_work_package_suggestions_exclude_already_assigned_resource(
    db_session: AsyncSession,
) -> None:
    """An assignment outside the search dates still makes a swap invalid."""
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
    general = await service.get_suggestions(date(2026, 6, 1), date(2026, 6, 5), 50)
    scoped = await service.get_suggestions(
        date(2026, 6, 1),
        date(2026, 6, 5),
        50,
        work_package_id=work_package.id,
    )

    assert {item.resource_id for item in general} == {
        assigned_person.id,
        free_person.id,
    }
    assert {item.resource_id for item in scoped} == {free_person.id}
