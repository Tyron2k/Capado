"""Service layer for work packages: CRUD operations and business logic."""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.assignment import Assignment
from app.models.project import Project, WorkPackage
from app.services.partial_update import UNSET, UnsetType


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _validate_work_package_fields(
    name: str | None,
    start_date: date | None,
    end_date: date | None,
) -> None:
    """Validate required fields and business rules for a work package.

    Ensures endDate >= startDate.
    """
    if not name or not name.strip():
        raise BusinessRuleError("The field 'Name' is required.", field="name")
    if start_date is None:
        raise BusinessRuleError(
            "The field 'Start date' is required.", field="start_date"
        )
    if end_date is None:
        raise BusinessRuleError("The field 'End date' is required.", field="end_date")
    if end_date < start_date:
        raise BusinessRuleError(
            "The end date must not be before the start date.",
            field="end_date",
        )


def _check_project_boundaries(
    wp_start_date: date,
    wp_end_date: date,
    project: Project,
) -> list[str]:
    """Check whether the work package falls outside the project time range.

    Issues a warning (not an error) when the work package is outside the project range.

    Returns:
        List of warnings (empty if everything is within bounds).

    """
    warnings: list[str] = []
    if wp_start_date < project.start_date:
        warnings.append(
            f"The work package start date is before the project start date "
            f"({project.start_date.isoformat()})."
        )
    if wp_end_date > project.end_date:
        warnings.append(
            f"The work package end date is after the project end date "
            f"({project.end_date.isoformat()})."
        )
    return warnings


class WorkPackageService:
    """Service for work package CRUD operations."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    async def create(
        self,
        project_id: UUID,
        name: str,
        start_date: date,
        end_date: date,
        lead_time_working_days: int | None = None,
    ) -> tuple[WorkPackage, list[str]]:
        """Create a new work package.

        Returns:
            Tuple of (WorkPackage, list of warnings).

        """
        # Load project and verify it exists
        project = await self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project", project_id)

        # Validation
        _validate_work_package_fields(name, start_date, end_date)

        # Warning on project boundary violation
        warnings = _check_project_boundaries(start_date, end_date, project)

        work_package = WorkPackage(
            project_id=project_id,
            name=name.strip(),
            start_date=start_date,
            end_date=end_date,
            lead_time_working_days=lead_time_working_days,
        )
        self.session.add(work_package)
        await self.session.commit()
        return work_package, warnings

    async def get_by_project(
        self, project_id: UUID, limit: int = 100, offset: int = 0
    ) -> tuple[list[WorkPackage], int]:
        """Return work packages for a project with pagination.

        Args:
            project_id: The UUID of the project.
            limit: Maximum number of items to return.
            offset: Number of items to skip.

        Returns:
            Tuple of (list of work packages, total count).

        Raises:
            NotFoundError: If the project does not exist.

        """
        from sqlmodel import func

        # Verify project exists
        project = await self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project", project_id)

        count_stmt = (
            select(func.count())
            .select_from(WorkPackage)
            .where(WorkPackage.project_id == project_id)
        )
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()

        # Chronological, because a work package is a stretch of time and reading it in insertion
        # order means a package starting in March appears below one starting in June purely because
        # somebody typed it later. end_date and name break ties so two packages that start on the
        # same day keep a fixed order — without a total order, OFFSET/LIMIT could show one row twice
        # across pages and drop another.
        statement = (
            select(WorkPackage)
            .where(WorkPackage.project_id == project_id)
            .order_by(WorkPackage.start_date, WorkPackage.end_date, WorkPackage.name)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all()), total

    async def get_by_id(self, work_package_id: UUID) -> WorkPackage:
        """Return a single work package by ID.

        Raises:
            NotFoundError: If the work package does not exist.

        """
        work_package = await self.session.get(WorkPackage, work_package_id)
        if work_package is None:
            raise NotFoundError("WorkPackage", work_package_id)
        return work_package

    async def update(
        self,
        work_package_id: UUID,
        name: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        lead_time_working_days: int | None = None,
        completed_at: datetime | None | UnsetType = UNSET,
    ) -> tuple[WorkPackage, list[str]]:
        """Update an existing work package (partial update).

        Fields left as ``None`` keep their current value. A date range outside
        the parent project's range is reported as a warning, not an error.

        Returns:
            Tuple of (WorkPackage, list of warnings).

        Raises:
            NotFoundError: If the work package or its parent project is gone.
            BusinessRuleError: If the resulting name is empty or the end date
                precedes the start date.

        """
        work_package = await self.get_by_id(work_package_id)

        # Merge: use new values or keep existing ones
        effective_name = name if name is not None else work_package.name
        effective_start_date = (
            start_date if start_date is not None else work_package.start_date
        )
        effective_end_date = end_date if end_date is not None else work_package.end_date

        # Validate with effective values
        _validate_work_package_fields(
            effective_name, effective_start_date, effective_end_date
        )

        # Load project for boundary check
        project = await self.session.get(Project, work_package.project_id)
        if project is None:
            raise NotFoundError("Project", work_package.project_id)
        warnings = _check_project_boundaries(
            effective_start_date, effective_end_date, project
        )

        # Update fields
        work_package.name = effective_name.strip()
        work_package.start_date = effective_start_date
        work_package.end_date = effective_end_date
        if lead_time_working_days is not None:
            work_package.lead_time_working_days = lead_time_working_days
        # UNSET leaves it alone; an explicit None reopens the package, which has to
        # stay possible — a completion marked by mistake is a normal correction, and
        # the audit log records both the closing and the reopening.
        if not isinstance(completed_at, UnsetType):
            work_package.completed_at = completed_at
        work_package.updated_at = _utcnow()

        self.session.add(work_package)
        await self.session.commit()
        return work_package, warnings

    async def delete(self, work_package_id: UUID) -> None:
        """Delete a work package and all associated assignments (hard delete, cascade)."""
        work_package = await self.get_by_id(work_package_id)

        # Cascade delete assignments
        statement = select(Assignment).where(
            Assignment.work_package_id == work_package_id
        )
        result = await self.session.execute(statement)
        assignments = result.scalars().all()
        for assignment in assignments:
            await self.session.delete(assignment)

        # Delete work package
        await self.session.delete(work_package)
        await self.session.commit()
