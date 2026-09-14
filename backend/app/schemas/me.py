"""Response shape for the signed-in person's own view of themselves.

One response rather than three endpoints, because the three pieces are read together: a person
checking their week wants the assignments, the absences that reduce them, and the qualifications the
assignments were matched against. Three round trips would render the same screen more slowly and let
the parts arrive out of step with each other.

The totals are carried alongside the lists because both are capped: a caller has to be able to tell
"this is everything" from "this is the first 200".
"""

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.absence import AbsenceResponse
from app.schemas.assignment import AssignmentResponse
from app.schemas.skill import ResourceSkillAssignmentResponse


class MyPlanResponse(BaseModel):
    """Everything the signed-in person may read about their own scheduling."""

    resource_id: UUID = Field(
        description="The scheduled person this account is linked to"
    )
    assignments: list[AssignmentResponse] = Field(
        description="The caller's own assignments, newest window first"
    )
    assignment_total: int = Field(
        description="Total assignments, which may exceed the returned page"
    )
    absences: list[AbsenceResponse] = Field(
        description="The caller's own absences, most recent start first"
    )
    absence_total: int = Field(
        description="Total absences, which may exceed the returned page"
    )
    skills: list[ResourceSkillAssignmentResponse] = Field(
        description="The caller's own qualifications, with level and validity window"
    )
