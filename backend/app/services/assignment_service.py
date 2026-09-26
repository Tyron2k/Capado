"""Service layer for assignments: CRUD plus conflict-detection trigger.

Assignments come in two shapes that share one table:

* Personal (``resource_type=personal``): ``start_date`` / ``end_date`` /
  ``allocation_percent``. Conflict detection sums ``allocation_percent``; a conflict
  occurs when the total exceeds 100%.
* Infrastructure (``resource_type=infrastructure``): ``start_at`` /
  ``end_at`` timestamps with minute precision. Conflict detection flags
  any pair of assignments on the same resource whose intervals overlap.

The service refuses mixed payloads — if you pass ``resource_type=personal``
you must use the date+hours fields, never ``start_at``/``end_at``.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.assignment import Assignment
from app.models.project import WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.services.capacity_service import CapacityService
from app.services.time_zone import local_day_bounds, planning_zone


def _utcnow() -> datetime:
    """Return current timezone-aware UTC time."""
    return datetime.now(UTC)


def _validate_personal_fields(
    start_date: date | None,
    end_date: date | None,
    allocation_percent: float | None,
    start_at: datetime | None,
    end_at: datetime | None,
) -> None:
    """Validate that personal assignment fields are consistent."""
    if start_at is not None or end_at is not None:
        raise BusinessRuleError(
            "For personal assignments, 'start_at' and 'end_at' must not be set.",
            field="start_at",
        )
    if start_date is None:
        raise BusinessRuleError(
            "The field 'Start date' is required.", field="start_date"
        )
    if end_date is None:
        raise BusinessRuleError("The field 'End date' is required.", field="end_date")
    if allocation_percent is None:
        raise BusinessRuleError(
            "The field 'Allocation percent' is required.", field="allocation_percent"
        )
    if allocation_percent <= 0:
        raise BusinessRuleError(
            "Allocation percent must be greater than 0.", field="allocation_percent"
        )
    if end_date < start_date:
        raise BusinessRuleError(
            "The end date must not be before the start date.",
            field="end_date",
        )


def _validate_infrastructure_fields(
    start_date: date | None,
    end_date: date | None,
    allocation_percent: float | None,
    start_at: datetime | None,
    end_at: datetime | None,
) -> None:
    """Validate that infrastructure assignment fields are consistent."""
    if start_date is not None or end_date is not None or allocation_percent is not None:
        raise BusinessRuleError(
            "For infrastructure assignments, 'start_date', 'end_date' and "
            "'allocation_percent' must not be set.",
            field="start_date",
        )
    if start_at is None:
        raise BusinessRuleError("The field 'Start time' is required.", field="start_at")
    if end_at is None:
        raise BusinessRuleError("The field 'End time' is required.", field="end_at")
    if end_at <= start_at:
        raise BusinessRuleError(
            "The end time must be after the start time.", field="end_at"
        )


def _validate_required_fields(
    resource_id: UUID | None,
    resource_type: ResourceType | None,
    work_package_id: UUID | None,
) -> None:
    """Validate that mandatory assignment fields are provided."""
    if resource_id is None:
        raise BusinessRuleError(
            "The field 'Resource' is required.", field="resource_id"
        )
    if resource_type is None:
        raise BusinessRuleError(
            "The field 'Resource type' is required.", field="resource_type"
        )
    if work_package_id is None:
        raise BusinessRuleError(
            "The field 'Work package' is required.", field="work_package_id"
        )


def _validate_assignment_fields(
    resource_id: UUID | None,
    resource_type: ResourceType | None,
    work_package_id: UUID | None,
    start_date: date | None,
    end_date: date | None,
    allocation_percent: float | None,
    start_at: datetime | None,
    end_at: datetime | None,
) -> None:
    """Validate all assignment fields based on resource type."""
    _validate_required_fields(resource_id, resource_type, work_package_id)
    if resource_type == ResourceType.personal:
        _validate_personal_fields(
            start_date, end_date, allocation_percent, start_at, end_at
        )
    else:
        _validate_infrastructure_fields(
            start_date, end_date, allocation_percent, start_at, end_at
        )


class AssignmentService:
    """Service for assignment CRUD operations."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session and capacity service."""
        self.session = session
        self.capacity_service = CapacityService(session)

    async def _check_resource_exists(
        self, resource_id: UUID, resource_type: ResourceType
    ) -> None:
        if resource_type == ResourceType.personal:
            resource = await self.session.get(PersonalResource, resource_id)
            if resource is None:
                raise NotFoundError("PersonalResource", resource_id)
        else:
            resource = await self.session.get(InfrastructureResource, resource_id)
            if resource is None:
                raise NotFoundError("InfrastructureResource", resource_id)

    async def _check_work_package_exists(self, work_package_id: UUID) -> None:
        """Verify the work package exists or raise NotFoundError."""
        wp = await self.session.get(WorkPackage, work_package_id)
        if wp is None:
            raise NotFoundError("WorkPackage", work_package_id)

    async def _check_personal_capacity_exceeded(
        self,
        resource_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[str]:
        """Warn (do not block) when a personal assignment pushes utilisation > 100%."""
        warnings: list[str] = []
        utilization_data = await self.capacity_service.calculate_utilization(
            resource_id, start_date, end_date
        )
        exceeded_days = [day for day in utilization_data if day.utilization > 100]
        if exceeded_days:
            first = exceeded_days[0].date.isoformat()
            last = exceeded_days[-1].date.isoformat()
            max_util = max(d.utilization for d in exceeded_days)
            if len(exceeded_days) == 1:
                warnings.append(
                    f"capacity_exceeded|days=1|from={first}|to={first}"
                    f"|max_util={max_util:.0f}"
                )
            else:
                warnings.append(
                    f"capacity_exceeded|days={len(exceeded_days)}|from={first}|to={last}"
                    f"|max_util={max_util:.0f}"
                )
        return warnings

    async def _trigger_conflict_detection(self, resource_id: UUID) -> None:
        """Trigger conflict detection refresh for a resource."""
        # Local import to avoid circular dependency.
        from app.services.conflict_refresh import refresh_resources

        await refresh_resources(self.session, [resource_id])

    async def create(
        self,
        resource_id: UUID,
        resource_type: ResourceType,
        work_package_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        allocation_percent: float | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> tuple[Assignment, list[str]]:
        """Create a new assignment. Returns the assignment plus soft warnings."""
        _validate_assignment_fields(
            resource_id,
            resource_type,
            work_package_id,
            start_date,
            end_date,
            allocation_percent,
            start_at,
            end_at,
        )

        await self._check_resource_exists(resource_id, resource_type)
        await self._check_work_package_exists(work_package_id)

        # Prevent duplicate: same resource + same work package
        existing_stmt = select(Assignment).where(
            Assignment.resource_id == resource_id,
            Assignment.work_package_id == work_package_id,
        )
        existing_result = await self.session.execute(existing_stmt)
        if existing_result.scalars().first() is not None:
            raise ConflictError(
                "This resource is already assigned to this work package."
            )

        assignment = Assignment(
            resource_id=resource_id,
            resource_type=resource_type,
            work_package_id=work_package_id,
            start_date=start_date,
            end_date=end_date,
            allocation_percent=allocation_percent,
            start_at=start_at,
            end_at=end_at,
        )
        self.session.add(assignment)
        await self.session.commit()

        warnings: list[str] = []
        if resource_type == ResourceType.personal and start_date and end_date:
            warnings = await self._check_personal_capacity_exceeded(
                resource_id, start_date, end_date
            )

        await self._trigger_conflict_detection(resource_id)
        return assignment, warnings

    async def get_all(
        self,
        resource_id: UUID | None = None,
        work_package_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Assignment], int]:
        """List assignments with pagination, optionally filtered.

        Date filters are pushed into SQL WHERE clauses for both personal
        (start_date/end_date) and infrastructure (start_at/end_at) shapes,
        avoiding loading the entire table into memory.

        Args:
            resource_id: Optional filter by resource UUID.
            work_package_id: Optional filter by work package UUID.
            start_date: Optional filter for assignments active from this date.
            end_date: Optional filter for assignments active until this date.
            limit: Maximum number of items to return.
            offset: Number of items to skip.

        Returns:
            Tuple of (paginated list of assignments, total count).

        """
        from sqlalchemy import func, or_

        statement = select(Assignment)

        if resource_id is not None:
            statement = statement.where(Assignment.resource_id == resource_id)
        if work_package_id is not None:
            statement = statement.where(Assignment.work_package_id == work_package_id)

        # Push date filters into SQL for both assignment shapes
        if start_date is not None:
            day_start, _ = local_day_bounds(start_date, planning_zone())
            statement = statement.where(
                or_(
                    # Personal shape: end_date >= filter start
                    Assignment.end_date >= start_date,
                    # Infrastructure shape: interval reaches this local day
                    Assignment.end_at > day_start,
                )
            )
        if end_date is not None:
            _, next_day = local_day_bounds(end_date, planning_zone())
            statement = statement.where(
                or_(
                    # Personal shape: start_date <= filter end
                    Assignment.start_date <= end_date,
                    # Infrastructure shape: interval starts before next local day
                    Assignment.start_at < next_day,
                )
            )

        # Count total matching rows
        count_stmt = select(func.count()).select_from(statement.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Apply pagination in SQL
        paginated = (
            statement.order_by(Assignment.created_at.desc()).offset(offset).limit(limit)
        )
        result = await self.session.execute(paginated)
        return list(result.scalars().all()), total

    async def get_by_id(self, assignment_id: UUID) -> Assignment:
        """Return a single assignment by ID.

        Raises:
            NotFoundError: If the assignment does not exist.

        """
        assignment = await self.session.get(Assignment, assignment_id)
        if assignment is None:
            raise NotFoundError("Assignment", assignment_id)
        return assignment

    async def update(
        self,
        assignment_id: UUID,
        resource_id: UUID | None = None,
        resource_type: ResourceType | None = None,
        work_package_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        allocation_percent: float | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> tuple[Assignment, list[str]]:
        """Update an existing assignment with partial fields.

        Returns:
            Tuple of (updated assignment, list of capacity warnings).

        """
        assignment = await self.get_by_id(assignment_id)

        effective_resource_id = (
            resource_id if resource_id is not None else assignment.resource_id
        )
        effective_resource_type = (
            resource_type if resource_type is not None else assignment.resource_type
        )
        effective_work_package_id = (
            work_package_id
            if work_package_id is not None
            else assignment.work_package_id
        )
        effective_start_date = (
            start_date if start_date is not None else assignment.start_date
        )
        effective_end_date = end_date if end_date is not None else assignment.end_date
        effective_allocation_percent = (
            allocation_percent
            if allocation_percent is not None
            else assignment.allocation_percent
        )
        effective_start_at = start_at if start_at is not None else assignment.start_at
        effective_end_at = end_at if end_at is not None else assignment.end_at

        # When the resource type changes, drop the fields of the previous shape
        # so validation only sees the new shape's payload.
        if resource_type is not None and resource_type != assignment.resource_type:
            if resource_type == ResourceType.personal:
                effective_start_at = None
                effective_end_at = None
            else:
                effective_start_date = None
                effective_end_date = None
                effective_allocation_percent = None

        _validate_assignment_fields(
            effective_resource_id,
            effective_resource_type,
            effective_work_package_id,
            effective_start_date,
            effective_end_date,
            effective_allocation_percent,
            effective_start_at,
            effective_end_at,
        )

        if resource_id is not None or resource_type is not None:
            await self._check_resource_exists(
                effective_resource_id, effective_resource_type
            )
        if work_package_id is not None:
            await self._check_work_package_exists(effective_work_package_id)

        if (
            effective_resource_id != assignment.resource_id
            or effective_work_package_id != assignment.work_package_id
        ):
            duplicate_result = await self.session.execute(
                select(Assignment).where(
                    Assignment.resource_id == effective_resource_id,
                    Assignment.work_package_id == effective_work_package_id,
                    Assignment.id != assignment_id,
                )
            )
            if duplicate_result.scalars().first() is not None:
                raise ConflictError(
                    "This resource is already assigned to this work package."
                )

        previous_resource_id = assignment.resource_id

        assignment.resource_id = effective_resource_id
        assignment.resource_type = effective_resource_type
        assignment.work_package_id = effective_work_package_id
        assignment.start_date = effective_start_date
        assignment.end_date = effective_end_date
        assignment.allocation_percent = effective_allocation_percent
        assignment.start_at = effective_start_at
        assignment.end_at = effective_end_at
        assignment.updated_at = _utcnow()

        self.session.add(assignment)
        await self.session.commit()

        warnings: list[str] = []
        if (
            effective_resource_type == ResourceType.personal
            and effective_start_date
            and effective_end_date
        ):
            warnings = await self._check_personal_capacity_exceeded(
                effective_resource_id,
                effective_start_date,
                effective_end_date,
            )

        await self._trigger_conflict_detection(effective_resource_id)
        if previous_resource_id != effective_resource_id:
            await self._trigger_conflict_detection(previous_resource_id)

        return assignment, warnings

    async def delete(self, assignment_id: UUID) -> None:
        """Delete an assignment and refresh conflicts for the affected resource.

        Removes related conflicts and their junction entries first to avoid
        FK violations, then deletes the assignment itself. The subsequent
        conflict refresh will recreate any conflicts that still apply.
        """
        from sqlalchemy import delete as sa_delete

        from app.models.conflict import Conflict, ConflictAssignment

        assignment = await self.get_by_id(assignment_id)
        resource_id = assignment.resource_id

        # Find all conflicts that reference this assignment
        ca_stmt = select(ConflictAssignment.conflict_id).where(
            ConflictAssignment.assignment_id == assignment_id
        )
        ca_result = await self.session.execute(ca_stmt)
        conflict_ids = [row[0] for row in ca_result.all()]

        if conflict_ids:
            # Delete ALL conflict_assignment links for these conflicts
            await self.session.execute(
                sa_delete(ConflictAssignment).where(
                    ConflictAssignment.conflict_id.in_(conflict_ids)
                )
            )
            # Delete the conflict records themselves
            await self.session.execute(
                sa_delete(Conflict).where(Conflict.id.in_(conflict_ids))
            )
            await self.session.flush()

        await self.session.delete(assignment)
        await self.session.commit()
        await self._trigger_conflict_detection(resource_id)
