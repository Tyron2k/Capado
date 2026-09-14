"""The team week endpoint: one group's week as a grid, for printing and posting.

Scoped like every other group-bound read: an editor limited to their own groups sees their own
team. Not admin-only — the whole point is that a foreman can produce this sheet without asking
anyone.

Nothing here is per-person self-service. The sheet is addressed to whoever runs the team, which is
the decision recorded for this project: individual logins were struck deliberately, and a sheet
for a group is the replacement rather than a stopgap.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.services.permissions import get_current_user
from app.services.team_week_service import build_team_week, group_name

# main.py adds the /api prefix.
router = APIRouter(prefix="/team-week", tags=["team-week"])


class DayEntryResponse(BaseModel):
    """One thing a person does on one day."""

    work_package_name: str
    project_name: str
    allocation_percent: float


class DayCellResponse(BaseModel):
    """One person on one day."""

    day: date
    entries: list[DayEntryResponse]
    absence_percent: float
    provisional_percent: float = Field(
        description="How much of the absence is still only requested — the part a foreman "
        "could renegotiate. Both provisional and confirmed absence reduce capacity."
    )
    is_working_day: bool = Field(
        description="False for a weekend or works holiday. Sent explicitly because a blank "
        "cell would otherwise be indistinguishable from 'nothing planned'."
    )
    is_overbooked: bool


class PersonRowResponse(BaseModel):
    """One person's week."""

    resource_id: UUID
    name: str
    cells: list[DayCellResponse]
    has_anything: bool = Field(
        description="False for somebody with nothing planned all week. The row is still "
        "returned — that is information a foreman needs, not a row to drop."
    )


class TeamWeekResponse(BaseModel):
    """The sheet."""

    group_id: UUID
    group_name: str
    days: list[date]
    rows: list[PersonRowResponse]


@router.get(
    "/{group_id}",
    response_model=TeamWeekResponse,
    summary="One team's week as a printable grid",
)
async def get_team_week(
    group_id: UUID,
    week_of: date | None = Query(
        default=None,
        description="Any date in the wanted week. Defaults to today. The ISO week containing "
        "it is returned, Monday to Sunday — a Sunday looks BACK to Monday rather than "
        "forward, so opening the sheet on Sunday shows the week that is ending.",
    ),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TeamWeekResponse:
    """Return the grid for one resource group."""
    anchor = week_of or datetime.now(UTC).date()
    days, rows = await build_team_week(session, group_id, anchor)
    return TeamWeekResponse(
        group_id=group_id,
        group_name=await group_name(session, group_id),
        days=days,
        rows=[
            PersonRowResponse(
                resource_id=row.resource_id,
                name=row.name,
                has_anything=row.has_anything,
                cells=[
                    DayCellResponse(
                        day=cell.day,
                        entries=[
                            DayEntryResponse(
                                work_package_name=entry.work_package_name,
                                project_name=entry.project_name,
                                allocation_percent=entry.allocation_percent,
                            )
                            for entry in cell.entries
                        ],
                        absence_percent=cell.absence_percent,
                        provisional_percent=cell.provisional_percent,
                        is_working_day=cell.is_working_day,
                        is_overbooked=cell.is_overbooked,
                    )
                    for cell in row.cells
                ],
            )
            for row in rows
        ],
    )
