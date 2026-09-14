"""Fill in a project's resolved customer for the API response.

One helper rather than the resolution repeated at each return point. Four endpoints return a project,
and a fifth added later that forgot this would silently ship an empty customer column — which looks
like "no customer" rather than like a bug, and is therefore the kind of omission nobody reports.

Two queries per call regardless of how many projects are being enriched: the folder tree and the
customer names are loaded once and reused. Per-project resolution would be a query per row for a
value that is usually inherited from a folder shared by all of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.customer import Customer
from app.models.project import Project, ProjectFolder
from app.schemas.project import ProjectResponse
from app.services.customer_resolution import (
    FolderNode,
    inherited_from_folder,
    resolve_customer_id,
)


async def _context(
    session: AsyncSession,
) -> tuple[dict[UUID, FolderNode], dict[UUID, str]]:
    """The folder tree and customer names needed to resolve any project."""
    folders = (await session.execute(select(ProjectFolder))).scalars().all()
    customers = (await session.execute(select(Customer))).scalars().all()
    return (
        {
            folder.id: FolderNode(
                folder_id=folder.id,
                parent_id=folder.parent_id,
                customer_id=folder.customer_id,
            )
            for folder in folders
        },
        {customer.id: customer.name for customer in customers},
    )


async def enrich_projects(
    session: AsyncSession, projects: Sequence[Project]
) -> list[ProjectResponse]:
    """Build responses with the resolved customer filled in.

    Returns an empty list for no projects without querying, so a filtered page that matched
    nothing costs nothing.
    """
    if not projects:
        return []
    folder_nodes, customer_names = await _context(session)
    responses: list[ProjectResponse] = []
    for project in projects:
        resolved = resolve_customer_id(
            project.customer_id, project.folder_id, folder_nodes
        )
        response = ProjectResponse.model_validate(project, from_attributes=True)
        # The NAME, not just the id: a client that had to look the name up itself would either
        # hold a second copy of the customer list or show a UUID.
        response.customer_name = customer_names.get(resolved) if resolved else None
        response.customer_inherited = inherited_from_folder(
            project.customer_id, project.folder_id, folder_nodes
        )
        responses.append(response)
    return responses


async def enrich_project(session: AsyncSession, project: Project) -> ProjectResponse:
    """Single-project convenience wrapper."""
    return (await enrich_projects(session, [project]))[0]
