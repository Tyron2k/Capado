"""Read access to the maintenance run log.

Admin-only, matching the audit log: the run log says when data was deleted, which is
administrative rather than operational information.

This endpoint is not a convenience. The defect being fixed is that a retention setting existed
and nobody could tell whether it had ever taken effect; a scheduler nobody can inspect would
reproduce that one level up. Being able to answer "when did the last prune run and how many rows
did it remove" is what turns the number in the compliance document from a claim into a fact.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.models.scheduled_job_run import ScheduledJobRun
from app.models.user import User
from app.services.permissions import require_admin

# main.py adds the /api prefix.
router = APIRouter(prefix="/maintenance", tags=["maintenance"])


class JobRunResponse(BaseModel):
    """One recorded run."""

    job_name: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    items_affected: int | None = Field(
        default=None,
        description="Rows the job touched. 0 means nothing was old enough yet; null means "
        "the job did not get far enough to know, which is not the same statement.",
    )
    detail: str

    model_config = {"from_attributes": True}


@router.get(
    "/runs",
    response_model=list[JobRunResponse],
    summary="Recent maintenance runs (admin only)",
)
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> list[JobRunResponse]:
    """The most recent runs, newest first.

    Includes failures and unresolved ``running`` rows. Filtering those out would hide exactly
    the two states an operator needs to see — a job failing nightly, and a job killed mid-run.
    """
    result = await session.execute(
        select(ScheduledJobRun).order_by(ScheduledJobRun.started_at.desc()).limit(limit)
    )
    return [
        JobRunResponse.model_validate(run, from_attributes=True)
        for run in result.scalars().all()
    ]
