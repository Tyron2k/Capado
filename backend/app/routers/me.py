"""What the signed-in person may read about themselves.

WHY THIS EXISTS

Everything Capado knows about a scheduled person was visible to their leaders and to administrators,
and not to that person. "What am I scheduled for next week" meant asking a supervisor, and answering a
GDPR Art. 15 request meant an export by hand. The compliance document promises the benefit is not
one-sided (section 8); this is the endpoint that makes that true rather than aspirational.

WHAT IT IS NOT

Not a second implementation of anything. It composes the three existing services — assignments,
absences and skill assignments — with the resource id taken from the CALLER'S OWN account rather than
from a path parameter. That is the whole security model of this router, and it is why there is no
``/me/plan/{resource_id}``: a route that accepts an id is a route that has to authorise it.

It is also deliberately read-only. Requesting leave, confirming an assignment or correcting an
absence are workflows with their own consequences (and, for leave, their own co-determination
question); none of them are here.

THE BOUNDARY, restated where it will be read while extending this: ADR-009 and section 2 of the
compliance document rule out actual time recording, performance measurement and any analysis of
sign-in behaviour. This router reads plan values. It must not grow a "did you do it" field.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.me import MyPlanResponse
from app.services.absence_service import AbsenceService
from app.services.assignment_service import AssignmentService
from app.services.permissions import get_current_user
from app.services.skill_service import SkillService

router = APIRouter(prefix="/me", tags=["me"])

# A person's own plan is read a screen at a time, not exported. The cap is generous enough that
# nobody hits it in practice and low enough that the endpoint cannot be used to pull the whole table.
_MAX_ITEMS = 200


@router.get(
    "/plan",
    response_model=MyPlanResponse,
    summary="The signed-in person's own plan, absences and qualifications",
    responses={
        409: {
            "description": (
                "The account is not linked to a scheduled person, so there is no plan to show"
            )
        },
    },
)
async def get_my_plan(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MyPlanResponse:
    """Return the caller's own assignments, absences and skill assignments.

    The resource is taken from ``current_user.resource_id`` and never from the request, so this
    endpoint cannot be pointed at somebody else.

    A 409 rather than an empty result when the account has no link: an empty plan and "nobody told
    this system who you are" are different answers, and returning the first for the second would have
    people conclude they are scheduled for nothing.

    Args:
        current_user: The authenticated caller.
        session: Database session.

    Returns:
        The caller's own plan.

    Raises:
        HTTPException: 409 if the account is not linked to a personal resource.

    """
    if current_user.resource_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This account is not linked to a scheduled person. "
                "An administrator links the two on the user record."
            ),
            headers={"X-Error-Code": "no_linked_resource"},
        )

    resource_id = current_user.resource_id

    assignments, assignment_total = await AssignmentService(session).get_all(
        resource_id=resource_id, limit=_MAX_ITEMS
    )
    absences, absence_total = await AbsenceService(session).get_for_resource(
        resource_id, limit=_MAX_ITEMS
    )
    skills = await SkillService(session).get_personal_resource_skills(resource_id)

    return MyPlanResponse(
        resource_id=resource_id,
        assignments=assignments,
        assignment_total=assignment_total,
        absences=absences,
        absence_total=absence_total,
        skills=skills,
    )
