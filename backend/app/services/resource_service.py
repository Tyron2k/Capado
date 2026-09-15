"""ResourceService: CRUD operations for personal and infrastructure resources.

Both resource types reference a ResourceGroup via group_id.
No parent_id hierarchy — resources are organized exclusively via groups.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.absence import Absence
from app.models.assignment import Assignment
from app.models.audit import AuditAction, AuditLog
from app.models.calendar import ResourceWorkProfile
from app.models.conflict import Conflict, ConflictAssignment
from app.models.resource import (
    InfrastructureResource,
    PersonalResource,
    ResourceType,
)
from app.models.skill import PersonalResourceSkill
from app.models.user import User
from app.services.partial_update import UNSET, UnsetType


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --- PersonalResource CRUD ---


async def create_personal_resource(
    session: AsyncSession,
    name: str,
    group_id: UUID,
    site_id: UUID | None = None,
) -> PersonalResource:
    """Create a new personal resource."""
    if not name or not name.strip():
        raise BusinessRuleError("Name is required.", field="name")

    resource = PersonalResource(
        name=name.strip(),
        group_id=group_id,
        site_id=site_id,
    )
    session.add(resource)
    await session.commit()
    return resource


async def get_all_personal_resources(
    session: AsyncSession,
    group_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[PersonalResource], int]:
    """Return active personal resources with pagination, optionally filtered by group.

    Args:
        session: Database session.
        group_id: Optional group filter.
        limit: Maximum number of items to return.
        offset: Number of items to skip.

    Returns:
        Tuple of (list of resources, total count).
    """
    from sqlmodel import func

    base = select(PersonalResource).where(PersonalResource.is_active.is_(True))
    if group_id is not None:
        base = base.where(PersonalResource.group_id == group_id)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    # ORDER BY is not cosmetic here: OFFSET/LIMIT over an unordered query lets Postgres return the
    # same row on two pages and skip another entirely, because nothing fixes the order between the
    # two requests. Sorting by name also matches what the Excel export already does, so the screen
    # and the file no longer disagree. id breaks ties so the order is total, not merely stable-ish.
    statement = (
        base.order_by(PersonalResource.name, PersonalResource.id)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(statement)
    return list(result.scalars().all()), total


async def get_personal_resource_by_id(
    session: AsyncSession,
    resource_id: UUID,
) -> PersonalResource:
    """Load a personal resource by ID or raise NotFoundError."""
    resource = await session.get(PersonalResource, resource_id)
    if resource is None:
        raise NotFoundError("PersonalResource", resource_id)
    return resource


async def update_personal_resource(
    session: AsyncSession,
    resource_id: UUID,
    name: str | None = None,
    group_id: UUID | None = None,
    site_id: UUID | None | UnsetType = UNSET,
) -> PersonalResource:
    """Update a personal resource.

    ``site_id`` takes UNSET rather than None as its "leave alone" value, because None is a
    meaningful value here: a resource can legitimately stop belonging to a site. Reusing None for
    both would make removal impossible to express — the bug the other fields still have, and which
    matters less for them because a resource always has a group and a name.
    """
    resource = await get_personal_resource_by_id(session, resource_id)

    if name is not None:
        if not name.strip():
            raise BusinessRuleError("Name is required.", field="name")
        resource.name = name.strip()
    if group_id is not None:
        resource.group_id = group_id
    if not isinstance(site_id, UnsetType):
        resource.site_id = site_id

    resource.updated_at = _utcnow()
    session.add(resource)
    await session.commit()
    from app.services.conflict_refresh import refresh_resources

    await refresh_resources(session, [resource_id])
    return resource


@dataclass
class ErasureReport:
    """What an erasure removed, per table. Returned so the caller can evidence the request."""

    resource_id: UUID
    skills: int = 0
    work_profiles: int = 0
    conflict_assignments: int = 0
    conflicts: int = 0
    assignments: int = 0
    absences: int = 0
    audit_entries: int = 0
    unlinked_accounts: int = 0


async def erase_personal_resource(
    session: AsyncSession,
    resource_id: UUID,
) -> ErasureReport:
    """Permanently delete a person and every planning row that refers to them.

    ERASURE, NOT DEACTIVATION, and the two are separate on purpose. Deactivation keeps the row so the
    person stays visible in historical plans; this removes them. Both exist because they answer
    different questions — "this person no longer works here" and "this person exercised their right
    to erasure".

    WHY REAL DELETION RATHER THAN ANONYMISATION. Capado is not a record of what happened; ADR-009
    fixes that boundary explicitly. So a departed person's history has no purpose to preserve, and
    for FUTURE planning the gap their removal leaves is exactly the information a planner needs to
    see. Anonymising would keep rows whose only remaining function is to make plans look staffed.

    THE POLYMORPHIC REFERENCES ARE WHY THIS IS HAND-WRITTEN. ``absences``, ``assignments``,
    ``conflicts`` and ``resource_work_profiles`` carry ``resource_id`` with **no foreign key** — one
    key cannot target both resource tables — so the database will not cascade for us and cannot
    complain if we forget a table. Each is deleted explicitly, and the count of each is returned so a
    caller (and the tests) can see that none was silently skipped.

    WHAT IS DELIBERATELY LEFT ALONE:

    - **Baselines.** ``baseline_service.snapshot_state`` freezes projects, work packages and
      assignments — never ``personal_resources`` — so a frozen payload holds a ``resource_id`` UUID
      and no name. After erasure that UUID resolves to nothing, which is what makes deletion here
      GDPR-complete rather than cosmetic. Rewriting baselines would corrupt the historical record to
      remove data that is not in it.
    - **Other resources' conflicts.** An assignment belongs to exactly one resource and conflicts are
      per resource, so removing this person cannot change anybody else's conflict state. No global
      refresh is needed, and doing one anyway would hide that fact from the next reader.

    THE AUDIT TRAIL IS THE ONE PLACE A NAME CAN SURVIVE. ``audit_log.changes`` stores
    ``{"field": {"from": ..., "to": ...}}`` in clear text, so a rename of this person put their name
    there. Those rows are removed. Deletions themselves are audited with an EMPTY changes dict
    (``audit.py`` writes ``entry(..., AuditAction.deleted, {})``), so the deletions performed here add
    no personal data — but their entries are keyed to the same ids and go too.

    One entry is then written by hand recording that an erasure happened, with no personal content.
    Keeping nothing at all would leave the operator unable to evidence that they honoured the
    request; keeping the old entries would defeat the request itself.

    Commits once, at the end. The service owns the transaction here because resources are
    service-owned — see ``tests/test_transaction_boundary.py``.
    """
    resource = await get_personal_resource_by_id(session, resource_id)
    report = ErasureReport(resource_id=resource.id)

    # Skills and work profiles: keyed directly on the resource.
    report.skills = (
        await session.execute(
            delete(PersonalResourceSkill).where(
                PersonalResourceSkill.resource_id == resource_id
            )
        )
    ).rowcount or 0
    report.work_profiles = (
        await session.execute(
            delete(ResourceWorkProfile).where(
                ResourceWorkProfile.resource_id == resource_id
            )
        )
    ).rowcount or 0

    # Conflicts before their join rows would orphan the join, so the join goes first. Both are in
    # UNAUDITED_TABLES, so neither produces audit noise.
    conflict_ids = list(
        (
            await session.execute(
                select(Conflict.id).where(
                    Conflict.resource_id == resource_id,
                    Conflict.resource_type == ResourceType.personal,
                )
            )
        )
        .scalars()
        .all()
    )
    if conflict_ids:
        report.conflict_assignments = (
            await session.execute(
                delete(ConflictAssignment).where(
                    ConflictAssignment.conflict_id.in_(conflict_ids)
                )
            )
        ).rowcount or 0
        report.conflicts = (
            await session.execute(delete(Conflict).where(Conflict.id.in_(conflict_ids)))
        ).rowcount or 0

    assignment_ids = list(
        (
            await session.execute(
                select(Assignment.id).where(
                    Assignment.resource_id == resource_id,
                    Assignment.resource_type == ResourceType.personal,
                )
            )
        )
        .scalars()
        .all()
    )
    absence_ids = list(
        (
            await session.execute(
                select(Absence.id).where(
                    Absence.resource_id == resource_id,
                    Absence.resource_type == ResourceType.personal,
                )
            )
        )
        .scalars()
        .all()
    )

    if assignment_ids:
        report.assignments = (
            await session.execute(
                delete(Assignment).where(Assignment.id.in_(assignment_ids))
            )
        ).rowcount or 0
    if absence_ids:
        report.absences = (
            await session.execute(delete(Absence).where(Absence.id.in_(absence_ids)))
        ).rowcount or 0

    # The account link is nulled by the foreign key (ON DELETE SET NULL, migration 026). Counted
    # here rather than trusted, because "the FK handles it" is exactly the kind of claim that stops
    # being true after a schema change and fails silently.
    report.unlinked_accounts = len(
        list(
            (
                await session.execute(
                    select(User.id).where(User.resource_id == resource_id)
                )
            )
            .scalars()
            .all()
        )
    )

    await session.delete(resource)
    # Flush so the listener's own deletion entries exist before the audit sweep removes them.
    await session.flush()

    touched_ids = [resource_id, *assignment_ids, *absence_ids]
    report.audit_entries = (
        await session.execute(
            delete(AuditLog).where(AuditLog.entity_id.in_(touched_ids))
        )
    ).rowcount or 0

    session.add(
        AuditLog(
            entity_type="personal_resources",
            entity_id=resource_id,
            action=AuditAction.deleted,
            changes={},
            reason=(
                "Erasure of a person and their planning data on request. No personal content is "
                "retained; the identifier is kept so the operator can evidence that this request "
                "was honoured."
            ),
        )
    )

    await session.commit()
    return report


async def soft_delete_personal_resource(
    session: AsyncSession,
    resource_id: UUID,
) -> PersonalResource:
    """Soft-delete (deactivate) a personal resource.

    DEACTIVATION, NOT ERASURE. The row stays, so the person keeps appearing in historical plans and
    can be reactivated. For an Art. 17 GDPR erasure request use :func:`erase_personal_resource`,
    which is a different intent and deliberately a different endpoint.
    """
    resource = await get_personal_resource_by_id(session, resource_id)
    resource.is_active = False
    resource.updated_at = _utcnow()
    session.add(resource)
    await session.commit()
    return resource


# --- InfrastructureResource CRUD ---


async def create_infrastructure_resource(
    session: AsyncSession,
    name: str,
    group_id: UUID,
    site_id: UUID | None = None,
) -> InfrastructureResource:
    """Create a new infrastructure resource."""
    if not name or not name.strip():
        raise BusinessRuleError("Name is required.", field="name")

    resource = InfrastructureResource(
        name=name.strip(),
        group_id=group_id,
        site_id=site_id,
    )
    session.add(resource)
    await session.commit()
    return resource


async def get_all_infrastructure_resources(
    session: AsyncSession,
    group_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[InfrastructureResource], int]:
    """Return active infrastructure resources with pagination, optionally filtered by group.

    Args:
        session: Database session.
        group_id: Optional group filter.
        limit: Maximum number of items to return.
        offset: Number of items to skip.

    Returns:
        Tuple of (list of resources, total count).
    """
    from sqlmodel import func

    base = select(InfrastructureResource).where(
        InfrastructureResource.is_active.is_(True)
    )
    if group_id is not None:
        base = base.where(InfrastructureResource.group_id == group_id)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    # See get_all_personal_resources: paginating without ORDER BY is a correctness bug, not just an
    # untidy list. Plain alphabetical by name — deliberately NOT a natural sort that reads digits out
    # of the name, so "Kabine 10" sorts before "Kabine 2". Name them "01", "02" if that matters;
    # a special-case sort would be a rule nobody can see in the data.
    statement = (
        base.order_by(InfrastructureResource.name, InfrastructureResource.id)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(statement)
    return list(result.scalars().all()), total


async def get_infrastructure_resource_by_id(
    session: AsyncSession,
    resource_id: UUID,
) -> InfrastructureResource:
    """Load an infrastructure resource by ID or raise NotFoundError."""
    resource = await session.get(InfrastructureResource, resource_id)
    if resource is None:
        raise NotFoundError("InfrastructureResource", resource_id)
    return resource


async def update_infrastructure_resource(
    session: AsyncSession,
    resource_id: UUID,
    name: str | None = None,
    group_id: UUID | None = None,
    site_id: UUID | None | UnsetType = UNSET,
) -> InfrastructureResource:
    """Update an infrastructure resource. See ``update_personal_resource`` on ``site_id``/UNSET."""
    resource = await get_infrastructure_resource_by_id(session, resource_id)

    if name is not None:
        if not name.strip():
            raise BusinessRuleError("Name is required.", field="name")
        resource.name = name.strip()
    if group_id is not None:
        resource.group_id = group_id
    if not isinstance(site_id, UnsetType):
        resource.site_id = site_id

    resource.updated_at = _utcnow()
    session.add(resource)
    await session.commit()
    from app.services.conflict_refresh import refresh_resources

    await refresh_resources(session, [resource_id])
    return resource


async def soft_delete_infrastructure_resource(
    session: AsyncSession,
    resource_id: UUID,
) -> InfrastructureResource:
    """Soft-delete (deactivate) an infrastructure resource."""
    resource = await get_infrastructure_resource_by_id(session, resource_id)
    resource.is_active = False
    resource.updated_at = _utcnow()
    session.add(resource)
    await session.commit()
    return resource
