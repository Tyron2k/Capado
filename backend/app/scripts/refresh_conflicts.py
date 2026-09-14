"""One-off helper: refresh conflicts for every active resource.

Usage (inside the backend container)::

    python -m app.scripts.refresh_conflicts

Useful after bulk seed loads, because the seed loader inserts Assignments
directly without going through the AssignmentService, which means the
normal "refresh on create/update/delete" trigger is bypassed.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlmodel import select

from app.database import async_session_factory
from app.models.resource import InfrastructureResource, PersonalResource
from app.services.conflict_service import ConflictService


async def _refresh_all() -> int:
    async with async_session_factory() as session:
        personal_stmt = select(PersonalResource).where(
            PersonalResource.is_active == True  # noqa: E712
        )
        infra_stmt = select(InfrastructureResource).where(
            InfrastructureResource.is_active == True  # noqa: E712
        )

        personal_ids = [
            r.id for r in (await session.execute(personal_stmt)).scalars().all()
        ]
        infra_ids = [r.id for r in (await session.execute(infra_stmt)).scalars().all()]

        service = ConflictService(session)

        total = 0
        for rid in personal_ids + infra_ids:
            conflicts = await service.refresh_conflicts(rid)
            total += len(conflicts)
        return total


def main() -> int:
    """Run the conflict refresh script and print the result count."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    total = asyncio.run(_refresh_all())
    print(f"refreshed conflicts, {total} conflict rows now stored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
