"""Every paginated list query must carry a TOTAL ordering.

This is not a tidiness rule. ``OFFSET``/``LIMIT`` over a query with no ``ORDER BY`` leaves the row
order undefined *between the two requests that fetch page 1 and page 2*, so Postgres is free to
return one row on both pages and never return another at all. All three queries here paginated
without ordering, which is how the infrastructure list came to look "chronological": it was showing
insertion order, and past 100 rows it could also have been showing a row twice.

"Total" matters as much as "ordered": ordering by ``name`` alone is not enough, because two resources
may share a name and their relative order would again be undefined. Each query therefore ends in a
tiebreaker that cannot repeat.

There is no database in this suite, so the assertion is made against the COMPILED SQL of the
statement the service hands to ``execute``. That is one level below behaviour, and deliberately so:
the ordering is a property of the statement, and this is the only place it can be read without
standing up Postgres.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

from app.services import resource_service
from app.services.work_package_service import WorkPackageService


class _CapturingSession:
    """Async session double that records every statement and serves empty results.

    ``get`` answers with a stand-in object because ``get_by_project`` checks the parent project
    exists before it queries — without it the call raises NotFoundError and never builds the
    statement this test is about.
    """

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> Any:
        self.statements.append(statement)
        return _EmptyResult()

    async def get(self, model: type, pk: Any) -> Any:
        return model(
            id=pk,
            name="Fictional Project",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )


class _EmptyResult:
    """Answers both shapes the services ask for: a count, and a row list."""

    def scalar_one(self) -> int:
        return 0

    def scalars(self) -> _EmptyResult:
        return self

    def all(self) -> list[Any]:
        return []


def _paginated_sql(session: _CapturingSession) -> str:
    """Return the compiled SQL of the statement that carries LIMIT/OFFSET.

    The services issue a COUNT first, which legitimately has no ordering — picking the statement by
    its LIMIT rather than by position keeps this test from breaking when that order changes.
    """
    for statement in session.statements:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if "LIMIT" in sql.upper():
            return sql
    raise AssertionError("no paginated statement was issued")


async def test_personal_resource_list_orders_by_name_then_id() -> None:
    session = _CapturingSession()

    await resource_service.get_all_personal_resources(session)  # type: ignore[arg-type]

    sql = _paginated_sql(session).upper()
    assert "ORDER BY" in sql
    assert sql.index("PERSONAL_RESOURCES.NAME") < sql.index(
        "PERSONAL_RESOURCES.ID", sql.index("ORDER BY")
    )


async def test_infrastructure_list_orders_by_name_then_id() -> None:
    session = _CapturingSession()

    await resource_service.get_all_infrastructure_resources(session)  # type: ignore[arg-type]

    sql = _paginated_sql(session)
    order_by = sql.upper().index("ORDER BY")
    assert "infrastructure_resources.name" in sql[order_by:]
    assert "infrastructure_resources.id" in sql[order_by:]


async def test_work_packages_are_ordered_chronologically_not_by_insertion() -> None:
    session = _CapturingSession()

    await WorkPackageService(session).get_by_project(uuid4())  # type: ignore[arg-type]

    sql = _paginated_sql(session)
    order_by = sql.upper().index("ORDER BY")
    tail = sql[order_by:]
    # start_date first: the complaint was that a package starting in March appeared below one
    # starting in June because it was typed later.
    assert tail.index("work_packages.start_date") < tail.index("work_packages.end_date")
    assert "work_packages.name" in tail
    # created_at must NOT be what orders the list — that is exactly the insertion order being fixed.
    assert "work_packages.created_at" not in tail


async def test_ordering_survives_a_group_filter() -> None:
    """The filter is applied to the base query, so it must not drop the ordering."""
    session = _CapturingSession()

    await resource_service.get_all_infrastructure_resources(session, group_id=uuid4())  # type: ignore[arg-type]

    sql = _paginated_sql(session).upper()
    assert "WHERE" in sql
    assert "ORDER BY" in sql


async def test_date_bearing_work_package_query_is_unaffected_by_ordering() -> None:
    """A sanity check that get_by_project still filters by project rather than by date."""
    session = _CapturingSession()
    project_id = uuid4()

    await WorkPackageService(session).get_by_project(project_id)  # type: ignore[arg-type]

    sql = _paginated_sql(session)
    assert "work_packages.project_id" in sql
    # Guard against a future refactor quietly turning the list into a date-window query.
    assert str(date(2026, 1, 1)) not in sql
