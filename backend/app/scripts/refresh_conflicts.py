"""One-off helper: refresh conflicts for resources that have plan data.

Usage (inside the backend container)::

    python -m app.scripts.refresh_conflicts

Useful after bulk seed loads, because the seed loader inserts Assignments
directly without going through the AssignmentService, which means the normal
"refresh on create/update/delete" trigger is bypassed. Resources with stored
conflicts but no remaining assignments are included so stale rows are cleared.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.database import async_session_factory


async def _refresh_all() -> int:
    async with async_session_factory() as session:
        from app.services.conflict_refresh import refresh_resources

        return await refresh_resources(session)


def main() -> int:
    """Run the conflict refresh script and print the result count."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    total = asyncio.run(_refresh_all())
    print(f"refreshed conflicts, {total} conflict rows now stored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
