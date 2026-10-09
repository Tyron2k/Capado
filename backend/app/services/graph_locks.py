"""Serialize structural planning writes, without locking unrelated application work."""

from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_GRAPH_NAMESPACE = (
    0x43_41_50_47  # CAPG; distinct from scheduler CAPO and resource keys.
)
_GRAPH_KEYS = {"dependencies": 1, "folders": 2}


async def lock_graph(
    session: AsyncSession, graph: Literal["dependencies", "folders"]
) -> None:
    """Hold one graph's lock through validation/write and release on transaction end.

    Cross-project dependencies can connect arbitrary components. Serializing that
    graph's structural writes protects the full cycle check; folder hierarchy writes
    use another key. Metadata edits, reads and resource planning do not acquire it.
    SQLite/session doubles are not evidence of PostgreSQL concurrency behavior.
    """
    if (
        isinstance(session, AsyncSession)
        and session.get_bind().dialect.name == "postgresql"
    ):
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
            {"namespace": _GRAPH_NAMESPACE, "key": _GRAPH_KEYS[graph]},
        )
