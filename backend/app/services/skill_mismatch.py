"""Shared utility for detecting skill mismatches between resources and work packages.

A resource has a skill mismatch when it does not satisfy ANY of the work
package's requirements. For example, if a WP requires "4 Electricians +
2 Mechanics", an Electrician satisfies the Electrician requirement and is
NOT mismatched. Only a resource with no relevant skills is flagged.

This module is used by:
- ``conflict_enrichment.enrich_conflicts_batch``
- ``assignments router._build_enrichment_maps``
- ``unmet_requirements_service.get_unmet_requirements``
"""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.assignment import Assignment
from app.models.skill import (
    InfrastructureResourceSkill,
    PersonalResourceSkill,
    SkillAttribute,
)
from app.models.work_package_requirement import WorkPackageRequirement
from app.services.qualification import HeldQualification, satisfies
from app.services.unmet_requirements_service import assignment_span


async def detect_mismatches(
    session: AsyncSession,
    assignments: list[tuple[UUID, UUID, UUID]],
    work_package_ids: set[UUID],
    resource_ids: set[UUID],
) -> set[UUID]:
    """Detect assignment IDs where the resource lacks all required skills.

    Each item in ``assignments`` is a tuple of
    ``(assignment_id, resource_id, work_package_id)``.

    Args:
        session: Async database session.
        assignments: List of (assignment_id, resource_id, work_package_id) tuples.
        work_package_ids: Set of work package IDs involved.
        resource_ids: Set of resource IDs involved.

    Returns:
        Set of assignment IDs that have a skill mismatch.

    """
    if not assignments or not work_package_ids or not resource_ids:
        return set()

    # 1. Load WP requirements
    req_stmt = select(WorkPackageRequirement).where(
        WorkPackageRequirement.work_package_id.in_(work_package_ids)
    )
    requirements = list((await session.execute(req_stmt)).scalars().all())

    # Build wp_id → set of (skill_id, skill_attribute_id | None, min_level | None)
    wp_required_skills: dict[UUID, set[tuple[UUID, UUID | None, int | None]]] = {}
    for req in requirements:
        wp_required_skills.setdefault(req.work_package_id, set()).add(
            (req.skill_id, req.skill_attribute_id, req.min_level)
        )

    if not wp_required_skills:
        return set()

    # 2. Load resource skill assignments
    resource_id_list = list(resource_ids)
    personal_skills_stmt = select(PersonalResourceSkill).where(
        PersonalResourceSkill.resource_id.in_(resource_id_list)
    )
    infra_skills_stmt = select(InfrastructureResourceSkill).where(
        InfrastructureResourceSkill.resource_id.in_(resource_id_list)
    )
    personal_skills = list(
        (await session.execute(personal_skills_stmt)).scalars().all()
    )
    infra_skills = list((await session.execute(infra_skills_stmt)).scalars().all())

    # 3. Map attribute → skill
    all_attr_ids = {s.skill_attribute_id for s in personal_skills} | {
        s.skill_attribute_id for s in infra_skills
    }
    attr_to_skill: dict[UUID, UUID] = {}
    if all_attr_ids:
        attr_stmt = select(SkillAttribute).where(SkillAttribute.id.in_(all_attr_ids))
        for attr in (await session.execute(attr_stmt)).scalars().all():
            attr_to_skill[attr.id] = attr.skill_id

    # 4. Build resource_id → attribute → the qualification's bounds.
    #
    # Keyed by attribute rather than a flat set, because a match now has to check the
    # qualification's validity window and level, not merely that it exists.
    resource_skills: dict[UUID, dict[tuple[UUID, UUID], HeldQualification]] = {}
    for s in personal_skills:
        skill_id = attr_to_skill.get(s.skill_attribute_id)
        if skill_id:
            resource_skills.setdefault(s.resource_id, {})[
                (skill_id, s.skill_attribute_id)
            ] = HeldQualification(
                valid_from=s.valid_from, valid_until=s.valid_until, level=s.level
            )
    for infra_s in infra_skills:
        skill_id = attr_to_skill.get(infra_s.skill_attribute_id)
        if skill_id:
            resource_skills.setdefault(infra_s.resource_id, {})[
                (skill_id, infra_s.skill_attribute_id)
            ] = HeldQualification(
                valid_from=infra_s.valid_from,
                valid_until=infra_s.valid_until,
                level=infra_s.level,
            )

    # 4b. When each assignment happens. Loaded here rather than taken as a parameter so
    # that no caller can forget it and silently lose the validity check — a qualification
    # expiring in March must not cover work planned for April, and checking against
    # "today" would answer that it does.
    assignment_ids = [a[0] for a in assignments]
    spans: dict[UUID, tuple[date, date] | None] = {}
    if assignment_ids:
        span_result = await session.execute(
            select(Assignment).where(Assignment.id.in_(assignment_ids))
        )
        for assignment in span_result.scalars().all():
            spans[assignment.id] = assignment_span(assignment)

    # 5. Check each assignment
    mismatched_ids: set[UUID] = set()
    for assignment_id, resource_id, work_package_id in assignments:
        required = wp_required_skills.get(work_package_id)
        if not required:
            continue
        held = resource_skills.get(resource_id, {})
        span = spans.get(assignment_id)
        start, end = span if span is not None else (None, None)
        satisfies_any = False
        for skill_id, attr_id, min_level in required:
            if attr_id is not None:
                qualification = held.get((skill_id, attr_id))
                if qualification is not None and satisfies(
                    qualification, min_level, start, end
                ):
                    satisfies_any = True
                    break
            else:
                # Requirement names the skill but no specific attribute: any held
                # attribute of that skill counts, provided it is valid and high enough.
                if any(
                    s_id == skill_id and satisfies(q, min_level, start, end)
                    for (s_id, _), q in held.items()
                ):
                    satisfies_any = True
                    break
        if not satisfies_any:
            mismatched_ids.add(assignment_id)

    return mismatched_ids
