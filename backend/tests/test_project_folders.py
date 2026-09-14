"""Tests for project folders: the tree, the guard, and the delete path.

The delete path is the reason folders exist as their own type. With a
self-referencing ``projects`` table the only safe option was to refuse a delete while
children existed, because removing a project takes its work packages and assignments
with it. A folder holds no plan, so deleting one can unfile its contents instead —
and that behaviour is what these tests pin down.

Pure functions are tested directly; the service uses a hand-written session double.
No database. All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.exceptions import BusinessRuleError, NotFoundError
from app.models.project import Project, ProjectFolder
from app.services.folder_tree import (
    FolderNode,
    ancestors,
    children_of,
    descendants,
    roots,
    would_create_cycle,
)
from app.services.partial_update import UNSET
from app.services.project_folder_service import ProjectFolderService
from app.services.project_progress import (
    WorkPackageProgress,
    completion_ratio,
    derived_status,
)

ORDER = UUID("aaaaaaaa-0000-0000-0000-000000000001")
SUB = UUID("bbbbbbbb-0000-0000-0000-000000000001")
DEEP = UUID("cccccccc-0000-0000-0000-000000000001")
OTHER = UUID("dddddddd-0000-0000-0000-000000000001")


def _node(
    node_id: UUID, parent: UUID | None = None, position: int = 0, name: str = "x"
) -> FolderNode:
    return FolderNode(id=node_id, parent_id=parent, position=position, name=name)


def _folder(
    folder_id: UUID, name: str = "ORD-4711", parent: UUID | None = None
) -> ProjectFolder:
    return ProjectFolder(id=folder_id, name=name, parent_id=parent, position=0)


def _project(project_id: UUID, folder: UUID | None = None) -> Project:
    return Project(
        id=project_id,
        name="Unit 42",
        folder_id=folder,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 6, 30),
    )


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


class TestFolderTree:
    """Walking and ordering."""

    def test_a_top_level_folder_has_no_ancestors(self):
        assert ancestors(ORDER, {ORDER: _node(ORDER)}) == []

    def test_nested_folders_report_nearest_first(self):
        nodes = [_node(ORDER), _node(SUB, ORDER), _node(DEEP, SUB)]
        by_id = {n.id: n for n in nodes}
        assert ancestors(DEEP, by_id) == [SUB, ORDER]

    def test_a_cycle_terminates(self):
        """Corrupt data must not hang a request."""
        by_id = {ORDER: _node(ORDER, SUB), SUB: _node(SUB, ORDER)}
        assert ancestors(ORDER, by_id) == [SUB]

    def test_children_come_back_in_sequence(self):
        nodes = [
            _node(DEEP, ORDER, position=3, name="c"),
            _node(SUB, ORDER, position=1, name="a"),
            _node(OTHER, ORDER, position=2, name="b"),
        ]
        assert [n.id for n in children_of(ORDER, nodes)] == [SUB, OTHER, DEEP]

    def test_equal_positions_fall_back_to_name(self):
        nodes = [
            _node(SUB, ORDER, position=1, name="zeta"),
            _node(DEEP, ORDER, position=1, name="alpha"),
        ]
        assert [n.id for n in children_of(ORDER, nodes)] == [DEEP, SUB]

    def test_roots_exclude_nested_folders(self):
        nodes = [_node(ORDER), _node(SUB, ORDER), _node(OTHER)]
        assert {n.id for n in roots(nodes)} == {ORDER, OTHER}

    def test_descendants_go_all_the_way_down(self):
        nodes = [_node(ORDER), _node(SUB, ORDER), _node(DEEP, SUB), _node(OTHER)]
        assert set(descendants(ORDER, nodes)) == {SUB, DEEP}

    def test_descendants_of_a_leaf_is_empty(self):
        nodes = [_node(ORDER), _node(SUB, ORDER)]
        assert descendants(SUB, nodes) == []

    def test_descendants_terminates_on_a_cycle(self):
        nodes = [_node(ORDER, DEEP), _node(SUB, ORDER), _node(DEEP, SUB)]
        assert set(descendants(ORDER, nodes)) == {SUB, DEEP}


class TestCycleGuard:
    """Refused before the write, not repaired after it."""

    def test_moving_to_top_level_is_always_safe(self):
        nodes = {ORDER: _node(ORDER), SUB: _node(SUB, ORDER)}
        assert would_create_cycle(SUB, None, nodes) is False

    def test_a_folder_cannot_be_its_own_parent(self):
        assert would_create_cycle(ORDER, ORDER, {ORDER: _node(ORDER)}) is True

    def test_a_folder_cannot_move_into_its_own_child(self):
        nodes = {ORDER: _node(ORDER), SUB: _node(SUB, ORDER)}
        assert would_create_cycle(ORDER, SUB, nodes) is True

    def test_a_folder_cannot_move_into_a_grandchild(self):
        nodes = {ORDER: _node(ORDER), SUB: _node(SUB, ORDER), DEEP: _node(DEEP, SUB)}
        assert would_create_cycle(ORDER, DEEP, nodes) is True

    def test_an_unrelated_move_is_allowed(self):
        nodes = {ORDER: _node(ORDER), SUB: _node(SUB, ORDER), OTHER: _node(OTHER)}
        assert would_create_cycle(SUB, OTHER, nodes) is False


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class _FakeSession:
    """Session double over an in-memory folder and project table."""

    def __init__(
        self, folders: list[ProjectFolder], projects: list[Project] | None = None
    ) -> None:
        self.folders = {f.id: f for f in folders}
        self.projects = {p.id: p for p in (projects or [])}
        self.commits = 0
        self.deleted: list[Any] = []

    async def get(self, model: type, pk: UUID) -> Any:
        if model.__name__ == "ProjectFolder":
            return self.folders.get(pk)
        if model.__name__ == "Project":
            return self.projects.get(pk)
        return None

    async def execute(self, statement: Any) -> Any:
        session = self
        text = str(statement)

        if text.strip().upper().startswith("UPDATE PROJECTS"):
            target = self._bound_uuid(statement)
            affected = [p for p in session.projects.values() if p.folder_id == target]
            for project in affected:
                project.folder_id = None
            return type("R", (), {"rowcount": len(affected)})()

        if text.strip().upper().startswith("UPDATE PROJECT_FOLDERS"):
            target = self._bound_uuid(statement)
            affected = [f for f in session.folders.values() if f.parent_id == target]
            new_parent = session.folders[target].parent_id if target else None
            for folder in affected:
                folder.parent_id = new_parent
            return type("R", (), {"rowcount": len(affected)})()

        columns = list(statement.selected_columns)

        class _Result:
            def all(self) -> list[tuple[Any, ...]]:
                if len(columns) == 1:
                    target = _FakeSession._bound_uuid(statement)
                    return [
                        (p.id,)
                        for p in session.projects.values()
                        if p.folder_id == target
                    ]
                return [
                    (f.id, f.parent_id, f.position, f.name)
                    for f in session.folders.values()
                ]

            def scalars(self) -> Any:
                return self

        return _Result()

    @staticmethod
    def _bound_uuid(statement: Any) -> UUID | None:
        """The UUID the statement filters ON, read from the WHERE clause.

        Deliberately not taken from the compiled parameter dict. An
        ``UPDATE project_folders SET parent_id = :a WHERE parent_id = :b`` binds two
        UUIDs under similar names, and picking the first one silently matched the SET
        value instead of the filter — a double that guesses can report a pass for
        behaviour the service does not have.
        """
        clause = statement.whereclause
        if clause is None:
            return None
        value = getattr(getattr(clause, "right", None), "value", None)
        if isinstance(value, UUID):
            return value
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, UUID):
                    return item
        return None

    def add(self, obj: Any) -> None:
        if isinstance(obj, ProjectFolder):
            self.folders[obj.id] = obj

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)
        self.folders.pop(obj.id, None)

    async def commit(self) -> None:
        self.commits += 1


def _service(
    folders: list[ProjectFolder], projects: list[Project] | None = None
) -> tuple[ProjectFolderService, _FakeSession]:
    session = _FakeSession(folders, projects)
    return ProjectFolderService(session), session  # type: ignore[arg-type]


class TestCreateAndUpdate:
    """Validation on the write paths."""

    @pytest.mark.asyncio
    async def test_a_blank_name_is_refused(self):
        service, _ = _service([])
        with pytest.raises(BusinessRuleError):
            await service.create("   ")

    @pytest.mark.asyncio
    async def test_the_name_is_trimmed(self):
        service, _ = _service([])
        folder = await service.create("  ORD-4711  ")
        assert folder.name == "ORD-4711"

    @pytest.mark.asyncio
    async def test_a_nonexistent_parent_is_a_404(self):
        service, _ = _service([])
        with pytest.raises(NotFoundError):
            await service.create("Sub", parent_id=uuid4())

    @pytest.mark.asyncio
    async def test_a_move_into_a_own_subfolder_is_refused(self):
        service, _ = _service([_folder(ORDER), _folder(SUB, "Sub", parent=ORDER)])
        with pytest.raises(BusinessRuleError, match="sub-folders"):
            await service.update(ORDER, parent_id=SUB)

    @pytest.mark.asyncio
    async def test_an_explicit_null_moves_a_folder_to_the_top(self):
        """Otherwise a nested folder can never be un-nested."""
        service, _ = _service([_folder(ORDER), _folder(SUB, "Sub", parent=ORDER)])
        result = await service.update(SUB, parent_id=None)
        assert result.parent_id is None

    @pytest.mark.asyncio
    async def test_omitting_the_parent_leaves_it_alone(self):
        service, _ = _service([_folder(ORDER), _folder(SUB, "Sub", parent=ORDER)])
        result = await service.update(SUB, name="Renamed")
        assert result.parent_id == ORDER

    @pytest.mark.asyncio
    async def test_unset_also_leaves_the_parent_alone(self):
        service, _ = _service([_folder(ORDER), _folder(SUB, "Sub", parent=ORDER)])
        result = await service.update(SUB, parent_id=UNSET)
        assert result.parent_id == ORDER


class TestDelete:
    """The whole reason a folder is not a project."""

    @pytest.mark.asyncio
    async def test_deleting_a_folder_unfiles_its_projects(self):
        """It must never be able to delete a plan."""
        project = _project(uuid4(), folder=ORDER)
        service, session = _service([_folder(ORDER)], [project])

        unfiled, moved = await service.delete(ORDER)

        assert unfiled == 1
        assert project.folder_id is None
        assert project.id in session.projects
        assert [f.id for f in session.deleted] == [ORDER]

    @pytest.mark.asyncio
    async def test_subfolders_move_up_one_level(self):
        service, session = _service(
            [
                _folder(ORDER),
                _folder(SUB, "Sub", parent=ORDER),
                _folder(DEEP, "Deep", parent=SUB),
            ]
        )
        unfiled, moved = await service.delete(SUB)

        assert moved == 1
        assert session.folders[DEEP].parent_id == ORDER

    @pytest.mark.asyncio
    async def test_deleting_a_top_level_folder_unnests_its_children(self):
        service, session = _service([_folder(ORDER), _folder(SUB, "Sub", parent=ORDER)])
        await service.delete(ORDER)
        assert session.folders[SUB].parent_id is None

    @pytest.mark.asyncio
    async def test_deleting_an_empty_folder_reports_nothing_moved(self):
        service, _ = _service([_folder(ORDER)])
        assert await service.delete(ORDER) == (0, 0)

    @pytest.mark.asyncio
    async def test_deleting_a_missing_folder_is_a_404(self):
        service, _ = _service([])
        with pytest.raises(NotFoundError):
            await service.delete(uuid4())


# ---------------------------------------------------------------------------
# Derived progress — unchanged by folders, still project-level
# ---------------------------------------------------------------------------


def _package(name: str, completed: datetime | None = None) -> WorkPackageProgress:
    return WorkPackageProgress(
        id=uuid4(), name=name, end_date=date(2026, 6, 5), completed_at=completed
    )


class TestDerivedProgress:
    """Progress belongs to the project, not to its grouping."""

    def test_nothing_completed_means_no_status(self):
        assert derived_status([_package("Strahlen")]) is None

    def test_furthest_is_by_completion_time_not_by_schedule(self):
        packages = [
            _package("Grundieren", datetime(2026, 6, 2, 10, 0)),
            _package("Decklack", datetime(2026, 6, 9, 16, 0)),
        ]
        assert derived_status(packages) == "Decklack"

    def test_empty_ratio_is_zero_not_complete(self):
        assert completion_ratio([]) == 0.0

    def test_half_completed(self):
        now = datetime(2026, 6, 2, 10, 0)
        assert completion_ratio([_package("a", now), _package("b")]) == 0.5
