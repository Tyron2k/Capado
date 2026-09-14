"""AutocompleteService: Suche nach aktiven Ressourcen für Typeahead-Vorschläge."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.resource import InfrastructureResource, PersonalResource
from app.schemas.autocomplete import AutocompleteResultResponse


async def search_resources(
    session: AsyncSession,
    q: str,
    type: str,
) -> list[AutocompleteResultResponse]:
    """Search active resources by name (case-insensitive substring).

    Limited to 10 results, sorted alphabetically by name.
    """
    if type == "personal":
        return await _search_personal(session, q)
    else:
        return await _search_infrastructure(session, q)


async def _search_personal(
    session: AsyncSession,
    q: str,
) -> list[AutocompleteResultResponse]:
    """Search active personal resources by name."""
    from app.models.resource_group import ResourceGroup

    statement = (
        select(PersonalResource, ResourceGroup.name.label("group_name"))
        .outerjoin(ResourceGroup, PersonalResource.group_id == ResourceGroup.id)
        .where(PersonalResource.is_active == True)  # noqa: E712
        .where(PersonalResource.name.ilike(f"%{q}%"))
        .order_by(PersonalResource.name)
        .limit(10)
    )

    result = await session.execute(statement)
    rows = result.all()

    return [
        AutocompleteResultResponse(
            id=row[0].id,
            name=row[0].name,
            type="personal",
            detail=row[1] or "",
        )
        for row in rows
    ]


async def _search_infrastructure(
    session: AsyncSession,
    q: str,
) -> list[AutocompleteResultResponse]:
    """Search active infrastructure resources by name."""
    from app.models.resource_group import ResourceGroup

    statement = (
        select(InfrastructureResource, ResourceGroup.name.label("group_name"))
        .outerjoin(ResourceGroup, InfrastructureResource.group_id == ResourceGroup.id)
        .where(InfrastructureResource.is_active == True)  # noqa: E712
        .where(InfrastructureResource.name.ilike(f"%{q}%"))
        .order_by(InfrastructureResource.name)
        .limit(10)
    )

    result = await session.execute(statement)
    rows = result.all()

    return [
        AutocompleteResultResponse(
            id=row[0].id,
            name=row[0].name,
            type="infrastructure",
            detail=row[1] or "",
        )
        for row in rows
    ]
