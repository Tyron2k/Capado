"""Baselines router: freeze the plan and read the drift against it.

    GET    /api/baselines              List baselines, newest first
    GET    /api/baselines/current      The baseline drift is shown against
    POST   /api/baselines              Freeze the current plan
    GET    /api/baselines/{id}/diff    Drift of the live plan against a baseline
    DELETE /api/baselines/{id}         Delete a baseline and its entries

Reads require authentication; writes require admin. Freezing a plan is an
organisation-wide statement about what was agreed, not a per-group edit.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.services.baseline_service import BaselineDiff, BaselineService, EntityDiff
from app.services.permissions import get_current_user, require_admin

router = APIRouter(tags=["Baselines"])


class BaselineCreate(BaseModel):
    """Request body for freezing the current plan."""

    name: str = Field(min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=1000)
    make_current: bool = True


class BaselineResponse(BaseModel):
    """Response schema for a baseline header."""

    id: UUID
    name: str
    note: str | None
    created_by: UUID | None
    is_current: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class BaselineCreatedResponse(BaselineResponse):
    """A freshly created baseline, with how much it captured."""

    entry_count: int


class EntityDiffResponse(BaseModel):
    """How one entity differs between the baseline and the live plan."""

    entity_type: str
    entity_id: UUID
    changes: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BaselineDiffResponse(BaseModel):
    """Drift of the live plan against one baseline.

    ``added`` and ``removed`` are not error states: work created after the freeze
    is genuinely new, and work deleted is work that went away.
    """

    baseline_id: UUID
    has_drift: bool
    added: list[EntityDiffResponse]
    removed: list[EntityDiffResponse]
    changed: list[EntityDiffResponse]


def _entity(diff: EntityDiff) -> EntityDiffResponse:
    return EntityDiffResponse(
        entity_type=diff.entity_type,
        entity_id=diff.entity_id,
        changes=diff.changes,
    )


def _diff_response(baseline_id: UUID, diff: BaselineDiff) -> BaselineDiffResponse:
    return BaselineDiffResponse(
        baseline_id=baseline_id,
        has_drift=diff.has_drift,
        added=[_entity(d) for d in diff.added],
        removed=[_entity(d) for d in diff.removed],
        changed=[_entity(d) for d in diff.changed],
    )


@router.get("/baselines", response_model=list[BaselineResponse])
async def list_baselines(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[BaselineResponse]:
    """List baselines, newest first."""
    baselines = await BaselineService(session).list_baselines()
    return [BaselineResponse.model_validate(b) for b in baselines]


@router.get("/baselines/current", response_model=BaselineResponse | None)
async def current_baseline(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> BaselineResponse | None:
    """The baseline drift is shown against, or null if none is marked."""
    baseline = await BaselineService(session).current_baseline()
    return BaselineResponse.model_validate(baseline) if baseline else None


@router.post(
    "/baselines",
    response_model=BaselineCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_baseline(
    body: BaselineCreate,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> BaselineCreatedResponse:
    """Freeze the current plan.

    Does not lock anything: the schedule stays editable, and the diff is what
    makes a later deviation visible (ADR-007).
    """
    baseline, entry_count = await BaselineService(session).create_baseline(
        name=body.name,
        note=body.note,
        created_by=admin.id,
        make_current=body.make_current,
    )
    return BaselineCreatedResponse(
        **BaselineResponse.model_validate(baseline).model_dump(),
        entry_count=entry_count,
    )


@router.get("/baselines/{baseline_id}/diff", response_model=BaselineDiffResponse)
async def baseline_diff(
    baseline_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> BaselineDiffResponse:
    """Drift of the live plan against a baseline."""
    diff = await BaselineService(session).diff(baseline_id)
    return _diff_response(baseline_id, diff)


@router.delete("/baselines/{baseline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_baseline(
    baseline_id: UUID,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Delete a baseline and its entries."""
    await BaselineService(session).delete_baseline(baseline_id)
