"""Service layer for work package dependencies.

The write path refuses exactly one thing — a cycle — and warns about everything else.
That split is the design: "A after B after A" cannot be scheduled at all, while dates
that contradict a link are an ordinary intermediate state a planner passes through on
the way to a fixed plan.
"""

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.project import WorkPackage, WorkPackageDependency
from app.services.dependencies import DependencyEdge, would_create_cycle


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WorkPackageDependencyService:
    """CRUD for finish-to-start links between work packages."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    async def _all_edges(self) -> list[DependencyEdge]:
        """Every link in the system, as plain edges.

        The whole table, because a cycle check follows a chain of unknown length and a
        per-step round trip would make the cost depend on how deeply a plan happens to
        be linked. Three columns per row, and dependency counts stay in the thousands
        even for a large plan.
        """
        result = await self.session.execute(
            select(
                WorkPackageDependency.predecessor_id,
                WorkPackageDependency.successor_id,
                WorkPackageDependency.lag_working_days,
            )
        )
        return [
            DependencyEdge(
                predecessor_id=row[0], successor_id=row[1], lag_working_days=row[2]
            )
            for row in result.all()
        ]

    async def _require_work_package(self, wp_id: UUID) -> WorkPackage:
        wp = await self.session.get(WorkPackage, wp_id)
        if wp is None:
            raise NotFoundError("WorkPackage", wp_id)
        return wp

    async def list_for_work_package(
        self, wp_id: UUID
    ) -> tuple[list[WorkPackageDependency], list[WorkPackageDependency]]:
        """Links where this package is the successor, and where it is the predecessor.

        Returned as two lists rather than one, because the question a user asks is
        directional: "what has to finish before this can start" is a different question
        from "what is waiting on this".
        """
        await self._require_work_package(wp_id)

        predecessors = await self.session.execute(
            select(WorkPackageDependency).where(
                WorkPackageDependency.successor_id == wp_id
            )
        )
        successors = await self.session.execute(
            select(WorkPackageDependency).where(
                WorkPackageDependency.predecessor_id == wp_id
            )
        )
        return (
            list(predecessors.scalars().all()),
            list(successors.scalars().all()),
        )

    async def create(
        self, predecessor_id: UUID, successor_id: UUID, lag_working_days: int = 0
    ) -> WorkPackageDependency:
        """Link two work packages, refusing a cycle.

        Both ends must exist: a link to a missing package is a dangling reference that
        every reader would have to defend against.

        Raises:
            NotFoundError: If either work package does not exist.
            BusinessRuleError: If the link would close a cycle, or already exists.
        """
        if lag_working_days < 0:
            raise BusinessRuleError(
                "The lag must not be negative.", field="lag_working_days"
            )

        await self._require_work_package(predecessor_id)
        await self._require_work_package(successor_id)

        if predecessor_id == successor_id:
            raise BusinessRuleError(
                "A work package cannot depend on itself.", field="successor_id"
            )

        edges = await self._all_edges()
        if any(
            e.predecessor_id == predecessor_id and e.successor_id == successor_id
            for e in edges
        ):
            raise BusinessRuleError(
                "This dependency already exists.", field="successor_id"
            )
        if would_create_cycle(predecessor_id, successor_id, edges):
            raise BusinessRuleError(
                "This would create a circular dependency: the successor already has "
                "to finish before the predecessor can start.",
                field="successor_id",
            )

        dependency = WorkPackageDependency(
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            lag_working_days=lag_working_days,
        )
        self.session.add(dependency)
        await self.session.commit()
        return dependency

    async def update_lag(
        self, dependency_id: UUID, lag_working_days: int
    ) -> WorkPackageDependency:
        """Change the waiting time on an existing link.

        Only the lag is editable. Repointing a link at different packages would need
        the cycle check again and is indistinguishable from deleting and recreating it,
        which is what the API asks for instead.
        """
        if lag_working_days < 0:
            raise BusinessRuleError(
                "The lag must not be negative.", field="lag_working_days"
            )

        dependency = await self.session.get(WorkPackageDependency, dependency_id)
        if dependency is None:
            raise NotFoundError("WorkPackageDependency", dependency_id)

        dependency.lag_working_days = lag_working_days
        dependency.updated_at = _utcnow()
        self.session.add(dependency)
        await self.session.commit()
        return dependency

    async def delete(self, dependency_id: UUID) -> None:
        """Remove a link. Neither work package is touched."""
        dependency = await self.session.get(WorkPackageDependency, dependency_id)
        if dependency is None:
            raise NotFoundError("WorkPackageDependency", dependency_id)
        await self.session.delete(dependency)
        await self.session.commit()

    async def edges_for_project(self, project_id: UUID) -> list[DependencyEdge]:
        """Links whose SUCCESSOR belongs to the given project.

        Scoped by successor rather than by either end, because the violation is a
        property of the successor's start date — that is the package whose dates a
        warning asks somebody to move. A link crossing project boundaries therefore
        appears on the side that can act on it.
        """
        successor = sa.orm.aliased(WorkPackage)
        result = await self.session.execute(
            select(
                WorkPackageDependency.predecessor_id,
                WorkPackageDependency.successor_id,
                WorkPackageDependency.lag_working_days,
            )
            .join(successor, successor.id == WorkPackageDependency.successor_id)
            .where(successor.project_id == project_id)
        )
        return [
            DependencyEdge(
                predecessor_id=row[0], successor_id=row[1], lag_working_days=row[2]
            )
            for row in result.all()
        ]
