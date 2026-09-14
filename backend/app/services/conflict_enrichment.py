"""Batch-enrichment for Conflict entities into API-facing ConflictResponse objects.

Loads all related data (ConflictAssignments, Assignments, WorkPackages,
Projects, Resources) in bulk queries upfront, then assembles the responses
in-memory. This avoids the N+1 query pattern that made the /api/conflicts
endpoint slow (~150ms for 50 conflicts).
"""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.assignment import Assignment
from app.models.conflict import Conflict, ConflictAssignment
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource
from app.schemas.capacity import (
    ConflictAssignmentInfo,
    ConflictResponse,
    compute_severity,
)
from app.services.skill_mismatch import detect_mismatches


async def enrich_conflicts_batch(
    session: AsyncSession, conflicts: list[Conflict]
) -> list[ConflictResponse]:
    """Enrich a list of conflicts in bulk (2-5 queries total, not N×M)."""
    if not conflicts:
        return []

    conflict_ids = [c.id for c in conflicts]

    # 1. Load all ConflictAssignment links in one query.
    ca_stmt = select(ConflictAssignment).where(
        ConflictAssignment.conflict_id.in_(conflict_ids)
    )
    ca_result = await session.execute(ca_stmt)
    all_cas = list(ca_result.scalars().all())

    # Group by conflict_id.
    cas_by_conflict: dict[UUID, list[ConflictAssignment]] = {}
    for ca in all_cas:
        cas_by_conflict.setdefault(ca.conflict_id, []).append(ca)

    # 2. Load all referenced Assignments in one query.
    assignment_ids = list({ca.assignment_id for ca in all_cas})
    assignments_by_id: dict[UUID, Assignment] = {}
    if assignment_ids:
        a_stmt = select(Assignment).where(Assignment.id.in_(assignment_ids))
        a_result = await session.execute(a_stmt)
        for a in a_result.scalars().all():
            assignments_by_id[a.id] = a

    # 3. Load all referenced WorkPackages in one query.
    wp_ids = list({a.work_package_id for a in assignments_by_id.values()})
    wps_by_id: dict[UUID, WorkPackage] = {}
    if wp_ids:
        wp_stmt = select(WorkPackage).where(WorkPackage.id.in_(wp_ids))
        wp_result = await session.execute(wp_stmt)
        for loaded_wp in wp_result.scalars().all():
            wps_by_id[loaded_wp.id] = loaded_wp

    # 4. Load all referenced Projects in one query.
    project_ids = list({wp.project_id for wp in wps_by_id.values()})
    projects_by_id: dict[UUID, Project] = {}
    if project_ids:
        p_stmt = select(Project).where(Project.id.in_(project_ids))
        p_result = await session.execute(p_stmt)
        for p in p_result.scalars().all():
            projects_by_id[p.id] = p

    # 5. Load all resource names (personal + infra) in two queries.
    resource_ids = list(
        {c.resource_id for c in conflicts}
        | {a.resource_id for a in assignments_by_id.values()}
    )
    resource_names: dict[UUID, str] = {}
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

    # 6. Skill-mismatch detection via shared utility.
    mismatched_assignment_ids: set[UUID] = set()
    if wp_ids and assignment_ids:
        mismatch_tuples = [
            (a.id, a.resource_id, a.work_package_id) for a in assignments_by_id.values()
        ]
        all_resource_ids_for_skills = {
            a.resource_id for a in assignments_by_id.values()
        }
        mismatched_assignment_ids = await detect_mismatches(
            session,
            mismatch_tuples,
            set(wp_ids),
            all_resource_ids_for_skills,
        )

    # 7. Assemble responses in-memory.
    responses: list[ConflictResponse] = []
    for conflict in conflicts:
        cas = cas_by_conflict.get(conflict.id, [])
        assignment_infos: list[ConflictAssignmentInfo] = []

        for ca in cas:
            assignment = assignments_by_id.get(ca.assignment_id)
            if assignment is None:
                assignment_infos.append(
                    ConflictAssignmentInfo(assignment_id=ca.assignment_id)
                )
                continue

            wp: WorkPackage | None = wps_by_id.get(assignment.work_package_id)
            project: Project | None = None
            if wp is not None:
                project = projects_by_id.get(wp.project_id)

            assignment_infos.append(
                ConflictAssignmentInfo(
                    assignment_id=ca.assignment_id,
                    work_package_id=assignment.work_package_id,
                    work_package_name=wp.name if wp else None,
                    project_id=project.id if project else None,
                    project_name=project.name if project else None,
                    resource_id=assignment.resource_id,
                    resource_name=resource_names.get(assignment.resource_id),
                    start_date=assignment.start_date,
                    end_date=assignment.end_date,
                    allocation_percent=assignment.allocation_percent,
                    start_at=assignment.start_at,
                    end_at=assignment.end_at,
                    skill_mismatch=ca.assignment_id in mismatched_assignment_ids,
                )
            )

        # Sort by effective start date.
        def _sort_key(a: ConflictAssignmentInfo) -> tuple[date, str]:
            if a.start_date is not None:
                return (a.start_date, (a.project_name or "").lower())
            if a.start_at is not None:
                return (a.start_at.date(), (a.project_name or "").lower())
            return (date.max, (a.project_name or "").lower())

        assignment_infos.sort(key=_sort_key)

        severity, overload_ratio = compute_severity(
            conflict.total_assigned_percent, conflict.available_percent
        )

        responses.append(
            ConflictResponse(
                id=conflict.id,
                resource_id=conflict.resource_id,
                resource_name=resource_names.get(conflict.resource_id),
                resource_type=conflict.resource_type,
                start_date=conflict.start_date,
                end_date=conflict.end_date,
                total_assigned_percent=conflict.total_assigned_percent,
                available_percent=conflict.available_percent,
                severity=severity,
                overload_ratio=overload_ratio,
                detected_at=conflict.detected_at,
                assignments=assignment_infos,
            )
        )

    return responses


async def enrich_conflict(
    session: AsyncSession, conflict: Conflict
) -> ConflictResponse:
    """Enrich a single conflict. Delegates to batch for consistency."""
    results = await enrich_conflicts_batch(session, [conflict])
    return results[0]
