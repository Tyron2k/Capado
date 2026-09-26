"""Service for computing unmet work package skill requirements.

Extracted from assignment_service to maintain single-responsibility.
Loads requirements, assignments, and resource skills in bulk, then
computes coverage in memory to avoid N+1 queries.

Suggestions are computed lazily: only resources with matching skill
attributes are loaded from the DB, avoiding full-table scans of all
active resources and their skill assignments.
"""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.assignment import Assignment
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.skill import (
    InfrastructureResourceSkill,
    PersonalResourceSkill,
    Skill,
    SkillAttribute,
)
from app.models.work_package_requirement import (
    RequirementMode,
    WorkPackageRequirement,
)
from app.schemas.assignment import ResourceSuggestion, UnmetRequirementResponse
from app.services.time_zone import local_date, local_day_bounds, planning_zone


def assignment_span(assignment: Assignment) -> tuple[date, date] | None:
    """The date range an assignment occupies, whichever shape it uses.

    ``assignments`` carries two mutually exclusive column sets: personal rows use
    ``start_date``/``end_date``, infrastructure rows use ``start_at``/``end_at`` and
    leave the dates NULL. Reading only one pair silently drops the other type rather
    than failing, which is how a fully booked hall came to report zero assignments
    (see docs/reference/known-limitations.md).

    Returns None for a row with neither pair populated, which should not occur but is
    not worth crashing a ranking over.
    """
    if assignment.start_date is not None and assignment.end_date is not None:
        return assignment.start_date, assignment.end_date
    if assignment.start_at is not None and assignment.end_at is not None:
        zone = planning_zone()
        return local_date(assignment.start_at, zone), local_date(
            assignment.end_at, zone
        )
    return None


def compute_coverage(
    mode: RequirementMode,
    min_allocation_percent: float,
    allocations: list[tuple[UUID, float]],
) -> float:
    """How much of a requirement the given allocations cover.

    Args:
        mode: How ``quantity`` is to be read.
        min_allocation_percent: In headcount mode, the allocation below which a
            resource does not count as present.
        allocations: ``(resource_id, allocation_percent)`` for every assignment
            whose resource carries a matching skill attribute. A resource may
            appear more than once — several assignments on one work package.

    Returns:
        Coverage in the same unit as ``quantity``: bodies in headcount mode,
        full-time equivalents in effort mode.

    In **headcount** mode a resource counts once, and only if its allocation
    reaches ``min_allocation_percent``. Four people at 25% cover nothing towards
    a two-person requirement, because effort does not substitute for presence:
    a cabin staffed by two, a lift needing two operators, a weld one person
    cannot hold. Multiple assignments of the same resource are counted once —
    one person is one body no matter how the paperwork is split.

    In **effort_fte** mode allocations sum, which is correct only where the work
    genuinely parallelises across bodies.

    Neither mode derives duration from effort. A work package's dates say how
    long the work takes; the requirement says who has to be there while it does.
    """
    if mode == RequirementMode.effort_fte:
        return sum(percent for _, percent in allocations) / 100.0

    counted: set[UUID] = set()
    for resource_id, percent in allocations:
        if percent >= min_allocation_percent:
            counted.add(resource_id)
    return float(len(counted))


