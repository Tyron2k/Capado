"""Download endpoints for the Excel reports.

Streamed as a file response with a Content-Disposition filename, so a browser saves it under a name
that says what it is and sorts by date. Without the header the browser names the file after the
route, and a folder of files called ``utilization`` is a folder nobody can navigate.

Read-only and open to any authenticated user, matching the screens the reports mirror: somebody who
can see the utilization chart can export it. Restricting the export while leaving the chart visible
would only mean the numbers get retyped by hand, which is worse.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.services.permissions import get_current_user
from app.services.reports.projects import build_project_report
from app.services.reports.utilization import build_utilization_report
from app.services.reports.workbook import filename_for

# main.py adds the /api prefix.
router = APIRouter(prefix="/reports", tags=["reports"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Cap on the reported span. 104 weeks of a few hundred people is tens of thousands of rows on the pivot sheet, which Excel
# handles fine; the limit exists because the utilization is computed per person per week and an
# open-ended range would let one request run for minutes.
_MAX_WEEKS = 104


def _xlsx_response(content: bytes, filename: str) -> Response:
    """An .xlsx download with a filename the browser will actually use."""
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/utilization", summary="Utilization report as Excel")
async def utilization_report(
    start: date | None = Query(
        default=None, description="First week. Defaults to the current week."
    ),
    end: date | None = Query(
        default=None, description="Last week. Defaults to 12 weeks after start."
    ),
    group_id: UUID | None = Query(
        default=None, description="Restrict to one resource group. Omitted: everybody."
    ),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Weekly utilization, wide for reading and long for pivoting."""
    today = datetime.now(UTC).date()
    first = start or today
    # Twelve weeks rather than a year: a default that produces a 50-column sheet trains people to
    # always pass parameters, and the parameters are right there.
    last = end or (first + timedelta(weeks=12))
    if last < first:
        first, last = last, first
    span_weeks = ((last - first).days // 7) + 1
    if span_weeks > _MAX_WEEKS:
        last = first + timedelta(weeks=_MAX_WEEKS - 1)
    content = await build_utilization_report(session, first, last, group_id)
    return _xlsx_response(content, filename_for("auslastung", today))


@router.get("/projects", summary="Project status report as Excel")
async def project_report(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Project status with commitment breaches and dependency violations.

    No date range: the question a status report answers is "where does everything stand", and
    filtering it by date would hide exactly the overdue project somebody is looking for.
    """
    content = await build_project_report(session)
    return _xlsx_response(content, filename_for("projekte", datetime.now(UTC).date()))
