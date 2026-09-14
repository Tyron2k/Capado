"""Service layer for projects: CRUD operations and business logic."""

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.project import Project, ProjectFolder, ProjectPriority
from app.services.partial_update import UNSET, UnsetType


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean_ref(value: str | None) -> str | None:
    """Normalise an external reference.

    Whitespace-only becomes None rather than an empty string, so "no reference" has
    exactly one representation and a lookup cannot miss a row because someone typed
    a space.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validate_project_fields(
    name: str | None,
    start_date: date | None,
    end_date: date | None,
) -> None:
    """Validate required fields and business rules for a project.

    Ensures endDate >= startDate and all required fields are present.
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


class ProjectService:
    """Service for project CRUD operations."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    async def _validate_folder(self, folder_id: UUID | None) -> None:
        """Reject a folder that does not exist.

        No cycle check is needed here: a project cannot contain a project, so filing
        one under a folder cannot create a loop. That check lives on the folder
        service, where nesting actually happens.
        """
        if folder_id is None:
            return
        folder = await self.session.get(ProjectFolder, folder_id)
        if folder is None:
            raise NotFoundError("ProjectFolder", folder_id)

    async def create(
        self,
        name: str,
        start_date: date,
        end_date: date,
        folder_id: UUID | None = None,
        position: int = 0,
        external_ref: str | None = None,
        committed_delivery_date: date | None = None,
        customer_id: UUID | None = None,
        priority: ProjectPriority = ProjectPriority.normal,
    ) -> Project:
        """Create a new project, optionally filed under a folder."""
        _validate_project_fields(name, start_date, end_date)
        await self._validate_folder(folder_id)

        project = Project(
            name=name.strip(),
            start_date=start_date,
            end_date=end_date,
            folder_id=folder_id,
            position=position,
            external_ref=_clean_ref(external_ref),
            committed_delivery_date=committed_delivery_date,
            customer_id=customer_id,
            priority=priority,
        )
        self.session.add(project)
        await self.session.commit()
        return project

    async def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
        folder_filter: UUID | Literal["unfiled"] | None = None,
    ) -> tuple[list[Project], int]:
        """Return projects with pagination.

        Args:
            limit: Maximum number of items to return.
            offset: Number of items to skip.
            folder_filter: A folder id to list the projects filed under it, the
                literal ``"unfiled"`` for projects in no folder, or None for
                everything.

        Returns:
            Tuple of (list of projects, total count matching the filter).

        The caller says which of the three it means, because none is a safe default:
        a folder view wants one folder, a cleanup view wants the unfiled ones, and an
        export wants all of them regardless of grouping.
        """
        from sqlmodel import func

        def _apply(statement):
            if folder_filter == "unfiled":
                return statement.where(Project.folder_id.is_(None))
            if folder_filter is not None:
                return statement.where(Project.folder_id == folder_filter)
            return statement

        total_result = await self.session.execute(
            _apply(select(func.count()).select_from(Project))
        )
        total = total_result.scalar_one()

        statement = _apply(select(Project))
        # Ordered by position with name as a tiebreaker, so a listing cannot
        # reorder itself between two requests.
        statement = (
            statement.order_by(Project.position, Project.name)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all()), total

    async def get_by_id(self, project_id: UUID) -> Project:
        """Return a single project by ID.

        Raises:
            NotFoundError: If the project does not exist.

        """
        project = await self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project", project_id)
        return project

    async def update(
        self,
        project_id: UUID,
        name: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        folder_id: UUID | None | UnsetType = UNSET,
        position: int | None = None,
        external_ref: str | None | UnsetType = UNSET,
        committed_delivery_date: date | None | UnsetType = UNSET,
        customer_id: UUID | None | UnsetType = UNSET,
        priority: ProjectPriority | None = None,
    ) -> Project:
        """Update an existing project.

        ``folder_id`` and ``external_ref`` use an explicit UNSET sentinel rather than
        None meaning "leave alone". Both are legitimately nullable, so None has to be
        able to mean "take this out of its folder" and "clear the reference" —
        otherwise a project can be filed but never unfiled.
        """
        project = await self.get_by_id(project_id)

        # Merge: use new values or keep existing ones
        effective_name = name if name is not None else project.name
        effective_start_date = (
            start_date if start_date is not None else project.start_date
        )
        effective_end_date = end_date if end_date is not None else project.end_date

        # Validate with effective values
        _validate_project_fields(
            effective_name,
            effective_start_date,
            effective_end_date,
        )

        if not isinstance(folder_id, UnsetType):
            await self._validate_folder(folder_id)
            project.folder_id = folder_id

        # Update fields
        project.name = effective_name.strip()
        project.start_date = effective_start_date
        project.end_date = effective_end_date
        if position is not None:
            project.position = position
        if not isinstance(external_ref, UnsetType):
            project.external_ref = _clean_ref(external_ref)
        if not isinstance(committed_delivery_date, UnsetType):
            project.committed_delivery_date = committed_delivery_date
        if not isinstance(customer_id, UnsetType):
            project.customer_id = customer_id
        if priority is not None:
            project.priority = priority
        project.updated_at = _utcnow()

        self.session.add(project)
        await self.session.commit()
        return project

    async def delete(self, project_id: UUID) -> None:
        """Delete a project (hard delete).

        No child check: a project cannot contain a project. Grouping lives in
        folders, and deleting a project only removes that project.
        """
        project = await self.get_by_id(project_id)
        await self.session.delete(project)
        await self.session.commit()