async def get_unmet_requirements(
    session: AsyncSession,
    *,
    resource_type: str | None = None,
) -> list[UnmetRequirementResponse]:
    """Compute work package requirements that lack sufficient assigned resources.

    Only considers work packages whose end_date is today or in the future
    (past WPs are excluded). Loads data in bulk for coverage computation,
    then lazily loads suggestion candidates scoped to the specific skill
    attributes that are actually unmet.

    For each WorkPackageRequirement:
    - If skill_attribute_id is set: count assigned resources that have that
      exact attribute.
    - If skill_attribute_id is None: count assigned resources that have ANY
      attribute of the requirement's skill.

    Args:
        session: Async database session.
        resource_type: Optional filter — 'personal' or 'infrastructure'.
            When set, only requirements whose skill belongs to that resource
            type are returned.

    Returns:
        List of unmet requirements where assigned < required quantity.

    """
    # 1. Load all requirements
    requirements = list(
        (await session.execute(select(WorkPackageRequirement))).scalars().all()
    )
    if not requirements:
        return []

    # 2. Load referenced work packages — only those still active (end_date >= today)
    wp_ids = {r.work_package_id for r in requirements}
    today = date.today()
    work_packages = list(
        (
            await session.execute(
                select(WorkPackage).where(
                    WorkPackage.id.in_(wp_ids),
                    WorkPackage.end_date >= today,
                )
            )
        )
        .scalars()
        .all()
    )
    if not work_packages:
        return []

    wp_map: dict[UUID, WorkPackage] = {wp.id: wp for wp in work_packages}
    # Filter requirements to only those on active WPs
    active_wp_ids = set(wp_map.keys())
    requirements = [r for r in requirements if r.work_package_id in active_wp_ids]
    if not requirements:
        return []

    # 3. Load projects in bulk
    project_ids = {wp.project_id for wp in work_packages}
    projects = list(
        (await session.execute(select(Project).where(Project.id.in_(project_ids))))
        .scalars()
        .all()
    )
    project_map: dict[UUID, Project] = {p.id: p for p in projects}

    # 4. Load skills and attributes in one pass (used for display + coverage)
    skill_ids = {r.skill_id for r in requirements}
    skills = list(
        (await session.execute(select(Skill).where(Skill.id.in_(skill_ids))))
        .scalars()
        .all()
    )
    skill_map: dict[UUID, Skill] = {s.id: s for s in skills}

    # Apply resource_type filter based on skill.resource_type
    if resource_type:
        allowed_skill_ids = {s.id for s in skills if s.resource_type == resource_type}
        requirements = [r for r in requirements if r.skill_id in allowed_skill_ids]
        if not requirements:
            return []

    # Load ALL attributes for the relevant skills in a single query.
    # This serves both display-name lookup and the skill_to_attrs mapping,
    # eliminating the previous duplicate SkillAttribute query.
    all_skill_attributes = list(
        (
            await session.execute(
                select(SkillAttribute).where(SkillAttribute.skill_id.in_(skill_ids))
            )
        )
        .scalars()
        .all()
    )
    attr_map: dict[UUID, SkillAttribute] = {a.id: a for a in all_skill_attributes}
    skill_to_attrs: dict[UUID, set[UUID]] = {}
    for sa in all_skill_attributes:
        skill_to_attrs.setdefault(sa.skill_id, set()).add(sa.id)

    # 5. Load all assignments for active work packages
    assignments = list(
        (
            await session.execute(
                select(Assignment).where(Assignment.work_package_id.in_(active_wp_ids))
            )
        )
        .scalars()
        .all()
    )

    # Group assignments by work_package_id
    wp_assignments: dict[UUID, list[Assignment]] = {}
    for a in assignments:
        wp_assignments.setdefault(a.work_package_id, []).append(a)

    # 6. Collect assigned resource IDs and load their skills
    personal_resource_ids: set[UUID] = set()
    infra_resource_ids: set[UUID] = set()
    for a in assignments:
        if a.resource_type == ResourceType.personal:
            personal_resource_ids.add(a.resource_id)
        else:
            infra_resource_ids.add(a.resource_id)

    # resource_id → set of skill_attribute_ids (for assigned resources only)
    resource_skill_attrs: dict[UUID, set[UUID]] = {}

    if personal_resource_ids:
        personal_skills = list(
            (
                await session.execute(
                    select(PersonalResourceSkill).where(
                        PersonalResourceSkill.resource_id.in_(personal_resource_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for ps in personal_skills:
            resource_skill_attrs.setdefault(ps.resource_id, set()).add(
                ps.skill_attribute_id
            )

    if infra_resource_ids:
        infra_skills = list(
            (
                await session.execute(
                    select(InfrastructureResourceSkill).where(
                        InfrastructureResourceSkill.resource_id.in_(infra_resource_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for irs in infra_skills:
            resource_skill_attrs.setdefault(irs.resource_id, set()).add(
                irs.skill_attribute_id
            )

    # 7. Compute coverage for each requirement and collect unmet ones
    unmet_entries: list[
        tuple[WorkPackageRequirement, WorkPackage, Project, set[UUID], set[UUID], float]
    ] = []

    for req in requirements:
        wp = wp_map.get(req.work_package_id)
        if not wp:
            continue
        project = project_map.get(wp.project_id)
        if not project:
            continue

        # Determine which skill_attribute_ids satisfy this requirement
        if req.skill_attribute_id is not None:
            matching_attr_ids = {req.skill_attribute_id}
        else:
            matching_attr_ids = skill_to_attrs.get(req.skill_id, set())

        # Coverage depends on how the requirement is meant to be satisfied
        # (RequirementMode); see :func:`compute_coverage`.
        allocations: list[tuple[UUID, float]] = []
        assigned_resource_ids: set[UUID] = set()
        for a in wp_assignments.get(req.work_package_id, []):
            res_attrs = resource_skill_attrs.get(a.resource_id, set())
            if not (res_attrs & matching_attr_ids):
                continue
            assigned_resource_ids.add(a.resource_id)
            allocations.append((a.resource_id, a.allocation_percent or 100.0))

        assigned_coverage = compute_coverage(
            req.requirement_mode, req.min_allocation_percent, allocations
        )

        gap = req.quantity - assigned_coverage
        if gap > 0:
            unmet_entries.append(
                (
                    req,
                    wp,
                    project,
                    matching_attr_ids,
                    assigned_resource_ids,
                    assigned_coverage,
                )
            )

    if not unmet_entries:
        return []

    # 8. Lazy-load suggestion data scoped to actually-unmet attributes only
    all_needed_attr_ids: set[UUID] = set()
    for _, _, _, matching_ids, _, _ in unmet_entries:
        all_needed_attr_ids.update(matching_ids)

    suggestion_data = await _load_suggestion_data(
        session,
        needed_attr_ids=all_needed_attr_ids,
        work_packages=work_packages,
    )

    # 9. Build response
    results: list[UnmetRequirementResponse] = []

    for (
        req,
        wp,
        project,
        matching_attr_ids,
        assigned_resource_ids,
        assigned_coverage,
    ) in unmet_entries:
        gap = req.quantity - assigned_coverage
        skill = skill_map.get(req.skill_id)
        attr = attr_map.get(req.skill_attribute_id) if req.skill_attribute_id else None

        suggestions = _compute_suggestions(
            matching_attr_ids=matching_attr_ids,
            assigned_resource_ids=assigned_resource_ids,
            wp_start=wp.start_date,
            wp_end=wp.end_date,
            candidate_skill_attrs=suggestion_data.candidate_skill_attrs,
            resource_map=suggestion_data.resource_map,
            group_map=suggestion_data.group_map,
            resource_assignments=suggestion_data.resource_assignments,
        )

        results.append(
            UnmetRequirementResponse(
                work_package_id=wp.id,
                work_package_name=wp.name,
                project_id=project.id,
                project_name=project.name,
                start_date=wp.start_date,
                end_date=wp.end_date,
                skill_name=skill.name if skill else "Unknown",
                attribute_name=attr.name if attr else None,
                resource_type=skill.resource_type if skill else "personal",
                required_quantity=req.quantity,
                assigned_quantity=round(assigned_coverage, 2),
                gap=round(gap, 2),
                suggestions=suggestions,
            )
        )

    return results


class _SuggestionData:
    """Container for lazily-loaded suggestion candidate data."""

    __slots__ = (
        "candidate_skill_attrs",
        "resource_map",
        "group_map",
        "resource_assignments",
    )

    def __init__(
        self,
        candidate_skill_attrs: dict[UUID, set[UUID]],
        resource_map: dict[UUID, tuple[str, str, UUID]],
        group_map: dict[UUID, str],
        resource_assignments: dict[UUID, list[tuple[date, date]]],
    ):
        self.candidate_skill_attrs = candidate_skill_attrs
        self.resource_map = resource_map
        self.group_map = group_map
        self.resource_assignments = resource_assignments


async def _load_suggestion_data(
    session: AsyncSession,
    *,
    needed_attr_ids: set[UUID],
    work_packages: list[WorkPackage],
) -> _SuggestionData:
    """Load only those resources that hold at least one of the needed skill attributes.

    Instead of loading ALL active resources and ALL skill assignments, this
    queries only resources that have a matching skill attribute, drastically
    reducing data transferred for large tenants.

    Args:
        session: Async database session.
        needed_attr_ids: Skill attribute IDs that are required by unmet entries.
        work_packages: Active work packages (for date-range overlap query).

    Returns:
        _SuggestionData with scoped candidate information.

    """
    if not needed_attr_ids:
        return _SuggestionData({}, {}, {}, {})

    # Find resources that hold at least one needed attribute
    personal_skill_rows = list(
        (
            await session.execute(
                select(PersonalResourceSkill).where(
                    PersonalResourceSkill.skill_attribute_id.in_(needed_attr_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    infra_skill_rows = list(
        (
            await session.execute(
                select(InfrastructureResourceSkill).where(
                    InfrastructureResourceSkill.skill_attribute_id.in_(needed_attr_ids)
                )
            )
        )
        .scalars()
        .all()
    )

    # Build candidate_skill_attrs: resource_id → set of attribute_ids
    candidate_skill_attrs: dict[UUID, set[UUID]] = {}
    candidate_personal_ids: set[UUID] = set()
    candidate_infra_ids: set[UUID] = set()

    for ps in personal_skill_rows:
        candidate_skill_attrs.setdefault(ps.resource_id, set()).add(
            ps.skill_attribute_id
        )
        candidate_personal_ids.add(ps.resource_id)
    for irs in infra_skill_rows:
        candidate_skill_attrs.setdefault(irs.resource_id, set()).add(
            irs.skill_attribute_id
        )
        candidate_infra_ids.add(irs.resource_id)

    # Load only the candidate resources (active only)
    resource_map: dict[UUID, tuple[str, str, UUID]] = {}
    group_ids: set[UUID] = set()

    if candidate_personal_ids:
        personal_resources = list(
            (
                await session.execute(
                    select(PersonalResource).where(
                        PersonalResource.id.in_(candidate_personal_ids),
                        PersonalResource.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in personal_resources:
            resource_map[r.id] = (r.name, "personal", r.group_id)
            group_ids.add(r.group_id)

    if candidate_infra_ids:
        infra_resources = list(
            (
                await session.execute(
                    select(InfrastructureResource).where(
                        InfrastructureResource.id.in_(candidate_infra_ids),
                        InfrastructureResource.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        for infra_r in infra_resources:
            resource_map[infra_r.id] = (
                infra_r.name,
                "infrastructure",
                infra_r.group_id,
            )
            group_ids.add(infra_r.group_id)

    # Remove inactive resources from candidate_skill_attrs
    candidate_skill_attrs = {
        rid: attrs
        for rid, attrs in candidate_skill_attrs.items()
        if rid in resource_map
    }

    # Load group names for candidates only
    group_map: dict[UUID, str] = {}
    if group_ids:
        groups = list(
            (
                await session.execute(
                    select(ResourceGroup).where(ResourceGroup.id.in_(group_ids))
                )
            )
            .scalars()
            .all()
        )
        group_map = {g.id: g.name for g in groups}

    # Load overlapping assignments for busyness ranking (scoped to candidate resources)
    min_start = min(
        (wp.start_date for wp in work_packages if wp.start_date), default=None
    )
    max_end = max((wp.end_date for wp in work_packages if wp.end_date), default=None)

    resource_assignments: dict[UUID, list[tuple[date, date]]] = {}
    candidate_ids = set(resource_map.keys())
    if min_start and max_end and candidate_ids:
        from sqlalchemy import and_, or_

        range_start, _ = local_day_bounds(min_start, planning_zone())
        _, range_end = local_day_bounds(max_end, planning_zone())

        overlapping = list(
            (
                await session.execute(
                    select(Assignment).where(
                        Assignment.resource_id.in_(candidate_ids),
                        # Both booking shapes. Filtering on start_date/end_date alone
                        # made every infrastructure booking invisible here: those rows
                        # keep their dates NULL and use start_at/end_at, and in SQL
                        # `NULL <= x` is not true. A fully booked hall therefore
                        # reported zero assignments and ranked as the LEAST busy
                        # candidate — silently, since nothing raised.
                        or_(
                            and_(
                                Assignment.start_date <= max_end,
                                Assignment.end_date >= min_start,
                            ),
                            and_(
                                Assignment.start_at < range_end,
                                Assignment.end_at > range_start,
                            ),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for a in overlapping:
            span = assignment_span(a)
            if span is not None:
                resource_assignments.setdefault(a.resource_id, []).append(span)

    return _SuggestionData(
        candidate_skill_attrs=candidate_skill_attrs,
        resource_map=resource_map,
        group_map=group_map,
        resource_assignments=resource_assignments,
    )


def _compute_suggestions(
    *,
    matching_attr_ids: set[UUID],
    assigned_resource_ids: set[UUID],
    wp_start: date,
    wp_end: date,
    candidate_skill_attrs: dict[UUID, set[UUID]],
    resource_map: dict[UUID, tuple[str, str, UUID]],
    group_map: dict[UUID, str],
    resource_assignments: dict[UUID, list[tuple[date, date]]],
    max_suggestions: int = 5,
) -> list[ResourceSuggestion]:
    """Find up to max_suggestions resources for an unmet requirement.

    Candidates must have a matching skill attribute and not already be
    assigned to the work package. They are ranked by fewest overlapping
    assignments in the WP period (least busy first).

    Args:
        matching_attr_ids: Skill attribute IDs that satisfy the requirement.
        assigned_resource_ids: Resource IDs already assigned to this WP.
        wp_start: Work package start date.
        wp_end: Work package end date.
        candidate_skill_attrs: Pre-filtered resource skill attribute mappings.
        resource_map: Resource ID to (name, resource_type, group_id) mapping.
        group_map: Group ID to group name mapping.
        resource_assignments: Resource ID to list of (start, end) assignment ranges.
        max_suggestions: Maximum number of suggestions to return.

    Returns:
        List of ResourceSuggestion sorted by overlapping assignments (least busy first).

    """
    candidates: list[tuple[int, UUID]] = []

    for resource_id, skill_attrs in candidate_skill_attrs.items():
        if not (skill_attrs & matching_attr_ids):
            continue
        if resource_id in assigned_resource_ids:
            continue
        if resource_id not in resource_map:
            continue

        # Count assignments overlapping the WP period
        overlapping = 0
        for a_start, a_end in resource_assignments.get(resource_id, []):
            if a_start <= wp_end and a_end >= wp_start:
                overlapping += 1

        candidates.append((overlapping, resource_id))

    candidates.sort(key=lambda c: c[0])
    top = candidates[:max_suggestions]

    suggestions: list[ResourceSuggestion] = []
    for overlapping, resource_id in top:
        name, resource_type, group_id = resource_map[resource_id]
        group_name = group_map.get(group_id)
        suggestions.append(
            ResourceSuggestion(
                resource_id=resource_id,
                resource_name=name,
                resource_type=resource_type,
                group_name=group_name,
                overlapping_assignments=overlapping,
            )
        )

    return suggestions
