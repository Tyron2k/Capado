"""Enforce the planning freeze on assignment writes.

One place, called from every assignment write path. Not a decorator and not middleware: the
check needs the assignment's dates BEFORE the change, which only the handler knows how to
load, and hiding that in a decorator would make the "both states count" rule invisible at the
call site — exactly where somebody adding a fifth write path needs to see it.

Personnel bookings carry dates and infrastructure bookings carry datetimes in the same table
(see docs/reference/known-limitations.md). Both are reduced to plain dates here, which is
correct for a freeze: a period is closed by day, never by hour.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.assignment import Assignment
from app.models.organization_settings import OrganizationSettings
from app.models.user import User, UserRole
from app.services.planning_freeze import Span, change_is_blocked, explain_block
from app.services.unmet_requirements_service import assignment_span


def span_of(assignment: Assignment) -> Span:
    """The assignment's span, whichever of the two booking shapes it uses.

    Delegates to :func:`assignment_span`, which already handles the two column sets and was
    written for the bug where reading only one pair made every infrastructure booking
    invisible. A second implementation here would be free to drift from it, and the freeze is
    exactly the place where silently missing a booking shape means silently allowing an edit.

    A row with neither pair populated yields a span with no bounds, which
    :func:`touches_frozen_period` treats as reaching back indefinitely — the conservative
    reading, and the right one for a permission check.
    """
    span = assignment_span(assignment)
    if span is None:
        return Span(start=None, end=None)
    return Span(start=span[0], end=span[1])


async def freeze_date(session: AsyncSession) -> date | None:
    """The configured freeze date, or None when no freeze is set."""
    result = await session.execute(select(OrganizationSettings).limit(1))
    settings = result.scalars().first()
    return settings.planning_freeze_before if settings else None


async def enforce_freeze(
    session: AsyncSession,
    current_user: User,
    before: Span | None,
    after: Span | None,
) -> None:
    """Raise 403 when this change reaches into the frozen period.

    403 rather than 409: the change is well-formed and would be accepted from somebody else,
    which is a permission answer, not a conflict.
    """
    if current_user.role == UserRole.admin:
        return
    freeze = await freeze_date(session)
    if freeze is None:
        return
    if change_is_blocked(before, after, freeze, is_admin=False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=explain_block(freeze)
        )
