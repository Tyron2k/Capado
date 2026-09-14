"""Resolving the display names a resource carries but does not store.

``group_name`` and ``site_name`` are denormalised onto resource responses so a client can render a
table without a second request per row. They are therefore NOT columns, and every endpoint that
returns a resource has to resolve them — which is exactly the sort of duty that gets forgotten.

IT WAS FORGOTTEN. The paginated list endpoints returned the raw model rows, so both fields fell back
to their schema default of ``""`` on every response, always. Nothing in the frontend consumed those
endpoints, so nothing surfaced it; an API consumer would have read ``group_name: ""`` as "this
resource has no group name", because an empty string is a statement rather than an error.

This module exists so there is ONE implementation. Before it there were two inline copies of the
group lookup in :mod:`app.services.hierarchy_service` — one per tree endpoint — and adding the list
endpoints would have made four. A copy per call site is how the two paths drifted apart in the first
place.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.schemas.resource import ResourceResponse


async def group_name_map(
    session: AsyncSession, group_ids: list[UUID]
) -> dict[UUID, str]:
    """Map group id to name for the ids given, skipping the query when there are none."""
    if not group_ids:
        return {}
    result = await session.execute(
        select(ResourceGroup).where(ResourceGroup.id.in_(group_ids))
    )
    return {g.id: g.name for g in result.scalars().all()}


async def site_name_map(session: AsyncSession, site_ids: list[UUID]) -> dict[UUID, str]:
    """Map site id to name for the ids given, skipping the query when there are none.

    Deliberately tolerant: an id with no row and a resource with no id both end up as the empty
    string rather than an error. A single-plant operator never files anything at a site, and that
    must not read as missing data.
    """
    if not site_ids:
        return {}
    result = await session.execute(select(Site).where(Site.id.in_(site_ids)))
    return {s.id: s.name for s in result.scalars().all()}


async def resolve_names(
    session: AsyncSession, resources: list
) -> tuple[dict[UUID, str], dict[UUID, str]]:
    """Both maps for a list of resources, in two queries regardless of row count.

    Batched on purpose: resolving per row would turn one list request into one query per resource,
    which is the shape that makes a paginated endpoint slower the more it is actually used.
    """
    groups = await group_name_map(session, list({r.group_id for r in resources}))
    sites = await site_name_map(
        session, list({r.site_id for r in resources if r.site_id is not None})
    )
    return groups, sites


async def to_responses(
    session: AsyncSession, resources: Sequence[Any]
) -> list[ResourceResponse]:
    """Build responses for a list of resource rows, with the display names resolved.

    Two queries for the whole list, not two per row.
    """
    if not resources:
        return []
    groups, sites = await resolve_names(session, list(resources))
    return [
        ResourceResponse(
            id=r.id,
            name=r.name,
            group_id=r.group_id,
            group_name=groups.get(r.group_id, ""),
            site_id=r.site_id,
            site_name=sites.get(r.site_id, "") if r.site_id else "",
            is_active=r.is_active,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in resources
    ]


async def to_response(session: AsyncSession, resource: Any) -> ResourceResponse:
    """Build the response for a single resource row, with the display names resolved.

    Goes through the list form rather than having its own body: a second implementation for one row
    is how the two paths came to disagree in the first place, and the saving would be one query.
    """
    built = await to_responses(session, [resource])
    return built[0]
