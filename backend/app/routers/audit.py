"""Audit router: read the change trail.

    GET /api/audit                     Filtered, newest first
    GET /api/audit/{type}/{id}         History of one entity

**Admin only, and that is not a convenience.** The trail names people and records
what each of them changed, which makes it a record of individual conduct. In a
German plant that is co-determination relevant under § 87 Abs. 1 Nr. 6 BetrVG, in
the same way per-person utilisation is. Widening this surface to editors — or
adding an "activity by user" view — is a decision for the works council, not a
feature toggle.

Filters exist so the answer to "who moved this assignment" is one request rather
than a scan the caller filters client-side, which would hand out the whole trail to
answer a narrow question.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.models.audit import AuditAction, AuditLog
from app.models.user import User
from app.services.permissions import require_admin

router = APIRouter(tags=["Audit"])

# A page bound the caller cannot raise. Without it a single request can pull the
# entire trail, which is both a performance problem and the widest possible
# disclosure of individual conduct.
MAX_PAGE_SIZE = 200


class AuditEntryResponse(BaseModel):
    """One recorded change."""

    id: UUID
    entity_type: str
    entity_id: UUID
    action: AuditAction
    actor_id: UUID | None
    reason: str | None
    changes: dict[str, Any]
    recorded_at: datetime

    model_config = {"from_attributes": True}


def _apply_filters(
    statement: Any,
    entity_type: str | None,
    entity_id: UUID | None,
    actor_id: UUID | None,
    action: AuditAction | None,
    recorded_from: datetime | None,
    recorded_to: datetime | None,
) -> Any:
    """Narrow an audit query by the supplied filters.

    Kept separate from the handler so the filter set is one thing to read and one
    thing to extend, rather than a wall of conditionals inside the route.
    """
    if entity_type is not None:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        statement = statement.where(AuditLog.entity_id == entity_id)
    if actor_id is not None:
        statement = statement.where(AuditLog.actor_id == actor_id)
    if action is not None:
        statement = statement.where(AuditLog.action == action)
    if recorded_from is not None:
        statement = statement.where(AuditLog.recorded_at >= recorded_from)
    if recorded_to is not None:
        statement = statement.where(AuditLog.recorded_at <= recorded_to)
    return statement


@router.get("/audit", response_model=list[AuditEntryResponse])
async def list_audit_entries(
    entity_type: str | None = Query(default=None),
    entity_id: UUID | None = Query(default=None),
    actor_id: UUID | None = Query(default=None),
    action: AuditAction | None = Query(default=None),
    recorded_from: datetime | None = Query(default=None, alias="from"),
    recorded_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> list[AuditEntryResponse]:
    """List recorded changes, newest first."""
    statement = _apply_filters(
        select(AuditLog),
        entity_type,
        entity_id,
        actor_id,
        action,
        recorded_from,
        recorded_to,
    )
    statement = (
        statement.order_by(AuditLog.recorded_at.desc()).offset(offset).limit(limit)
    )
    result = await session.execute(statement)
    return [
        AuditEntryResponse.model_validate(entry) for entry in result.scalars().all()
    ]


@router.get("/audit/{entity_type}/{entity_id}", response_model=list[AuditEntryResponse])
async def entity_history(
    entity_type: str,
    entity_id: UUID,
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> list[AuditEntryResponse]:
    """History of one entity, newest first.

    Served by the composite index on (entity_type, entity_id, recorded_at), which
    is also what a later "last changed by" lookup would use instead of
    denormalised columns on every table (ADR-006).
    """
    statement = (
        select(AuditLog)
        .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
        .order_by(AuditLog.recorded_at.desc())
        .limit(limit)
    )
    result = await session.execute(statement)
    return [
        AuditEntryResponse.model_validate(entry) for entry in result.scalars().all()
    ]
