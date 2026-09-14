"""Response schemas for the project overview endpoint."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class LateWorkPackage(BaseModel):
    """A work package whose working-day lead time overruns its end date."""

    work_package_id: UUID
    work_package_name: str
    entered_end: date
    derived_end: date
    working_days_short: int


class CommitmentBreachResponse(BaseModel):
    """A committed delivery date the plan does not meet."""

    committed: date
    planned_end: date
    derived_end: date | None = None
    working_days_short: int
    # True when the PLANNED dates meet the commitment and only the recorded lead times
    # do not. The dangerous case: every date-based report looks fine.
    hidden: bool


class DependencyViolationResponse(BaseModel):
    """A successor that starts before its predecessor allows.

    Carries both names, because a warning naming only one side cannot be acted on: the
    reader has to know what is waiting on what before they can decide which date moves.
    """

    predecessor_id: UUID
    predecessor_name: str
    successor_id: UUID
    successor_name: str
    predecessor_end: date
    successor_start: date
    lag_working_days: int
    # The first day the successor may start, given the predecessor's end and the lag.
    earliest_start: date
    # Working days the successor would have to move. The unit someone acts on —
    # calendar days would include days nobody works and overstate the fix.
    working_days_short: int


class ScheduleNodeResponse(BaseModel):
    """Where one work package sits in the schedule."""

    work_package_id: UUID
    work_package_name: str
    earliest_start: date
    earliest_finish: date
    latest_start: date
    latest_finish: date
    # Working days it can slip before the project does. Negative means the deadline is
    # already unreachable through this package.
    float_working_days: int
    is_critical: bool
    # Working days the package occupies, from its lead time when recorded and from its
    # entered span otherwise. Included because the float is only interpretable next to
    # it: five days of float on a two-day task means something different from five on a
    # thirty-day one.
    duration_working_days: int


class ProjectScheduleResponse(BaseModel):
    """Forward and backward pass over one project's work packages."""

    project_id: UUID
    # The date the analysis measured against: the committed delivery date where one
    # exists, otherwise the planned end. Reported so the numbers can be read without
    # guessing what they were compared to.
    deadline: date
    deadline_is_commitment: bool
    nodes: list[ScheduleNodeResponse]


class ProjectOverviewItem(BaseModel):
    """Aggregated KPIs for a single project."""

    project_id: UUID
    project_name: str
    start_date: date
    end_date: date
    progress_percent: float
    active_work_package_count: int
    next_deadline: date
    open_conflict_count: int
    average_resource_utilization_percent: float | None = None
    # Work packages whose recorded lead time in WORKING days cannot fit between
    # their start and their committed end. The project is then late in fact, and
    # someone has to act. The entered dates are never adjusted to make the warning
    # go away (ADR-008).
    late_work_packages: list[LateWorkPackage] = Field(default_factory=list)
    # Present only when a commitment exists and is missed. Absent is not "on time" for
    # a project nobody promised anything about — it is "nothing was promised".
    commitment_breach: CommitmentBreachResponse | None = None
    # Dependencies the entered dates contradict. Reported rather than corrected: the
    # planner decides which side moves, and a system that reschedules on their behalf
    # drives the next change into a spreadsheet.
    dependency_violations: list[DependencyViolationResponse] = Field(
        default_factory=list
    )
    # The smallest float across the project's work packages — how much the project as a
    # whole can slip. None when there is nothing to analyse. Negative means the deadline
    # is already unreachable.
    min_float_working_days: int | None = None
    critical_work_package_count: int = 0

    @property
    def is_late(self) -> bool:
        """Whether any work package overruns its commitment."""
        return bool(self.late_work_packages)


class ProjectOverviewResponse(BaseModel):
    """Response containing aggregated project overview items."""

    projects: list[ProjectOverviewItem]
