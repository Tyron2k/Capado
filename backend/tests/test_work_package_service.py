"""Tests for :mod:`app.services.work_package_service`.

Covers the update path and the project-boundary warnings:

- A missing parent project raises :class:`NotFoundError` (404) instead of
  dereferencing ``None`` and surfacing as an opaque 500.
- Partial updates keep untouched fields.
- ``end_date < start_date`` is rejected as a business rule violation.
- Property-based invariants for ``_check_project_boundaries``.

No database is used: the session is a hand-written double. All data is inline
and clearly fictional.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.project import Project, WorkPackage
from app.services.work_package_service import (
    WorkPackageService,
    _check_project_boundaries,
)


class _FakeSession:
    """Minimal async session double: ``get`` serves a preloaded object map."""

    def __init__(self, objects: dict[tuple[str, UUID], Any] | None = None) -> None:
        self._objects = objects or {}
        self.commits = 0

    async def get(self, model: type, pk: UUID) -> Any:
        return self._objects.get((model.__name__, pk))

    def add(self, obj: Any) -> None:  # noqa: D102 - no-op for the double
        pass

    async def commit(self) -> None:  # noqa: D102 - no-op for the double
        self.commits += 1


def _project(start: date = date(2026, 1, 1), end: date = date(2026, 12, 31)) -> Project:
    """Fictional project spanning the given range."""
    return Project(id=uuid4(), name="Test Project A", start_date=start, end_date=end)


def _work_package(project: Project) -> WorkPackage:
    """Fictional work package inside the given project's range."""
    return WorkPackage(
        id=uuid4(),
        project_id=project.id,
        name="Work Package One",
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 20),
        # A fixed past timestamp so the bump on update is observable.
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _service(*objects: Any) -> tuple[WorkPackageService, _FakeSession]:
    """Build a service whose session serves the given model instances."""
    mapping = {(type(obj).__name__, obj.id): obj for obj in objects}
    session = _FakeSession(mapping)
    return WorkPackageService(session), session  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


async def test_update_missing_work_package_raises_not_found() -> None:
    service, _ = _service()
    with pytest.raises(NotFoundError):
        await service.update(uuid4(), name="Renamed")


async def test_update_missing_project_raises_not_found() -> None:
    """A work package whose project is gone must not blow up as a 500."""
    project = _project()
    work_package = _work_package(project)
    # Deliberately register only the work package, not its project.
    service, session = _service(work_package)

    with pytest.raises(NotFoundError):
        await service.update(work_package.id, start_date=date(2026, 3, 3))

    assert session.commits == 0


async def test_update_changes_dates_and_returns_no_warnings_inside_project() -> None:
    project = _project()
    work_package = _work_package(project)
    previous_updated_at = work_package.updated_at
    service, session = _service(project, work_package)

    updated, warnings = await service.update(
        work_package.id,
        start_date=date(2026, 4, 6),
        end_date=date(2026, 4, 24),
    )

    assert updated.updated_at > previous_updated_at

    assert (updated.start_date, updated.end_date) == (
        date(2026, 4, 6),
        date(2026, 4, 24),
    )
    assert updated.name == "Work Package One"
    assert warnings == []
    assert session.commits == 1


async def test_update_only_name_keeps_dates() -> None:
    project = _project()
    work_package = _work_package(project)
    service, _ = _service(project, work_package)

    updated, warnings = await service.update(work_package.id, name="  Renamed  ")

    assert updated.name == "Renamed"
    assert (updated.start_date, updated.end_date) == (
        date(2026, 3, 2),
        date(2026, 3, 20),
    )
    assert warnings == []


async def test_update_end_before_start_is_rejected() -> None:
    project = _project()
    work_package = _work_package(project)
    service, session = _service(project, work_package)

    with pytest.raises(BusinessRuleError) as exc_info:
        await service.update(work_package.id, end_date=date(2026, 3, 1))

    assert exc_info.value.field == "end_date"
    assert session.commits == 0


async def test_update_blank_name_is_rejected() -> None:
    project = _project()
    work_package = _work_package(project)
    service, session = _service(project, work_package)

    with pytest.raises(BusinessRuleError) as exc_info:
        await service.update(work_package.id, name="   ")

    assert exc_info.value.field == "name"
    assert session.commits == 0


async def test_update_outside_project_range_warns_but_saves() -> None:
    project = _project(date(2026, 1, 1), date(2026, 6, 30))
    work_package = _work_package(project)
    service, session = _service(project, work_package)

    updated, warnings = await service.update(
        work_package.id,
        start_date=date(2025, 12, 1),
        end_date=date(2026, 7, 15),
    )

    assert len(warnings) == 2
    assert updated.start_date == date(2025, 12, 1)
    assert session.commits == 1


# ---------------------------------------------------------------------------
# _check_project_boundaries (property-based)
# ---------------------------------------------------------------------------

_DATES = st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31))


@settings(max_examples=200)
@given(
    project_start=_DATES,
    project_span=st.integers(min_value=0, max_value=800),
    wp_start=_DATES,
    wp_span=st.integers(min_value=0, max_value=800),
)
def test_boundary_warnings_match_out_of_range_edges(
    project_start: date,
    project_span: int,
    wp_start: date,
    wp_span: int,
) -> None:
    """One warning per out-of-range edge, and none while fully contained."""
    project = _project(project_start, project_start + timedelta(days=project_span))
    wp_end = wp_start + timedelta(days=wp_span)

    warnings = _check_project_boundaries(wp_start, wp_end, project)

    expected = int(wp_start < project.start_date) + int(wp_end > project.end_date)
    assert len(warnings) == expected
    if wp_start >= project.start_date and wp_end <= project.end_date:
        assert warnings == []
