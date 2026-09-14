"""HierarchyService: Flat resource lists with group names and conflict counts.

Resources are organized via groups only (no parent_id hierarchy).
The "tree" endpoints now return flat lists with group_name and conflict_count.
"""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.conflict import Conflict
from app.models.resource import (
    InfrastructureResource,
    PersonalResource,
)
from app.schemas.resource import ResourceListItemResponse
from app.services import resource_names


async def _conflict_count_map(
    session: AsyncSession, resource_ids: list[UUID]
) -> dict[UUID, int]:
    """Count persisted conflicts per resource ID in a single query."""
    if not resource_ids:
        return {}
    stmt = (
        select(Conflict.resource_id, func.count(Conflict.id))
        .where(Conflict.resource_id.in_(resource_ids))
        .group_by(Conflict.resource_id)
    )
    result = await session.execute(stmt)
    return {row[0]: int(row[1]) for row in result.all()}


async def get_personal_tree(
    session: AsyncSession,
) -> list[ResourceListItemResponse]:
    """Return all active personal resources as a flat list with group names and conflict counts."""
    statement = select(PersonalResource).where(PersonalResource.is_active.is_(True))
    result = await session.execute(statement)
    resources = list(result.scalars().all())

    # Shared with the list endpoints on purpose: this lookup used to be inline here, once per tree
    # endpoint, and the paginated endpoints did not do it at all — which is how they came to return
    # an empty group_name and site_name on every response.
    group_map, site_map = await resource_names.resolve_names(session, resources)
    conflict_counts = await _conflict_count_map(session, [r.id for r in resources])

    return [
        ResourceListItemResponse(
            id=r.id,
            name=r.name,
            group_id=r.group_id,
            group_name=group_map.get(r.group_id, ""),
            site_id=r.site_id,
            site_name=site_map.get(r.site_id, "") if r.site_id else "",
            is_active=r.is_active,
            conflict_count=conflict_counts.get(r.id, 0),
        )
        for r in resources
    ]


async def get_infrastructure_tree(
    session: AsyncSession,
) -> list[ResourceListItemResponse]:
    """Return all active infrastructure resources as a flat list with group names and conflict counts."""
    statement = select(InfrastructureResource).where(
        InfrastructureResource.is_active.is_(True)
    )
    result = await session.execute(statement)
    resources = list(result.scalars().all())

    # Shared with the list endpoints on purpose: this lookup used to be inline here, once per tree
    # endpoint, and the paginated endpoints did not do it at all — which is how they came to return
    # an empty group_name and site_name on every response.
    group_map, site_map = await resource_names.resolve_names(session, resources)
    conflict_counts = await _conflict_count_map(session, [r.id for r in resources])

    return [
        ResourceListItemResponse(
            id=r.id,
            name=r.name,
            group_id=r.group_id,
            group_name=group_map.get(r.group_id, ""),
            site_id=r.site_id,
            site_name=site_map.get(r.site_id, "") if r.site_id else "",
            is_active=r.is_active,
            conflict_count=conflict_counts.get(r.id, 0),
        )
        for r in resources
    ]
