"""API router for Projects and WorkPackages with RBAC permission checks.

Write endpoints check project scope for editors.
"""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.models.assignment import Assignment
from app.models.conflict import Conflict, ConflictAssignment
from app.models.project import Project, WorkPackage
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.project import (
    ProjectCreate,
    ProjectFolderCreate,
    ProjectFolderDeleteResponse,
    ProjectFolderResponse,
    ProjectFolderUpdate,
    ProjectResponse,
    ProjectUpdate,
    WorkPackageCreate,
    WorkPackageCreateResponse,
    WorkPackageDependenciesResponse,
    WorkPackageDependencyCreate,
    WorkPackageDependencyResponse,
    WorkPackageDependencyUpdate,
    WorkPackageResponse,
    WorkPackageUpdate,
    WorkPackageUpdateResponse,
)
from app.schemas.project_overview import (
    CommitmentBreachResponse,
    DependencyViolationResponse,
    LateWorkPackage,
    ProjectOverviewItem,
    ProjectOverviewResponse,
    ProjectScheduleResponse,
    ScheduleNodeResponse,
)
from app.services.critical_path import (
    ScheduleNode,
    analyse,
    duration_working_days,
)
from app.services.dependencies import DependencyEdge, check_violation
from app.services.lead_time import assess_commitment, schedule_warning
from app.services.partial_update import UNSET
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)
from app.services.project_enrichment import enrich_project, enrich_projects
from app.services.project_folder_service import ProjectFolderService
from app.services.project_service import ProjectService
from app.services.work_package_dependency_service import (
    WorkPackageDependencyService,
)
from app.services.work_package_service import WorkPackageService
from app.services.working_time_service import WorkingTimeService

# The lead-time check is about the plant's calendar, not a person's contract, so it
# resolves the DEFAULT week profile. WorkingTimeService keys profiles by resource, so
# a sentinel id with no binding falls through to that default.
_NO_RESOURCE = UUID("00000000-0000-0000-0000-000000000000")

router = APIRouter()


def _parse_folder(value: str | None) -> UUID | Literal["unfiled"] | None:
    """Turn the folder_id query parameter into a filter.

    Accepts a folder id, the literal "unfiled", or nothing. A malformed id is a client
    error rather than a silently ignored filter — quietly returning the unfiltered
    list would look like the folder simply being empty.
    """
    if value is None:
        return None
    if value.strip().lower() == "unfiled":
        return "unfiled"
    try:
        return UUID(value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="folder_id must be a folder id or the literal 'unfiled'.",
        ) from exc


def _parse_project_ids(raw: str | None) -> list[UUID] | None:
    """Parse comma-separated project_ids query value.

    Returns ``None`` if not provided; an empty list if only whitespace/empty
    tokens remain after parsing; raises ``HTTPException(400)`` on invalid UUIDs.
    """
    if raw is None:
        return None
    tokens = [t.strip() for t in raw.split(",")]
    tokens = [t for t in tokens if t]
    if not tokens:
        return []
    parsed: list[UUID] = []
    for token in tokens:
        try:
            parsed.append(UUID(token))
        except ValueError as err:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid project_ids element: {token!r}",
            ) from err
    return parsed


def _progress_percent(start: date, end: date, today: date) -> float:
    """Compute progress percentage based on elapsed time."""
    if start == end:
        return 100.0 if today >= start else 0.0
    total = (end - start).days
    elapsed = (today - start).days
    ratio = elapsed / total if total > 0 else 0.0
    value = max(0.0, min(100.0, ratio * 100.0))
    return round(value, 1)


# --- Project Endpoints ---


