"""Service layer for project folders.

Folders are optional grouping. Nothing in planning depends on them, which is what
makes the delete path safe: removing a folder can never remove planned work, only
the grouping. That is the whole reason a folder is its own type rather than a parent
project (ADR-008).
"""

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.project import Project, ProjectFolder
from app.services.folder_tree import FolderNode, descendants, would_create_cycle
from app.services.partial_update import UNSET, UnsetType
from app.services.project_service import _clean_ref


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _validate_name(name: str | None) -> str:
    """Require a non-blank name and return it trimmed."""
    if not name or not name.strip():
        raise BusinessRuleError("The field 'Name' is required.", field="name")
    return name.strip()


class ProjectFolderService:
    """CRUD for project folders."""

    def __init__(self, session: AsyncSession):
        """Initialize with a database session."""
        self.session = session

    async def _tree(self) -> dict[UUID, FolderNode]:
        """Every folder's tree fields, keyed by id.

        The whole table, because a cycle check follows a parent chain of unknown
        length and a per-step round trip would make the cost depend on how deeply the
        user happened to nest things. Four columns per row.
        """
        result = await self.session.execute(
            select(
                ProjectFolder.id,
                ProjectFolder.parent_id,
                ProjectFolder.position,
                ProjectFolder.name,
            )
        )
        return {
            row[0]: FolderNode(
                id=row[0], parent_id=row[1], position=row[2], name=row[3]
            )
            for row in result.all()
        }

    async def _validate_parent(
        self, folder_id: UUID | None, parent_id: UUID | None
    ) -> None:
        """Reject a parent that does not exist or would close a cycle."""
        if parent_id is None:
            return
        if folder_id is not None and parent_id == folder_id:
            raise BusinessRuleError(
                "A folder cannot be its own parent.", field="parent_id"
            )

        tree = await self._tree()
        if parent_id not in tree:
            raise NotFoundError("ProjectFolder", parent_id)
        if folder_id is not None and would_create_cycle(folder_id, parent_id, tree):
            raise BusinessRuleError(
                "A folder cannot be moved into one of its own sub-folders.",
                field="parent_id",
            )

    async def get_by_id(self, folder_id: UUID) -> ProjectFolder:
        """Return one folder.

        Raises:
            NotFoundError: If the folder does not exist.
        """
        folder = await self.session.get(ProjectFolder, folder_id)
        if folder is None:
            raise NotFoundError("ProjectFolder", folder_id)
        return folder

    async def get_all(self) -> list[ProjectFolder]:
        """Return every folder, ordered for a stable listing.

        Unpaginated on purpose: folders are a navigation aid a human maintains by
        hand, so the count stays in the dozens, and a tree that arrives one page at a
        time cannot be rendered as a tree.
        """
        result = await self.session.execute(
            select(ProjectFolder).order_by(ProjectFolder.position, ProjectFolder.name)
        )
        return list(result.scalars().all())

    async def create(
        self,
        name: str,
        parent_id: UUID | None = None,
        position: int = 0,
        external_ref: str | None = None,
        customer_id: UUID | None = None,
    ) -> ProjectFolder:
        """Create a folder, optionally inside another."""
        clean_name = _validate_name(name)
        await self._validate_parent(None, parent_id)

        folder = ProjectFolder(
            name=clean_name,
            parent_id=parent_id,
            position=position,
            external_ref=_clean_ref(external_ref),
            customer_id=customer_id,
        )
        self.session.add(folder)
        await self.session.commit()
        return folder

    async def update(
        self,
        folder_id: UUID,
        name: str | None = None,
        parent_id: UUID | None | UnsetType = UNSET,
        position: int | None = None,
        external_ref: str | None | UnsetType = UNSET,
        customer_id: UUID | None | UnsetType = UNSET,
    ) -> ProjectFolder:
        """Update a folder.

        ``parent_id`` uses the UNSET sentinel because it is nullable: an explicit
        null has to mean "move to the top level", which None-means-unchanged cannot
        express.
        """
        folder = await self.get_by_id(folder_id)

        if name is not None:
            folder.name = _validate_name(name)
        if not isinstance(parent_id, UnsetType):
            await self._validate_parent(folder_id, parent_id)
            folder.parent_id = parent_id
        if position is not None:
            folder.position = position
        if not isinstance(customer_id, UnsetType):
            folder.customer_id = customer_id
        if not isinstance(external_ref, UnsetType):
            folder.external_ref = _clean_ref(external_ref)

        folder.updated_at = _utcnow()
        self.session.add(folder)
        await self.session.commit()
        return folder

    async def delete(self, folder_id: UUID) -> tuple[int, int]:
        """Delete a folder, keeping everything that was in it.

        Projects inside are unfiled — ``folder_id`` back to NULL — and sub-folders
        are re-parented one level up. Nothing is cascaded away, because a project
        carries work packages and assignments and deleting a grouping must never be
        able to delete a plan.

        This is the payoff of a folder not being a project: with a self-referencing
        ``projects`` table the only safe option was to refuse the delete outright.

        Returns:
            (projects unfiled, sub-folders re-parented).
        """
        folder = await self.get_by_id(folder_id)
        parent_id = folder.parent_id

        unfiled = await self.session.execute(
            sa.update(Project)
            .where(Project.folder_id == folder_id)
            .values(folder_id=None)
        )
        moved = await self.session.execute(
            sa.update(ProjectFolder)
            .where(ProjectFolder.parent_id == folder_id)
            .values(parent_id=parent_id)
        )

        await self.session.delete(folder)
        await self.session.commit()
        return unfiled.rowcount or 0, moved.rowcount or 0

    async def project_ids_in(
        self, folder_id: UUID, *, include_subfolders: bool = False
    ) -> list[UUID]:
        """Ids of the projects filed under a folder.

        ``include_subfolders`` exists because both readings are legitimate: a folder
        view usually wants its own contents, while a roll-up over an order that was
        subdivided wants everything beneath it. Neither is a safe default, so the
        caller says which.
        """
        folder_ids = [folder_id]
        if include_subfolders:
            tree = await self._tree()
            folder_ids.extend(descendants(folder_id, list(tree.values())))

        result = await self.session.execute(
            select(Project.id)
            .where(Project.folder_id.in_(folder_ids))
            .order_by(Project.position, Project.name)
        )
        return [row[0] for row in result.all()]
