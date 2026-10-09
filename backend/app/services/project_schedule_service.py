"""Focused project analysis orchestration, using the caller's read transaction.

Queries share one injected session. This service neither commits nor changes plans;
warnings and date assessments are returned for the planner to act on.
"""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.project import WorkPackage
from app.schemas.project_overview import (
    ProjectScheduleResponse,
    ScheduleNodeResponse,
)
from app.services.critical_path import (
    ScheduleNode,
    analyse,
    duration_working_days,
)
from app.services.project_service import ProjectService
from app.services.work_package_dependency_service import (
    WorkPackageDependencyService,
)
from app.services.working_time_service import WorkingTimeService

_NO_RESOURCE = UUID(int=0)


class ProjectScheduleService:
    """Coordinate project data and the existing planning calculations."""

    def __init__(self, session: AsyncSession):
        """Use the request-scoped session without owning its transaction."""
        self.session = session

    async def get_schedule(self, project_id: UUID) -> ProjectScheduleResponse:
        """Return the existing project analysis contract."""
        project = await ProjectService(self.session).get_by_id(project_id)

        wp_result = await self.session.execute(
            select(WorkPackage).where(WorkPackage.project_id == project_id)
        )
        work_packages = list(wp_result.scalars().all())

        edges = await WorkPackageDependencyService(self.session).edges_for_project(
            project_id
        )

        working_time = WorkingTimeService(self.session)
        if work_packages:
            span_start = min(wp.start_date for wp in work_packages)
            span_end = max(
                max(wp.end_date for wp in work_packages),
                project.committed_delivery_date or project.end_date,
            )
            await working_time.prepare([], span_start, span_end)

        def _is_working(day: date) -> bool:
            profile = working_time.profile_for(_NO_RESOURCE, day)
            if profile is None:
                return False
            return profile.minutes_for_weekday(day.weekday()) > 0

        deadline = project.committed_delivery_date or project.end_date
        nodes = [
            ScheduleNode(
                id=wp.id,
                name=wp.name,
                start_date=wp.start_date,
                end_date=wp.end_date,
                lead_time_working_days=wp.lead_time_working_days,
            )
            for wp in work_packages
        ]
        analysis = analyse(nodes, edges, deadline, _is_working)
        durations = {
            node.id: duration_working_days(node, _is_working) for node in nodes
        }

        return ProjectScheduleResponse(
            project_id=project_id,
            deadline=deadline,
            deadline_is_commitment=project.committed_delivery_date is not None,
            nodes=[
                ScheduleNodeResponse(
                    work_package_id=n.id,
                    work_package_name=n.name,
                    earliest_start=n.earliest_start,
                    earliest_finish=n.earliest_finish,
                    latest_start=n.latest_start,
                    latest_finish=n.latest_finish,
                    float_working_days=n.float_working_days,
                    is_critical=n.is_critical,
                    duration_working_days=durations.get(n.id, 0),
                )
                for n in analysis
            ],
        )