@router.get(
    "/projects/overview",
    response_model=ProjectOverviewResponse,
    summary="Get project overview with KPIs",
)
async def get_project_overview(
    project_ids: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> ProjectOverviewResponse:
    """Return aggregated KPIs per project for the project overview.

    Returns progress, active work packages, next deadline, open conflicts,
    and average resource utilization percentage per project.
    """
    parsed_ids = _parse_project_ids(project_ids)

    # Empty parsed list → return empty list.
    if parsed_ids is not None and len(parsed_ids) == 0:
        return ProjectOverviewResponse(projects=[])

    # Load projects (optionally filtered).
    project_stmt = select(Project)
    if parsed_ids is not None:
        project_stmt = project_stmt.where(Project.id.in_(parsed_ids))
    project_result = await session.execute(project_stmt)
    projects = list(project_result.scalars().all())
    if not projects:
        return ProjectOverviewResponse(projects=[])

    project_id_set: set[UUID] = {p.id for p in projects}

    # Load all work packages for these projects.
    wp_stmt = select(WorkPackage).where(WorkPackage.project_id.in_(project_id_set))
    wp_result = await session.execute(wp_stmt)
    work_packages = list(wp_result.scalars().all())
    wps_by_project: dict[UUID, list[WorkPackage]] = {}
    wp_to_project: dict[UUID, UUID] = {}
    for wp in work_packages:
        wps_by_project.setdefault(wp.project_id, []).append(wp)
        wp_to_project[wp.id] = wp.project_id

    # Conflict count per project via ConflictAssignment → Assignment → WorkPackage.
    conflict_counts: dict[UUID, int] = {}
    if work_packages:
        # Load all conflicts with their assignments linked to these WPs.
        ca_stmt = select(ConflictAssignment)
        ca_result = await session.execute(ca_stmt)
        all_conflict_assignments = list(ca_result.scalars().all())

        a_stmt = select(Assignment)
        a_result = await session.execute(a_stmt)
        all_assignments = list(a_result.scalars().all())
        assignment_by_id: dict[UUID, Assignment] = {a.id: a for a in all_assignments}

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
        c_result = await session.execute(c_stmt)
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
    working_time = WorkingTimeService(session)
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
    dependency_service = WorkPackageDependencyService(session)
    edges_by_project: dict[UUID, list[DependencyEdge]] = {}
    for project_id_key in project_id_set:
        edges_by_project[project_id_key] = await dependency_service.edges_for_project(
            project_id_key
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
        extra_result = await session.execute(
            select(WorkPackage).where(WorkPackage.id.in_(missing_ids))
        )
        for wp in extra_result.scalars().all():
            wp_by_id[wp.id] = wp

    today = date.today()

    # Compute average resource utilization per project.
    # For each project: find all resource_ids assigned to its WPs, compute
    # their average weekly utilization over the project timeframe.
    from app.services.capacity_service import CapacityService

    capacity_service = CapacityService(session)

    items: list[ProjectOverviewItem] = []
    for project in projects:
        project_wps = wps_by_project.get(project.id, [])
        active_count = sum(
            1 for wp in project_wps if wp.start_date <= today <= wp.end_date
        )
        future_deadlines = [wp.end_date for wp in project_wps if wp.end_date >= today]
        next_deadline = min(future_deadlines) if future_deadlines else project.end_date

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
        late.sort(key=lambda item: (-item.working_days_short, item.work_package_name))

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


# --- Project Folder Endpoints ---
#
# Folders come before projects in this file because they are the coarser object, and
# an unfiled project is the normal case: nothing here has to be used at all.


@router.get(
    "/project-folders",
    response_model=list[ProjectFolderResponse],
    summary="List all project folders",
)
async def get_project_folders(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return every folder, ordered by position then name.

    Unpaginated: folders are a navigation aid maintained by hand, so the count stays
    small, and a tree delivered one page at a time cannot be rendered as a tree.

    Args:
        session: Database session.
        _current_user: Authenticated user.

    Returns:
        All folders in a stable order.
    """
    return await ProjectFolderService(session).get_all()


@router.post(
    "/project-folders",
    response_model=ProjectFolderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project folder",
)
async def create_project_folder(
    data: ProjectFolderCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a folder, optionally inside another.

    Args:
        data: Name, optional parent, optional position.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        The created folder.
    """
    check_write_permission(current_user, EntityType.project)
    return await ProjectFolderService(session).create(
        name=data.name,
        parent_id=data.parent_id,
        position=data.position,
        external_ref=data.external_ref,
        customer_id=data.customer_id,
    )


@router.put(
    "/project-folders/{folder_id}",
    response_model=ProjectFolderResponse,
    summary="Update a project folder",
)
async def update_project_folder(
    folder_id: UUID,
    data: ProjectFolderUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Rename, move, or reorder a folder.

    Sending ``parent_id`` as null moves it to the top level; omitting the field
    leaves the parent unchanged. A move that would place a folder inside its own
    subtree is refused.

    Args:
        folder_id: The folder to update.
        data: Fields to change.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        The updated folder.
    """
    check_write_permission(current_user, EntityType.project)
    sent = data.model_fields_set
    return await ProjectFolderService(session).update(
        folder_id=folder_id,
        name=data.name,
        parent_id=data.parent_id if "parent_id" in sent else UNSET,
        position=data.position,
        external_ref=data.external_ref if "external_ref" in sent else UNSET,
        customer_id=data.customer_id if "customer_id" in sent else UNSET,
    )


@router.delete(
    "/project-folders/{folder_id}",
    response_model=ProjectFolderDeleteResponse,
    summary="Delete a project folder",
)
async def delete_project_folder(
    folder_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a folder without deleting anything that was in it.

    Projects inside become unfiled and sub-folders move up one level. Nothing is
    cascaded, because a project carries work packages and assignments and removing a
    grouping must never be able to remove a plan.

    Args:
        folder_id: The folder to delete.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        How many projects were unfiled and how many sub-folders moved up.
    """
    check_write_permission(current_user, EntityType.project)
    unfiled, moved = await ProjectFolderService(session).delete(folder_id)
    return ProjectFolderDeleteResponse(projects_unfiled=unfiled, subfolders_moved=moved)


# --- Project Endpoints ---


@router.get(
    "/projects",
    response_model=PaginatedResponse[ProjectResponse],
    summary="List all projects",
)
async def get_projects(
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    folder_id: str | None = Query(
        default=None,
        description=(
            "A folder id to list the projects filed under it, or 'unfiled' for "
            "projects in no folder. Omit for everything."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve projects with pagination.

    Args:
        limit: Maximum number of items to return.
        offset: Number of items to skip.
        folder_id: A folder id to list the projects filed under it, or "unfiled" for
            projects in no folder. Omitted returns everything.
        session: Database session.

    Returns:
        Paginated list of projects matching the filter.

    """
    service = ProjectService(session)
    projects, total = await service.get_all(
        limit=limit, offset=offset, folder_filter=_parse_folder(folder_id)
    )
    # Enriched rather than returned raw: the resolved customer is a computed field,
    # and a raw ORM object would serialise it as empty.
    return PaginatedResponse(
        items=await enrich_projects(session, projects),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
)
async def create_project(
    data: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new project.

    Admins can always create projects. Editors with at least one project
    in their scope can also create new projects — the new project is
    automatically added to their scope_project_ids.

    Args:
        data: Project creation data.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The newly created project.

    Raises:
        HTTPException: 403 if the user is a viewer or an editor without
            any project scope.

    """
    from app.models.user import UserRole

    if current_user.role == UserRole.viewer:
        check_write_permission(current_user, EntityType.project, project_id=None)

    if current_user.role == UserRole.editor and not current_user.scope_project_ids:
        # Editors need at least one project in their scope to create new ones
        check_write_permission(current_user, EntityType.project, project_id=None)

    service = ProjectService(session)
    project = await service.create(
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
        folder_id=data.folder_id,
        position=data.position,
        external_ref=data.external_ref,
        committed_delivery_date=data.committed_delivery_date,
        customer_id=data.customer_id,
        priority=data.priority,
    )

    # Auto-scope: add the new project to the editor's scope_project_ids
    if current_user.role == UserRole.editor:
        existing_ids = list(current_user.scope_project_ids or [])
        existing_ids.append(project.id)
        current_user.scope_project_ids = existing_ids
        session.add(current_user)
        await session.commit()

    return await enrich_project(session, project)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Retrieve a single project",
)
async def get_project(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve a single project by its ID.

    Args:
        project_id: The UUID of the project.
        session: Database session.

    Returns:
        The project record.

    Raises:
        NotFoundError: If the project does not exist.

    """
    service = ProjectService(session)
    project = await service.get_by_id(project_id)
    return await enrich_project(session, project)


@router.put(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Update a project",
)
async def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update a project's name or date range.

    Args:
        project_id: The UUID of the project to update.
        data: Fields to update (name, start_date, end_date).
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The updated project record.

    """
    check_write_permission(current_user, EntityType.project, project_id=project_id)
    service = ProjectService(session)
    # Only fields the client actually SENT are forwarded. folder_id and external_ref
    # are nullable, so an explicit null has to mean "take out of the folder" / "clear
    # it" — which a plain None default cannot express.
    sent = data.model_fields_set
    project = await service.update(
        project_id=project_id,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
        folder_id=data.folder_id if "folder_id" in sent else UNSET,
        position=data.position,
        external_ref=data.external_ref if "external_ref" in sent else UNSET,
        committed_delivery_date=(
            data.committed_delivery_date if "committed_delivery_date" in sent else UNSET
        ),
        customer_id=data.customer_id if "customer_id" in sent else UNSET,
        priority=data.priority,
    )
    return await enrich_project(session, project)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
)
async def delete_project(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a project and its associated work packages.

    Args:
        project_id: The UUID of the project to delete.
        session: Database session.
        current_user: The authenticated user.

    """
    check_write_permission(current_user, EntityType.project, project_id=project_id)
    service = ProjectService(session)
    await service.delete(project_id)


# --- WorkPackage Endpoints (nested under projects) ---


@router.get(
    "/projects/{project_id}/work-packages",
    response_model=PaginatedResponse[WorkPackageResponse],
    summary="List work packages of a project",
)
async def get_work_packages(
    project_id: UUID,
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve work packages belonging to a project with pagination.

    Args:
        project_id: The UUID of the project.
        limit: Maximum number of items to return.
        offset: Number of items to skip.
        session: Database session.

    Returns:
        Paginated list of work packages for the project.

    """
    service = WorkPackageService(session)
    work_packages, total = await service.get_by_project(
        project_id, limit=limit, offset=offset
    )
    return PaginatedResponse(
        items=work_packages, total=total, limit=limit, offset=offset
    )


@router.post(
    "/projects/{project_id}/work-packages",
    response_model=WorkPackageCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a work package",
)
async def create_work_package(
    project_id: UUID,
    data: WorkPackageCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new work package within a project.

    Args:
        project_id: The UUID of the parent project.
        data: Work package creation data (name, start_date, end_date).
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The created work package with any warnings.

    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageService(session)
    work_package, warnings = await service.create(
        lead_time_working_days=data.lead_time_working_days,
        project_id=project_id,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    return WorkPackageCreateResponse(
        work_package=WorkPackageResponse.model_validate(work_package),
        warnings=warnings,
    )


@router.get(
    "/projects/{project_id}/work-packages/{work_package_id}",
    response_model=WorkPackageResponse,
    summary="Retrieve a single work package",
)
async def get_work_package(
    project_id: UUID,
    work_package_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve a single work package by its ID.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The UUID of the work package.
        session: Database session.

    Returns:
        The work package record.

    Raises:
        NotFoundError: If the work package does not exist.

    """
    service = WorkPackageService(session)
    work_package = await service.get_by_id(work_package_id)
    return work_package


@router.put(
    "/projects/{project_id}/work-packages/{work_package_id}",
    response_model=WorkPackageUpdateResponse,
    summary="Update a work package",
)
async def update_work_package(
    project_id: UUID,
    work_package_id: UUID,
    data: WorkPackageUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update a work package's name or date range.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The UUID of the work package to update.
        data: Fields to update (name, start_date, end_date).
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The updated work package with any warnings.

    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageService(session)
    wp_sent = data.model_fields_set
    work_package, warnings = await service.update(
        lead_time_working_days=data.lead_time_working_days,
        completed_at=data.completed_at if "completed_at" in wp_sent else UNSET,
        work_package_id=work_package_id,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    return WorkPackageUpdateResponse(
        work_package=WorkPackageResponse.model_validate(work_package),
        warnings=warnings,
    )


@router.delete(
    "/projects/{project_id}/work-packages/{work_package_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a work package",
)
async def delete_work_package(
    project_id: UUID,
    work_package_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a work package and cascade-delete its assignments.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The UUID of the work package to delete.
        session: Database session.
        current_user: The authenticated user.

    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageService(session)
    await service.delete(work_package_id)


# --- Work Package Dependency Endpoints ---
#
# Nested under the work package that is the SUCCESSOR, because that is the side whose
# dates a violation asks somebody to move. "What has to finish before this can start" is
# the question a planner has while looking at one package.


@router.get(
    "/projects/{project_id}/work-packages/{work_package_id}/dependencies",
    response_model=WorkPackageDependenciesResponse,
    summary="List dependencies of a work package",
)
async def get_work_package_dependencies(
    project_id: UUID,
    work_package_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return links in both directions for one work package.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The work package to inspect.
        session: Database session.
        _current_user: Authenticated user.

    Returns:
        Predecessors and successors as separate lists.
    """
    service = WorkPackageDependencyService(session)
    predecessors, successors = await service.list_for_work_package(work_package_id)
    return WorkPackageDependenciesResponse(
        predecessors=[
            WorkPackageDependencyResponse.model_validate(d) for d in predecessors
        ],
        successors=[
            WorkPackageDependencyResponse.model_validate(d) for d in successors
        ],
    )


@router.post(
    "/projects/{project_id}/work-packages/{work_package_id}/dependencies",
    response_model=WorkPackageDependencyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a dependency to a work package",
)
async def create_work_package_dependency(
    project_id: UUID,
    work_package_id: UUID,
    data: WorkPackageDependencyCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Record that another work package has to finish before this one starts.

    A link that would close a cycle is refused: "A after B after A" cannot be scheduled
    at all. Dates that merely contradict the link are accepted and reported as a
    warning, because that is an ordinary intermediate state on the way to a fixed plan.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The successor — the package that waits.
        data: The predecessor and the lag in working days.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        The created link.
    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageDependencyService(session)
    return await service.create(
        predecessor_id=data.predecessor_id,
        successor_id=work_package_id,
        lag_working_days=data.lag_working_days,
    )


@router.put(
    "/projects/{project_id}/work-packages/{work_package_id}/dependencies/{dependency_id}",
    response_model=WorkPackageDependencyResponse,
    summary="Change the lag on a dependency",
)
async def update_work_package_dependency(
    project_id: UUID,
    work_package_id: UUID,
    dependency_id: UUID,
    data: WorkPackageDependencyUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Change the waiting time between two linked work packages.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The successor the link hangs on.
        dependency_id: The link to change.
        data: The new lag in working days.
        session: Database session.
        current_user: Authenticated user.

    Returns:
        The updated link.
    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageDependencyService(session)
    return await service.update_lag(dependency_id, data.lag_working_days)


@router.delete(
    "/projects/{project_id}/work-packages/{work_package_id}/dependencies/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a dependency",
)
async def delete_work_package_dependency(
    project_id: UUID,
    work_package_id: UUID,
    dependency_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Remove a link. Neither work package is touched.

    Args:
        project_id: The UUID of the parent project.
        work_package_id: The successor the link hangs on.
        dependency_id: The link to remove.
        session: Database session.
        current_user: Authenticated user.
    """
    check_write_permission(current_user, EntityType.work_package, project_id=project_id)
    service = WorkPackageDependencyService(session)
    await service.delete(dependency_id)


# --- Schedule analysis ---


@router.get(
    "/projects/{project_id}/schedule",
    response_model=ProjectScheduleResponse,
    summary="Critical path and float for one project",
)
async def get_project_schedule(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Forward and backward pass over the project's work packages.

    Reports, per package, the earliest and latest it can start and finish, its float in
    working days, and whether it is on the critical path.

    The deadline is the committed delivery date where one exists, otherwise the planned
    end — and which of the two was used is part of the response, because float measured
    against a planned end that already misses the customer date reads far more
    comfortable than the situation is.

    Args:
        project_id: The project to analyse.
        session: Database session.
        _current_user: Authenticated user.

    Returns:
        The deadline used and one entry per work package.

    Raises:
        NotFoundError: If the project does not exist.
    """
    project = await ProjectService(session).get_by_id(project_id)

    wp_result = await session.execute(
        select(WorkPackage).where(WorkPackage.project_id == project_id)
    )
    work_packages = list(wp_result.scalars().all())

    edges = await WorkPackageDependencyService(session).edges_for_project(project_id)

    working_time = WorkingTimeService(session)
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
    durations = {node.id: duration_working_days(node, _is_working) for node in nodes}

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
