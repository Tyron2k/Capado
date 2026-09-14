"""The digest endpoint: everything needing attention, in one ordered list.

Read-only and open to any authenticated user. Deliberately not restricted to planners: the
findings are about the plan, not about people's behaviour, and a foreman who can see that a
certificate lapses next week is a foreman who can do something about it. The one thing it
exposes that a normal read does not is a person's name next to an expiring qualification,
which is already visible on that person's resource page.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.services.digest import summarise
from app.services.digest_service import build_digest
from app.services.permissions import get_current_user

# main.py adds the /api prefix; including it here would double it.
router = APIRouter(prefix="/digest", tags=["digest"])


class FindingResponse(BaseModel):
    """One finding as sent to the client.

    ``params`` rather than a rendered sentence: ``kind`` says which sentence, the client
    owns the wording. This replaced a ``title``/``detail`` pair that the backend composed
    as German prose — which made the English UI show German sentences under English
    headings, and could not be fixed on the client at all.
    """

    kind: str
    severity: str
    params: dict[str, str] = Field(
        description="Substitution values for the sentence selected by 'kind'. Dates are "
        "ISO so the client can format them for its own locale."
    )
    due: date
    resource_id: UUID | None = None
    work_package_id: UUID | None = None
    project_id: UUID | None = None


class DigestResponse(BaseModel):
    """The digest, with the counts a header needs before the detail."""

    generated_for: date = Field(
        description="The date the digest was computed against. Severity and horizon are "
        "relative to this day, so a client showing a cached digest can say how old it is."
    )
    counts: dict[str, int]
    findings: list[FindingResponse]
    suppressed_count: int = Field(
        description="Findings that exceeded the configured cap and are NOT in the list. "
        "Reported rather than dropped silently: a truncated digest that looks complete is "
        "worse than one that says it is truncated."
    )


@router.get("", response_model=DigestResponse, summary="Everything needing attention")
async def get_digest(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DigestResponse:
    """Compute the digest for today.

    Computed on request rather than stored. A stored digest would need invalidating on every
    plan edit, and a stale digest is worse than a slow one — somebody acting on a finding
    that was already resolved wastes exactly the attention this feature is trying to save.
    """
    today = datetime.now(UTC).date()
    builder = await build_digest(session, today)
    findings = builder.result()
    return DigestResponse(
        generated_for=today,
        counts=summarise(findings),
        findings=[
            FindingResponse(
                kind=f.kind.value,
                severity=f.severity.value,
                params=f.params,
                due=f.due,
                resource_id=f.resource_id,
                work_package_id=f.work_package_id,
                project_id=f.project_id,
            )
            for f in findings
        ],
        suppressed_count=builder.suppressed_count,
    )
