"""Shared fixtures. Chiefly: a real database for tests that need one.

WHY THIS DID NOT EXIST, AND WHY IT COULD

Every test in this suite was DB-free, using hand-built session doubles. That is a good default — it
keeps the suite at roughly 30 seconds — but it leaves one class of claim unverifiable: whether a
statement is correct against an actual schema. A double records that a DELETE was issued against a
table; it cannot notice that the WHERE clause selects the wrong rows, or that a column was renamed.

The erasure feature made that gap concrete. It deletes across seven tables, four of which reference a
person through a polymorphic ``resource_id`` with no foreign key, so the database can neither cascade
nor complain. Its unit tests assert every table was addressed and say so honestly: "what this cannot
tell is that the SQL is correct against a real schema."

**SQLite is viable here, and that was not obvious.** The schema looked Postgres-bound — array columns
for user scopes, JSON for audit changes. But ``app/utils/pg_types.py`` already implements
``UUIDArray`` as a ``TypeDecorator`` that returns ``ARRAY(UUID)`` on PostgreSQL and **JSON
everywhere else**. The portability was built and never used. All 31 tables create on SQLite
unmodified, verified before this file was written.

WHAT THIS HARNESS IS AND IS NOT

It is a *sharper* check than a double, not a *complete* one. SQLite and PostgreSQL differ where it
matters most for this application:

- **No real ARRAY type.** Scope columns become JSON, so a query using PostgreSQL array containment
  would pass here and fail in production. Do not test scope filtering with this.
- **Weaker constraint enforcement.** Foreign keys are off by default in SQLite; the fixture enables
  them, but ``ON DELETE`` semantics and deferred constraints still differ.
- **Different collation and no ILIKE.** Case-insensitive matching — which the importers rely on —
  behaves differently.

So: use it to verify that statements hit the rows they mean to. For anything that depends on
PostgreSQL semantics, a container-backed test is the only honest answer, and there is nowhere to put
one yet.

The engine is per-test and in-memory. A shared engine across tests in a parallel suite (``-n auto``)
would let one test see another's rows, which is the failure mode that makes a DB suite untrustworthy
rather than merely slow.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401  — registers every table on SQLModel.metadata


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A session against a fresh in-memory database with the real schema.

    ``StaticPool`` is required, not cosmetic: SQLite's ``:memory:`` database belongs to a single
    connection, so the default pool would hand a later query a NEW empty database and the test would
    fail with a missing table rather than with the thing it was testing.

    Foreign keys are switched on per connection. SQLite ignores them by default, and a harness that
    silently accepts a violated key would give false confidence about exactly the constraints this
    schema does declare.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    """Present for libraries that look for it; the suite itself runs on pytest-asyncio."""
    return "asyncio"
