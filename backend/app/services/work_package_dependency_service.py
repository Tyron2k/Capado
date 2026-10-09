"""Service layer for work package dependencies.

The write path refuses exactly one thing — a cycle — and warns about everything else.
That split is the design: "A after B after A" cannot be scheduled at all, while dates
that contradict a link are an ordinary intermediate state a planner passes through on
the way to a fixed plan.
"""

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.project import WorkPackage, WorkPackageDependency
from app.services.dependencies import DependencyEdge, would_create_cycle
from app.services.graph_locks import lock_graph
from app.services.work_package_service import WorkPackageService


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

    async def _require_work_package(
        self, wp_id: UUID, project_id: UUID | None = None
    ) -> WorkPackage:
        return await WorkPackageService(self.session).get_by_id(
            wp_id, project_id=project_id
        )

    async def _require_dependency(
        self, dependency_id: UUID, successor_id: UUID | None, project_id: UUID | None
    ) -> WorkPackageDependency:
        if successor_id is not None:
            await self._require_work_package(successor_id, project_id)
        dependency = await self.session.get(WorkPackageDependency, dependency_id)
        if dependency is None or (
            successor_id is not None and dependency.successor_id != successor_id
        ):
            raise NotFoundError("WorkPackageDependency", dependency_id)
        return dependency

    async def list_for_work_package(
        self, wp_id: UUID, *, project_id: UUID | None = None
    ) -> tuple[list[WorkPackageDependency], list[WorkPackageDependency]]:
        """Links where this package is the successor, and where it is the predecessor.

        Returned as two lists rather than one, because the question a user asks is
        directional: "what has to finish before this can start" is a different question
        from "what is waiting on this".
        """
        await self._require_work_package(wp_id, project_id)

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
        self,
        predecessor_id: UUID,
        successor_id: UUID,
        lag_working_days: int = 0,
        *,
        project_id: UUID | None = None,
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

        await lock_graph(self.session, "dependencies")
        if (
            isinstance(self.session, AsyncSession)
            and self.session.get_bind().dialect.name == "postgresql"
        ):
            # Keep endpoints present until the validated edge has committed. A delete
            # waits for key-share locks; acquire before audit FK writes and in ID order.
            endpoints = list(
                (
                    await self.session.execute(
                        select(WorkPackage)
                        .where(WorkPackage.id.in_({predecessor_id, successor_id}))
                        .order_by(WorkPackage.id)
                        .with_for_update(read=True, key_share=True)
                        .execution_options(populate_existing=True)
                    )
                )
                .scalars()
                .all()
            )
            present = {wp.id for wp in endpoints}
            for wp_id in (predecessor_id, successor_id):
                if wp_id not in present:
                    raise NotFoundError("WorkPackage", wp_id)
        await self._require_work_package(predecessor_id)
        await self._require_work_package(successor_id, project_id)

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
        self,
        dependency_id: UUID,
        lag_working_days: int,
        *,
        successor_id: UUID | None = None,
        project_id: UUID | None = None,
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

        dependency = await self._require_dependency(
            dependency_id, successor_id, project_id
        )

        dependency.lag_working_days = lag_working_days
        dependency.updated_at = _utcnow()
        self.session.add(dependency)
        await self.session.commit()
        return dependency

    async def delete(
        self,
        dependency_id: UUID,
        *,
        successor_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> None:
        """Remove a link. Neither work package is touched."""
        await lock_graph(self.session, "dependencies")
        dependency = await self._require_dependency(
            dependency_id, successor_id, project_id
        )
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

    async def edges_for_projects(
        self, project_ids: set[UUID]
    ) -> dict[UUID, list[DependencyEdge]]:
        """Read successor-scoped dependencies for an overview in one query.

        Cross-project predecessors stay attached to the successor's project.
        Reuse the caller's transaction; this is a targeted query, not a second
        persistence abstraction or a loop of per-project requests.
        """
        if not project_ids:
            return {}
        successor = sa.orm.aliased(WorkPackage)
        result = await self.session.execute(
            select(
                successor.project_id,
                WorkPackageDependency.predecessor_id,
                WorkPackageDependency.successor_id,
                WorkPackageDependency.lag_working_days,
            )
            .join(successor, successor.id == WorkPackageDependency.successor_id)
            .where(successor.project_id.in_(project_ids))
        )
        grouped: dict[UUID, list[DependencyEdge]] = {}
        for project_id, predecessor_id, successor_id, lag in result.all():
            grouped.setdefault(project_id, []).append(
                DependencyEdge(predecessor_id, successor_id, lag)
            )
        return grouped
