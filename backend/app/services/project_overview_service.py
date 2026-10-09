"""Focused project analysis orchestration, using the caller's read transaction.

Queries share one injected session. This service neither commits nor changes plans;
warnings and date assessments are returned for the planner to act on.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.conflict import Conflict, ConflictAssignment
from app.models.project import Project, WorkPackage
from app.schemas.project_overview import (
    CommitmentBreachResponse,
    DependencyViolationResponse,
    LateWorkPackage,
    ProjectOverviewItem,
    ProjectOverviewResponse,
)
from app.services.critical_path import (
    ScheduleNode,
    analyse,
)
from app.services.dependencies import check_violation
from app.services.lead_time import assess_commitment, schedule_warning
from app.services.work_package_dependency_service import (
    WorkPackageDependencyService,
)
from app.services.working_time_service import WorkingTimeService

_NO_RESOURCE = UUID(int=0)


def _progress_percent(start: date, end: date, today: date) -> float:
    """Compute progress percentage based on elapsed time."""
    if start == end:
        return 100.0 if today >= start else 0.0
    total = (end - start).days
    elapsed = (today - start).days
    ratio = elapsed / total if total > 0 else 0.0
    value = max(0.0, min(100.0, ratio * 100.0))
    return round(value, 1)


class ProjectOverviewService:
    """Coordinate project data and the existing planning calculations."""

    def __init__(self, session: AsyncSession):
        """Use the request-scoped session without owning its transaction."""
        self.session = session

    async def get_overview(
        self, project_ids: list[UUID] | None = None, *, today: date | None = None
    ) -> ProjectOverviewResponse:
        """Return the existing project analysis contract."""
        # Empty parsed list → return empty list.
        if project_ids is not None and len(project_ids) == 0:
            return ProjectOverviewResponse(projects=[])

        # Load projects (optionally filtered).
        project_stmt = select(Project)
        if project_ids is not None:
            project_stmt = project_stmt.where(Project.id.in_(project_ids))
        project_result = await self.session.execute(project_stmt)
        projects = list(project_result.scalars().all())
        if not projects:
            return ProjectOverviewResponse(projects=[])

        project_id_set: set[UUID] = {p.id for p in projects}

        # Load all work packages for these projects.
        wp_stmt = select(WorkPackage).where(WorkPackage.project_id.in_(project_id_set))
        wp_result = await self.session.execute(wp_stmt)
        work_packages = list(wp_result.scalars().all())
        wps_by_project: dict[UUID, list[WorkPackage]] = {}
        wp_to_project: dict[UUID, UUID] = {}
        for wp in work_packages:
            wps_by_project.setdefault(wp.project_id, []).append(wp)
            wp_to_project[wp.id] = wp.project_id

        # Conflict count per project via ConflictAssignment → Assignment → WorkPackage.
        conflict_counts: dict[UUID, int] = {}
        all_assignments: list[Assignment] = []
        if work_packages:
            # Load all conflicts with their assignments linked to these WPs.
            ca_stmt = select(ConflictAssignment)
            ca_result = await self.session.execute(ca_stmt)
            all_conflict_assignments = list(ca_result.scalars().all())

            a_stmt = select(Assignment)
            a_result = await self.session.execute(a_stmt)
            all_assignments = list(a_result.scalars().all())
            assignment_by_id: dict[UUID, Assignment] = {
                a.id: a for a in all_assignments
            }

            # Build conflict_id -> set of project_ids involved.
            conflict_projects: dict[UUID, set[UUID]] = {}
            for ca in all_conflict_assignments:
                assignment = assignment_by_id.get(ca.assignment_id)
                if assignment is None:
                    continue
                project_id = wp_to_project.get(assignment.work_package_id)
                if project_id is None or project_id not in project_id_set:
                    continue
                conflict_projects.setdefault(ca.conflict_id, set()).add(project_id)

            # Only count conflicts that actually persist as Conflict rows.
            c_stmt = select(Conflict).where(Conflict.id.in_(conflict_projects.keys()))
            c_result = await self.session.execute(c_stmt)
            existing_conflict_ids = {c.id for c in c_result.scalars().all()}

            for conflict_id, affected_projects in conflict_projects.items():
                if conflict_id not in existing_conflict_ids:
                    continue
                for project_id in affected_projects:
                    conflict_counts[project_id] = conflict_counts.get(project_id, 0) + 1

        # One working-time service for the whole overview. The lead-time check asks
        # whether a PROCESS fits, not whether one person is free, so it runs against
        # the default week profile and the site calendar rather than any resource's own
        # contract.
        working_time = WorkingTimeService(self.session)
        span_start = min(p.start_date for p in projects)
        span_end = max(
            max((wp.end_date for wp in work_packages), default=span_start),
            max(p.end_date for p in projects),
        )
        await working_time.prepare([], span_start, span_end)

        def _is_working_day(day: date) -> bool:
            """Whether the plant works on this date, per the default profile."""
            profile = working_time.profile_for(_NO_RESOURCE, day)
            if profile is None:
                return False
            return profile.minutes_for_weekday(day.weekday()) > 0

        # Dependency edges for every project in one pass. Per-project queries would make
        # the cost scale with how many projects the caller asked about, and the overview is
        # the one endpoint that asks about all of them.
        dependency_service = WorkPackageDependencyService(self.session)
        edges_by_project = await dependency_service.edges_for_projects(
            {wp.project_id for wp in work_packages}
        )

        # Dates and names for every work package involved, including predecessors that live
        # in another project — a link may cross project boundaries, and the warning belongs
        # to the side that can act on it.
        wp_by_id: dict[UUID, WorkPackage] = {wp.id: wp for wp in work_packages}
        missing_ids = {
            edge.predecessor_id
            for edges in edges_by_project.values()
            for edge in edges
            if edge.predecessor_id not in wp_by_id
        }
        if missing_ids:
            extra_result = await self.session.execute(
                select(WorkPackage).where(WorkPackage.id.in_(missing_ids))
            )
            for wp in extra_result.scalars().all():
                wp_by_id[wp.id] = wp

        today = today or date.today()

        # Compute average resource utilization per project.
        # For each project: find all resource_ids assigned to its WPs, compute
        # their average weekly utilization over the project timeframe.
        from app.services.capacity_service import CapacityService

        capacity_service = CapacityService(self.session)

        items: list[ProjectOverviewItem] = []
        for project in projects:
            project_wps = wps_by_project.get(project.id, [])
            active_count = sum(
                1 for wp in project_wps if wp.start_date <= today <= wp.end_date
            )
            future_deadlines = [
                wp.end_date for wp in project_wps if wp.end_date >= today
            ]
            next_deadline = (
                min(future_deadlines) if future_deadlines else project.end_date
            )

            # Resource utilization for this project.
            project_wp_ids = {wp.id for wp in project_wps}
            project_resource_ids: set[UUID] = set()
            for a in all_assignments:
                if a.work_package_id in project_wp_ids:
                    project_resource_ids.add(a.resource_id)

            avg_util: float | None = None
            if project_resource_ids:
                utils: list[float] = []
                for rid in project_resource_ids:
                    weeks = await capacity_service.get_weekly_utilization(
                        rid, project.start_date, project.end_date
                    )
                    if weeks:
                        total_available = sum(w.total_available for w in weeks)
                        total_assigned = sum(w.total_assigned for w in weeks)
                        if total_available > 0:
                            utils.append(total_assigned / total_available * 100)
                if utils:
                    avg_util = round(sum(utils) / len(utils), 1)

            late: list[LateWorkPackage] = []
            for wp in wps_by_project.get(project.id, []):
                warning = schedule_warning(
                    wp.start_date,
                    wp.end_date,
                    wp.lead_time_working_days,
                    _is_working_day,
                )
                if warning is not None:
                    late.append(
                        LateWorkPackage(
                            work_package_id=wp.id,
                            work_package_name=wp.name,
                            entered_end=warning.entered_end,
                            derived_end=warning.derived_end,
                            working_days_short=warning.working_days_short,
                        )
                    )
            late.sort(
                key=lambda item: (-item.working_days_short, item.work_package_name)
            )

            violations: list[DependencyViolationResponse] = []
            for edge in edges_by_project.get(project.id, []):
                predecessor = wp_by_id.get(edge.predecessor_id)
                successor = wp_by_id.get(edge.successor_id)
                if predecessor is None or successor is None:
                    # A link whose ends cannot both be resolved cannot be judged. The
                    # cascade makes this unreachable in practice; skipping beats guessing.
                    continue
                violation = check_violation(
                    edge, predecessor.end_date, successor.start_date, _is_working_day
                )
                if violation is None:
                    continue
                violations.append(
                    DependencyViolationResponse(
                        predecessor_id=predecessor.id,
                        predecessor_name=predecessor.name,
                        successor_id=successor.id,
                        successor_name=successor.name,
                        predecessor_end=violation.predecessor_end,
                        successor_start=violation.successor_start,
                        lag_working_days=violation.lag_working_days,
                        earliest_start=violation.earliest_start,
                        working_days_short=violation.working_days_short,
                    )
                )
            violations.sort(
                key=lambda item: (-item.working_days_short, item.successor_name)
            )

            # The deadline the schedule is measured against: the commitment where one
            # exists, otherwise the planned end. Measuring against a planned end that
            # already misses the customer date would report comfortable float on a late
            # project.
            analysis = analyse(
                [
                    ScheduleNode(
                        id=wp.id,
                        name=wp.name,
                        start_date=wp.start_date,
                        end_date=wp.end_date,
                        lead_time_working_days=wp.lead_time_working_days,
                    )
                    for wp in wps_by_project.get(project.id, [])
                ],
                edges_by_project.get(project.id, []),
                project.committed_delivery_date or project.end_date,
                _is_working_day,
            )
            min_float = min((n.float_working_days for n in analysis), default=None)
            critical_count = sum(1 for n in analysis if n.is_critical)

            # The commitment is assessed against BOTH the planned end and the furthest
            # derived end, because a plan that fits its own dates can still be unsupported
            # by the durations it is built from.
            derived_ends = [w.derived_end for w in late]
            breach = assess_commitment(
                project.committed_delivery_date,
                project.end_date,
                max(derived_ends) if derived_ends else None,
                _is_working_day,
            )
            breach_response = (
                CommitmentBreachResponse(
                    committed=breach.committed,
                    planned_end=breach.planned_end,
                    derived_end=breach.derived_end,
                    working_days_short=breach.working_days_short,
                    hidden=breach.hidden,
                )
                if breach is not None
                else None
            )

            items.append(
                ProjectOverviewItem(
                    project_id=project.id,
                    project_name=project.name,
                    start_date=project.start_date,
                    end_date=project.end_date,
                    progress_percent=_progress_percent(
                        project.start_date, project.end_date, today
                    ),
                    active_work_package_count=active_count,
                    next_deadline=next_deadline,
                    open_conflict_count=conflict_counts.get(project.id, 0),
                    average_resource_utilization_percent=avg_util,
                    late_work_packages=late,
                    commitment_breach=breach_response,
                    dependency_violations=violations,
                    min_float_working_days=min_float,
                    critical_work_package_count=critical_count,
                )
            )

        # Sort by start_date asc, then name asc.
        items.sort(key=lambda item: (item.start_date, item.project_name.lower()))
        return ProjectOverviewResponse(projects=items)
