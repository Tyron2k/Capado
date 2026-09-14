"""Service for absence CRUD operations."""

from datetime import UTC, date, datetime
from types import EllipsisType
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.absence import Absence, AbsenceReason, AbsenceStatus
from app.models.resource import ResourceType


class AbsenceService:
    """CRUD operations for resource absences."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    async def create(
        self,
        resource_id: UUID,
        resource_type: ResourceType,
        reason: AbsenceReason,
        start_date,
        end_date,
        allocation_percent: float = 100.0,
        status: AbsenceStatus = AbsenceStatus.confirmed,
        note: str | None = None,
    ) -> Absence:
        """Create a new absence.

        Args:
            resource_id: The resource to block.
            resource_type: personal or infrastructure.
            reason: Why the resource is unavailable.
            start_date: First day of absence.
            end_date: Last day of absence (inclusive).
            allocation_percent: How much capacity is blocked (1-100).
            status: Whether the absence is confirmed or still a request. Both reduce
                capacity identically; the status says what is still negotiable.
            note: Optional free-text note.

        Returns:
            The created Absence.

        Raises:
            BusinessRuleError: If end_date < start_date.

        """
        if end_date < start_date:
            raise BusinessRuleError(
                "End date must be equal to or after start date.",
                field="end_date",
            )

        absence = Absence(
            resource_id=resource_id,
            resource_type=resource_type,
            reason=reason,
            start_date=start_date,
            end_date=end_date,
            allocation_percent=allocation_percent,
            status=status,
            note=note,
        )
        self.session.add(absence)
        await self.session.flush()
        return absence

    async def get_by_id(self, absence_id: UUID) -> Absence:
        """Load an absence by ID or raise NotFoundError."""
        absence = await self.session.get(Absence, absence_id)
        if absence is None:
            raise NotFoundError("Absence", absence_id)
        return absence

    async def get_for_resource(
        self, resource_id: UUID, limit: int = 100, offset: int = 0
    ) -> tuple[list[Absence], int]:
        """Return absences for a resource with pagination, ordered by start_date desc.

        Args:
            resource_id: The UUID of the resource.
            limit: Maximum number of items to return.
            offset: Number of items to skip.

        Returns:
            Tuple of (list of absences, total count).

        """
        from sqlmodel import func

        count_stmt = (
            select(func.count())
            .select_from(Absence)
            .where(Absence.resource_id == resource_id)
        )
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()

        stmt = (
            select(Absence)
            .where(Absence.resource_id == resource_id)
            .order_by(Absence.start_date.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update(
        self,
        absence_id: UUID,
        reason: AbsenceReason | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        allocation_percent: float | None = None,
        status: AbsenceStatus | None = None,
        # Ellipsis is a deliberate sentinel: `note` is nullable, so passing None
        # must CLEAR it while omitting the argument leaves it untouched. The
        # annotation has to name the sentinel or a checker reads the default as
        # a type error.
        note: str | None | EllipsisType = ...,
    ) -> Absence:
        """Update an existing absence (partial update).

        Args:
            absence_id: ID of the absence to update.
            reason: New reason (optional).
            start_date: New start date (optional).
            end_date: New end date (optional).
            allocation_percent: New allocation (optional).
            status: New status (optional). Confirming a provisional absence does not change
                the capacity arithmetic — both statuses reduce it identically — only what is
                still negotiable.
            note: New note (pass None to clear, omit to keep).

        Returns:
            The updated Absence.

        """
        absence = await self.get_by_id(absence_id)

        if reason is not None:
            absence.reason = reason
        if start_date is not None:
            absence.start_date = start_date
        if end_date is not None:
            absence.end_date = end_date
        if allocation_percent is not None:
            absence.allocation_percent = allocation_percent
        if status is not None:
            absence.status = status
        if note is not ...:
            absence.note = note

        # Validate dates after update
        if absence.end_date < absence.start_date:
            raise BusinessRuleError(
                "End date must be equal to or after start date.",
                field="end_date",
            )

        absence.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.session.add(absence)
        await self.session.flush()
        return absence

    async def delete(self, absence_id: UUID) -> None:
        """Delete an absence."""
        absence = await self.get_by_id(absence_id)
        await self.session.delete(absence)
        await self.session.flush()
