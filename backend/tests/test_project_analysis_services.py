"""Regression checks for analysis boundaries and batched successor scoping."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.services.project_overview_service import ProjectOverviewService
from app.services.project_schedule_service import ProjectScheduleService
from app.services.work_package_dependency_service import WorkPackageDependencyService


def result(rows):
    value = MagicMock()
    value.scalars.return_value.all.return_value = rows
    value.all.return_value = rows
    return value


async def test_overview_handles_a_project_without_work_packages_at_a_fixed_date():
    project = Project(
        name="Empty plan", start_date=date(2026, 1, 1), end_date=date(2026, 1, 11)
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [result([project]), result([])]
    with patch("app.services.capacity_service.WorkingTimeService") as working:
        working.return_value.prepare = AsyncMock()
        response = await ProjectOverviewService(session).get_overview(
            today=date(2026, 1, 6)
        )
    item = response.projects[0]
    assert item.progress_percent == 50
    assert item.active_work_package_count == 0
    assert item.average_resource_utilization_percent is None
    assert item.min_float_working_days is None
    assert item.next_deadline == project.end_date
    assert item.late_work_packages == []
    assert session.execute.await_count == 2
    session.commit.assert_not_awaited()


async def test_explicit_empty_project_selection_does_not_query_the_database():
    session = AsyncMock(spec=AsyncSession)
    assert (await ProjectOverviewService(session).get_overview([])).projects == []
    session.execute.assert_not_awaited()


async def test_dependency_batch_retains_successor_project_and_cross_project_edges():
    first, second, predecessor, successor1, successor2 = (uuid4() for _ in range(5))
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result(
        [
            (first, predecessor, successor1, 0),
            (second, successor1, successor2, 2),
        ]
    )
    grouped = await WorkPackageDependencyService(session).edges_for_projects(
        {first, second}
    )
    assert grouped[first][0].predecessor_id == predecessor
    assert grouped[second][0].predecessor_id == successor1
    assert grouped[second][0].successor_id == successor2
    assert grouped[second][0].lag_working_days == 2
    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()


async def test_empty_schedule_retains_the_committed_deadline_without_preparing_a_calendar():
    project = Project(
        name="Empty",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 1),
        committed_delivery_date=date(2026, 1, 20),
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = project
    session.execute.side_effect = [result([]), result([])]
    with patch("app.services.project_schedule_service.WorkingTimeService") as working:
        working.return_value.prepare = AsyncMock()
        response = await ProjectScheduleService(session).get_schedule(project.id)
        working.return_value.prepare.assert_not_awaited()
    assert response.nodes == []
    assert response.deadline == date(2026, 1, 20) and response.deadline_is_commitment
    session.commit.assert_not_awaited()
