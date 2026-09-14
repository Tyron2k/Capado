"""Autocomplete router: GET /api/autocomplete for typeahead suggestions."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.exceptions import BusinessRuleError
from app.models.user import User
from app.schemas.autocomplete import AutocompleteResultResponse
from app.services import autocomplete_service
from app.services.permissions import get_current_user

router = APIRouter()

_VALID_TYPES = {"personal", "infrastructure"}


@router.get(
    "/autocomplete",
    response_model=list[AutocompleteResultResponse],
    summary="Autocomplete search for resources",
)
async def autocomplete(
    q: str | None = Query(None),
    type: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> list[AutocompleteResultResponse]:
    """Search active resources by name (case-insensitive substring).

    Returns max 10 results, sorted alphabetically.

    Query parameters:
    - q: Search text (1–100 characters, required)
    - type: Resource type ('personal' or 'infrastructure', required)
    """
    # Validation: q must not be missing or empty
    if not q or not q.strip():
        raise BusinessRuleError(
            message="The search text must not be empty.",
            field="q",
        )

    # Validation: q max 100 characters
    if len(q) > 100:
        raise BusinessRuleError(
            message="The search text must not exceed 100 characters.",
            field="q",
        )

    # Validation: type must be 'personal' or 'infrastructure'
    if not type or type not in _VALID_TYPES:
        raise BusinessRuleError(
            message="The parameter 'type' must be 'personal' or 'infrastructure'.",
            field="type",
        )

    return await autocomplete_service.search_resources(
        session=session,
        q=q.strip(),
        type=type,
    )
