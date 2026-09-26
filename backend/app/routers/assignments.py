"""Router for Assignments with RBAC permission checks.

Write endpoints determine scope by looking up the assigned resource:
- Personal assignments → check department scope
- Infrastructure assignments → check location scope

Endpoints:
- GET    /assignments         — All assignments (filterable)
- POST   /assignments         — Create a new assignment
- GET    /assignments/{id}    — Single assignment
- PUT    /assignments/{id}    — Update an assignment
- DELETE /assignments/{id}    — Delete an assignment

Response payloads are enriched with ``resource_name`` / ``work_package_name`` /
``project_id`` / ``project_name`` so the frontend does not have to display
raw UUIDs.
"""

from collections.abc import Iterable
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.models.assignment import Assignment
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.user import User
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentCreateResponse,
    AssignmentPreviewRequest,
    AssignmentPreviewResponse,
    AssignmentResponse,
    AssignmentUpdate,
    UnmetRequirementResponse,
)
from app.schemas.pagination import PaginatedResponse
from app.services.assignment_preview import AssignmentPreviewService
from app.services.assignment_service import AssignmentService
from app.services.freeze_enforcement import enforce_freeze, span_of
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)
from app.services.planning_freeze import Span
from app.services.skill_mismatch import detect_mismatches
from app.services.time_zone import local_date, planning_zone
from app.services.unmet_requirements_service import get_unmet_requirements

router = APIRouter(prefix="/assignments", tags=["Assignments"])


async def _check_assignment_permission(
    session: AsyncSession,
    user: User,
    resource_id: UUID,
    resource_type: ResourceType | None = None,
) -> None:
    """Check write permission for an assignment based on the assigned resource.

    Looks up the resource to determine the appropriate scope value
    (department for personal, location for infrastructure).

    Args:
        session: Database session for resource lookup.
        user: The authenticated user.
        resource_id: The ID of the resource being assigned.
        resource_type: Optional hint for resource type to avoid extra lookups.

    Raises:
        HTTPException: 403 if the user lacks permission.

    """
    if resource_type == ResourceType.personal or resource_type is None:
        stmt = select(PersonalResource).where(PersonalResource.id == resource_id)
        result = await session.execute(stmt)
        personal = result.scalar_one_or_none()
        if personal is not None:
            check_write_permission(
                user, EntityType.assignment, group_id=personal.group_id
            )
            return

    if resource_type == ResourceType.infrastructure or resource_type is None:
        infra_stmt = select(InfrastructureResource).where(
            InfrastructureResource.id == resource_id
        )
        result = await session.execute(infra_stmt)
        infra = result.scalar_one_or_none()
        if infra is not None:
            check_write_permission(user, EntityType.assignment, group_id=infra.group_id)
            return

    # Resource not found — let the service layer handle the 404
    return


async def _build_enrichment_maps(
    session: AsyncSession,
    assignments: Iterable[Assignment],
    *,
    include_mismatch: bool = True,
) -> tuple[dict[UUID, str], dict[UUID, tuple[str, UUID | None, str | None]], set[UUID]]:
    """Return lookup tables for resource names, work-package metadata, and skill mismatches.

    - ``resource_names[id]`` → display name of the resource (personal or infra).
    - ``work_package_info[id]`` → tuple of ``(wp_name, project_id, project_name)``.
    - ``mismatched_assignment_ids`` → set of assignment IDs where the resource
      lacks at least one skill required by the work package (empty if
      ``include_mismatch=False``).

    Args:
        session: Async database session.
        assignments: Iterable of Assignment models to enrich.
        include_mismatch: Whether to run skill mismatch detection. Set to
            False to skip the (relatively expensive) detection when the
            caller does not need it.

    """
    assignment_list = list(assignments)
    resource_ids = {a.resource_id for a in assignment_list}
    work_package_ids = {a.work_package_id for a in assignment_list}

    resource_names: dict[UUID, str] = {}
    work_package_info: dict[UUID, tuple[str, UUID | None, str | None]] = {}

    if resource_ids:
        personal_stmt = select(PersonalResource).where(
            PersonalResource.id.in_(resource_ids)
        )
        for r in (await session.execute(personal_stmt)).scalars().all():
            resource_names[r.id] = r.name

        infra_stmt = select(InfrastructureResource).where(
            InfrastructureResource.id.in_(resource_ids)
        )
        for infra_r in (await session.execute(infra_stmt)).scalars().all():
            resource_names[infra_r.id] = infra_r.name

    if work_package_ids:
        wp_stmt = select(WorkPackage).where(WorkPackage.id.in_(work_package_ids))
        work_packages = list((await session.execute(wp_stmt)).scalars().all())
        project_ids = {wp.project_id for wp in work_packages}
        project_names: dict[UUID, str] = {}
        if project_ids:
            project_stmt = select(Project).where(Project.id.in_(project_ids))
            for p in (await session.execute(project_stmt)).scalars().all():
                project_names[p.id] = p.name
        for wp in work_packages:
            work_package_info[wp.id] = (
                wp.name,
                wp.project_id,
                project_names.get(wp.project_id),
            )

    # --- Skill mismatch detection via shared utility ---
    mismatched_assignment_ids: set[UUID] = set()
    if include_mismatch and assignment_list:
        mismatch_tuples = [
            (a.id, a.resource_id, a.work_package_id) for a in assignment_list
        ]
        mismatched_assignment_ids = await detect_mismatches(
            session, mismatch_tuples, work_package_ids, resource_ids
        )

    return resource_names, work_package_info, mismatched_assignment_ids


async def _enrich_one(
    session: AsyncSession, assignment: Assignment
) -> AssignmentResponse:
    """Enrich a single assignment with resolved names and mismatch status.

    Uses targeted single-row lookups instead of the batch map-building logic,
    avoiding unnecessary bulk queries when only one assignment is involved.
    """
    # Resolve resource name
    resource_name: str | None = None
    if assignment.resource_type == ResourceType.personal:
        res = await session.get(PersonalResource, assignment.resource_id)
        if res:
            resource_name = res.name
    else:
        res = await session.get(InfrastructureResource, assignment.resource_id)
        if res:
            resource_name = res.name

    # Resolve work package + project
    wp_name: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    wp = await session.get(WorkPackage, assignment.work_package_id)
    if wp:
        wp_name = wp.name
        project_id = wp.project_id
        project = await session.get(Project, wp.project_id)
        if project:
            project_name = project.name

    # Detect skill mismatch for this single assignment
    mismatched_ids = await detect_mismatches(
        session,
        [(assignment.id, assignment.resource_id, assignment.work_package_id)],
        {assignment.work_package_id},
        {assignment.resource_id},
    )

    return AssignmentResponse(
        id=assignment.id,
        resource_id=assignment.resource_id,
        resource_name=resource_name,
        resource_type=assignment.resource_type,
        work_package_id=assignment.work_package_id,
        work_package_name=wp_name,
        project_id=project_id,
        project_name=project_name,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        allocation_percent=assignment.allocation_percent,
        start_at=assignment.start_at,
        end_at=assignment.end_at,
        skill_mismatch=assignment.id in mismatched_ids,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _serialize(
    assignment: Assignment,
    resource_names: dict[UUID, str],
    work_package_info: dict[UUID, tuple[str, UUID | None, str | None]],
    mismatched_ids: set[UUID] | None = None,
) -> AssignmentResponse:
    """Serialize an Assignment model to the API response schema."""
    wp = work_package_info.get(assignment.work_package_id)
    wp_name = wp[0] if wp else None
    project_id = wp[1] if wp else None
    project_name = wp[2] if wp else None
    return AssignmentResponse(
        id=assignment.id,
        resource_id=assignment.resource_id,
        resource_name=resource_names.get(assignment.resource_id),
        resource_type=assignment.resource_type,
        work_package_id=assignment.work_package_id,
        work_package_name=wp_name,
        project_id=project_id,
        project_name=project_name,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        allocation_percent=assignment.allocation_percent,
        start_at=assignment.start_at,
        end_at=assignment.end_at,
        skill_mismatch=assignment.id in (mismatched_ids or set()),
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


@router.get(
    "",
    response_model=PaginatedResponse[AssignmentResponse],
    summary="List all assignments",
)
async def get_assignments(
    resource_id: UUID | None = Query(default=None, description="Filter by resource"),
    work_package_id: UUID | None = Query(
        default=None, description="Filter by work package"
    ),
    start_date: date | None = Query(
        default=None,
        alias="startDate",
        description="Filter: assignments active from this date",
    ),
    end_date: date | None = Query(
        default=None,
        alias="endDate",
        description="Filter: assignments active until this date",
    ),
    skill_mismatch: bool | None = Query(
        default=None,
        alias="skillMismatch",
        description="Filter: only assignments with skill mismatches (true) or without (false)",
    ),
    include_mismatch: bool = Query(
        default=True,
        alias="includeMismatch",
        description="Whether to compute skill mismatch status. Set to false to skip.",
    ),
    limit: int = Query(default=100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return all assignments with pagination, optionally filtered.

    Supports filtering by resource, work package, date range, and skill
    mismatch status. When ``skillMismatch=true``, only assignments where
    the resource lacks skills required by the work package are returned.

    Skill mismatch detection adds 2-3 queries per request. Pass
    ``includeMismatch=false`` to skip it when the caller does not display
    mismatch indicators (e.g. Gantt chart data loading).

    Args:
        resource_id: Optional filter by resource UUID.
        work_package_id: Optional filter by work package UUID.
        start_date: Optional filter for assignments active from this date.
        end_date: Optional filter for assignments active until this date.
        skill_mismatch: Optional filter by mismatch status.
        include_mismatch: Whether to compute skill_mismatch field (default true).
        limit: Maximum number of items to return.
        offset: Number of items to skip.
        session: Database session.

    Returns:
        Paginated list of enriched assignment records.

    """
    service = AssignmentService(session)
    assignments, total = await service.get_all(
        resource_id=resource_id,
        work_package_id=work_package_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    # Force mismatch computation when filtering by it
    needs_mismatch = include_mismatch or skill_mismatch is not None
    resource_names, wp_info, mismatches = await _build_enrichment_maps(
        session, assignments, include_mismatch=needs_mismatch
    )

    # Apply skill_mismatch filter post-enrichment (mismatch is computed in memory)
    if skill_mismatch is not None:
        if skill_mismatch:
            assignments = [a for a in assignments if a.id in mismatches]
        else:
            assignments = [a for a in assignments if a.id not in mismatches]
        total = len(assignments)

    items = [_serialize(a, resource_names, wp_info, mismatches) for a in assignments]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/preview",
    response_model=AssignmentPreviewResponse,
    summary="Preview the impact of an assignment without saving it",
)
async def preview_assignment(
    data: AssignmentPreviewRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Apply the same permission and freeze checks as a real assignment change."""
    service = AssignmentService(session)
    existing = (
        await service.get_by_id(data.assignment_id)
        if data.assignment_id is not None
        else None
    )
    if existing is not None:
        await _check_assignment_permission(
            session, current_user, existing.resource_id, existing.resource_type
        )
    await _check_assignment_permission(
        session, current_user, data.resource_id, data.resource_type
    )
    await enforce_freeze(
        session,
        current_user,
        before=span_of(existing) if existing is not None else None,
        after=Span(
            start=data.start_date
            or (local_date(data.start_at, planning_zone()) if data.start_at else None),
            end=data.end_date
            or (local_date(data.end_at, planning_zone()) if data.end_at else None),
        ),
    )
    return await AssignmentPreviewService(session).preview(data)


@router.post(
    "",
    response_model=AssignmentCreateResponse,
    status_code=201,
    summary="Create an assignment",
)
async def create_assignment(
    data: AssignmentCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new assignment for a personal or infrastructure resource.

    Args:
        data: Assignment creation data (resource, work package, dates, allocation).
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The created assignment with any conflict warnings.

    """
    await _check_assignment_permission(
        session, current_user, data.resource_id, data.resource_type
    )
    # No prior state for a creation; the requested dates are the only state to test.
    await enforce_freeze(
        session,
        current_user,
        before=None,
        after=Span(
            start=data.start_date
            or (local_date(data.start_at, planning_zone()) if data.start_at else None),
            end=data.end_date
            or (local_date(data.end_at, planning_zone()) if data.end_at else None),
        ),
    )
    service = AssignmentService(session)
    assignment, warnings = await service.create(
        resource_id=data.resource_id,
        resource_type=data.resource_type,
        work_package_id=data.work_package_id,
        start_date=data.start_date,
        end_date=data.end_date,
        allocation_percent=data.allocation_percent,
        start_at=data.start_at,
        end_at=data.end_at,
    )
    return AssignmentCreateResponse(
        assignment=await _enrich_one(session, assignment),
        warnings=warnings,
    )


@router.get(
    "/planning/unmet-requirements",
    response_model=list[UnmetRequirementResponse],
    summary="List unmet work package skill requirements",
)
async def list_unmet_requirements(
    resource_type: str | None = Query(
        default=None,
        description="Filter by resource type: 'personal' or 'infrastructure'",
    ),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return work package requirements where not enough matching resources are assigned.

    Only considers work packages whose end_date is today or in the future.
    Computes the gap between required and assigned resources per skill
    requirement. Only entries with gap > 0 are returned.

    Args:
        resource_type: Optional filter by resource type.
        session: Database session.

    Returns:
        List of unmet requirement entries with gap information.

    """
    return await get_unmet_requirements(session, resource_type=resource_type)


@router.get(
    "/planning/overview",
    summary="Combined planning overview (unmet + conflicts + mismatches)",
)
async def get_planning_overview(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return all data needed for the planning overview in a single response.

    Combines unmet requirements, active conflicts, and mismatched assignments
    to eliminate multiple client-side fetches. All three datasets are loaded
    within the same DB session for consistency.

    Mismatch detection reuses the results already computed inside
    ``enrich_conflicts_batch`` (for conflict-related assignments) and only
    runs an additional pass for assignments not covered by conflicts.

    Returns:
        Dict with keys: unmet_requirements, conflicts, mismatched_assignments.

    """
    from app.models.conflict import Conflict
    from app.services.conflict_enrichment import enrich_conflicts_batch

    # Load unmet requirements
    unmet = await get_unmet_requirements(session)

    # Load and enrich conflicts (includes mismatch detection internally)
    conflict_result = await session.execute(select(Conflict))
    conflicts = list(conflict_result.scalars().all())
    enriched_conflicts = await enrich_conflicts_batch(session, conflicts)

    # Extract mismatched assignment IDs already detected by conflict enrichment
    conflict_mismatch_ids: set[UUID] = set()
    conflict_assignment_ids: set[UUID] = set()
    for ec in enriched_conflicts:
        for ai in ec.assignments:
            conflict_assignment_ids.add(ai.assignment_id)
            if ai.skill_mismatch:
                conflict_mismatch_ids.add(ai.assignment_id)

    # Load remaining assignments not covered by conflicts and detect mismatches
    all_stmt = select(Assignment)
    all_assignments = list((await session.execute(all_stmt)).scalars().all())

    # Only detect mismatches for assignments NOT already checked by conflicts
    non_conflict_assignments = [
        a for a in all_assignments if a.id not in conflict_assignment_ids
    ]
    additional_mismatches: set[UUID] = set()
    if non_conflict_assignments:
        tuples = [
            (a.id, a.resource_id, a.work_package_id) for a in non_conflict_assignments
        ]
        wp_ids = {a.work_package_id for a in non_conflict_assignments}
        res_ids = {a.resource_id for a in non_conflict_assignments}
        additional_mismatches = await detect_mismatches(
            session, tuples, wp_ids, res_ids
        )

    # Combine all mismatched assignment IDs
    all_mismatch_ids = conflict_mismatch_ids | additional_mismatches
    if not all_mismatch_ids:
        return {
            "unmet_requirements": unmet,
            "conflicts": enriched_conflicts,
            "mismatched_assignments": [],
        }

    # Enrich only the mismatched assignments (not all 500+)
    mismatched_models = [a for a in all_assignments if a.id in all_mismatch_ids]
    resource_names, wp_info, _ = await _build_enrichment_maps(
        session, mismatched_models, include_mismatch=False
    )
    mismatched = [
        _serialize(a, resource_names, wp_info, all_mismatch_ids)
        for a in mismatched_models
    ]

    return {
        "unmet_requirements": unmet,
        "conflicts": enriched_conflicts,
        "mismatched_assignments": mismatched,
    }


@router.get(
    "/{assignment_id}",
    response_model=AssignmentResponse,
    summary="Retrieve a single assignment",
)
async def get_assignment(
    assignment_id: UUID,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
):
    """Return a single assignment by its ID.

    Args:
        assignment_id: The UUID of the assignment.
        session: Database session.

    Returns:
        The enriched assignment record.

    Raises:
        NotFoundError: If the assignment does not exist.

    """
    service = AssignmentService(session)
    assignment = await service.get_by_id(assignment_id)
    return await _enrich_one(session, assignment)


@router.put(
    "/{assignment_id}",
    response_model=AssignmentCreateResponse,
    summary="Update an assignment",
)
async def update_assignment(
    assignment_id: UUID,
    data: AssignmentUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update an existing assignment (partial update).

    Args:
        assignment_id: The UUID of the assignment to update.
        data: Fields to update.
        session: Database session.
        current_user: The authenticated user.

    Returns:
        The updated assignment with any conflict warnings.

    """
    # Load existing assignment to check permission on the current resource
    service = AssignmentService(session)
    existing = await service.get_by_id(assignment_id)
    await _check_assignment_permission(
        session, current_user, existing.resource_id, existing.resource_type
    )
    if data.resource_id is not None and data.resource_id != existing.resource_id:
        await _check_assignment_permission(
            session,
            current_user,
            data.resource_id,
            data.resource_type or existing.resource_type,
        )
    # BOTH states are tested. Checking only the requested dates would let somebody drag a
    # frozen booking into the open period, rewriting frozen history through an edit that
    # looks entirely legitimate afterwards.
    before = span_of(existing)
    await enforce_freeze(
        session,
        current_user,
        before=before,
        after=Span(
            start=data.start_date
            or (local_date(data.start_at, planning_zone()) if data.start_at else None)
            or before.start,
            end=data.end_date
            or (local_date(data.end_at, planning_zone()) if data.end_at else None)
            or before.end,
        ),
    )
    assignment, warnings = await service.update(
        assignment_id=assignment_id,
        resource_id=data.resource_id,
        resource_type=data.resource_type,
        work_package_id=data.work_package_id,
        start_date=data.start_date,
        end_date=data.end_date,
        allocation_percent=data.allocation_percent,
        start_at=data.start_at,
        end_at=data.end_at,
    )
    return AssignmentCreateResponse(
        assignment=await _enrich_one(session, assignment),
        warnings=warnings,
    )


@router.delete(
    "/{assignment_id}",
    status_code=204,
    summary="Delete an assignment",
)
async def delete_assignment(
    assignment_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete an assignment by ID.

    Args:
        assignment_id: The UUID of the assignment to delete.
        session: Database session.
        current_user: The authenticated user.

    """
    service = AssignmentService(session)
    existing = await service.get_by_id(assignment_id)
    await _check_assignment_permission(
        session, current_user, existing.resource_id, existing.resource_type
    )
    # Deleting frozen work is a change to frozen history, so a deletion is checked too.
    await enforce_freeze(session, current_user, before=span_of(existing), after=None)
    await service.delete(assignment_id)
