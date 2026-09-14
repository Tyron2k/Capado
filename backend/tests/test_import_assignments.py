"""Unit tests for assignment import in app.services.import_export.assignments.

Pure unit tests without database — uses a mock AsyncSession to verify
the import logic (CSV parsing, resource resolution, duplicate detection,
error reporting, correct assignment field shapes).
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.assignment import Assignment
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.services.import_export import import_assignments

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fixed IDs for test entities
PROJECT_ID = uuid4()
WP_ID = uuid4()
WP2_ID = uuid4()
WP3_ID = uuid4()
INFRA_GROUP_ID = uuid4()
PERSONAL_GROUP_ID = uuid4()
INFRA_RESOURCE_ID = uuid4()
PERSONAL_RESOURCE_ID = uuid4()


def _make_project(
    name="Test Project Alpha", start=date(2026, 7, 1), end=date(2026, 8, 31)
):
    p = Project(id=PROJECT_ID, name=name, start_date=start, end_date=end)
    return p


def _make_wp(
    name="Grundierung", start=date(2026, 7, 10), end=date(2026, 7, 20), wp_id=None
):
    return WorkPackage(
        id=wp_id or WP_ID,
        project_id=PROJECT_ID,
        name=name,
        start_date=start,
        end_date=end,
    )


def _make_infra(name="Bay 62"):
    return InfrastructureResource(
        id=INFRA_RESOURCE_ID, name=name, group_id=INFRA_GROUP_ID, is_active=True
    )


def _make_personal(name="Max Mustermann"):
    return PersonalResource(
        id=PERSONAL_RESOURCE_ID, name=name, group_id=PERSONAL_GROUP_ID, is_active=True
    )


def _mock_scalars_result(items):
    """Create a mock that simulates session.execute().scalars().all() / .first()."""
    mock = MagicMock()
    mock.scalars.return_value = mock
    mock.all.return_value = items
    mock.first.return_value = items[0] if items else None
    return mock


def _build_mock_session(
    projects=None,
    work_packages=None,
    infra_resources=None,
    personal_resources=None,
    existing_assignments=None,
):
    """Build a mock AsyncSession that returns the given entities for queries.

    The mock dispatches based on the order of execute() calls that
    import_assignments makes:
    1. Projects
    2. Infrastructure resources
    3. Personal resources
    4. Existing assignments
    5+ Work package lookups (per row)
    """
    session = AsyncMock()

    projects = projects or []
    infra_resources = infra_resources or []
    personal_resources = personal_resources or []
    existing_assignments = existing_assignments or []
    work_packages = work_packages or []

    # The import function calls session.execute() in this order:
    # 1. select(Project) -> all projects
    # 2. select(InfrastructureResource) -> all infra
    # 3. select(PersonalResource) -> all personal
    # 4. select(Assignment) -> existing assignments
    # Then per-row: select(WorkPackage) for WP resolution

    call_counter = {"n": 0}

    async def mock_execute(stmt):
        call_counter["n"] += 1
        n = call_counter["n"]

        if n == 1:  # Projects
            return _mock_scalars_result(projects)
        elif n == 2:  # Infra resources
            return _mock_scalars_result(infra_resources)
        elif n == 3:  # Personal resources
            return _mock_scalars_result(personal_resources)
        elif n == 4:  # Existing assignments
            return _mock_scalars_result(existing_assignments)
        else:
            # Work package lookups (per row)
            return _mock_scalars_result(work_packages)

    session.execute = mock_execute
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    return session


# ---------------------------------------------------------------------------
# Empty / header validation
# ---------------------------------------------------------------------------


class TestImportAssignmentsValidation:
    """Tests for structural validation (empty file, bad header)."""

    async def test_empty_file_reports_error(self):
        """Empty file is reported as error."""
        session = _build_mock_session()
        result = await import_assignments(session, [])
        assert len(result.errors) == 1
        assert "empty" in result.errors[0].lower()

    async def test_too_few_columns_reports_error(self):
        """Header with fewer than 5 columns is rejected."""
        session = _build_mock_session()
        rows = [("Project", "Resource", "Start")]
        result = await import_assignments(session, rows)
        assert len(result.errors) == 1
        assert "header" in result.errors[0].lower()

    async def test_no_data_rows_produces_zero_counts(self):
        """File with header only produces zero counts and no errors."""
        session = _build_mock_session()
        rows = [("Project", "Resource", "Start", "End", "Allocation")]
        result = await import_assignments(session, rows)
        assert result.created == 0
        assert result.errors == []


# ---------------------------------------------------------------------------
# 5-column format: infrastructure
# ---------------------------------------------------------------------------


class TestImport5ColInfra:
    """Tests for 5-column format with infrastructure resources."""

    async def test_creates_infra_assignment(self):
        """Infrastructure resource gets an assignment with start_at/end_at."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra()],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Bay 62", "2026-07-12", "2026-07-15", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 1
        assert result.errors == []

        # Verify the assignment was added with correct shape
        added = session.add.call_args_list[-1][0][0]
        assert isinstance(added, Assignment)
        assert added.resource_type == "infrastructure"
        assert added.start_at == datetime(2026, 7, 12, 6, 0, 0)
        assert added.end_at == datetime(2026, 7, 15, 18, 0, 0)
        assert added.start_date is None
        assert added.allocation_percent is None

    async def test_error_on_missing_project(self):
        """Reports error when project doesn't exist."""
        session = _build_mock_session(
            projects=[],  # No projects
            infra_resources=[_make_infra()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Nonexistent", "Bay 62", "2026-07-12", "2026-07-15", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 0
        assert len(result.errors) == 1
        assert "project" in result.errors[0].lower()
        assert "not found" in result.errors[0].lower()

    async def test_error_on_missing_resource(self):
        """Reports error when resource doesn't exist."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[],
            personal_resources=[],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Phantom", "2026-07-12", "2026-07-15", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 0
        assert len(result.errors) == 1
        assert "resource" in result.errors[0].lower()
        assert "not found" in result.errors[0].lower()

    async def test_error_on_invalid_date_format(self):
        """Reports error for non-ISO date format."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Bay 62", "12.07.2026", "15.07.2026", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 0
        assert len(result.errors) == 1
        assert "date" in result.errors[0].lower()

    async def test_error_on_missing_start_date(self):
        """Reports error when start date is empty."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Bay 62", "", "2026-07-15", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 0
        assert len(result.errors) == 1
        assert "required" in result.errors[0].lower()

    async def test_skips_empty_rows(self):
        """Rows with empty project/resource are silently skipped."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra()],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("", "", "", "", ""),
            ("Test Project Alpha", "Bay 62", "2026-07-12", "2026-07-15", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 1
        assert result.errors == []

    async def test_skips_duplicate_same_resource_and_wp(self):
        """Second assignment to same resource+WP is skipped."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra()],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Bay 62", "2026-07-12", "2026-07-15", "100"),
            ("Test Project Alpha", "Bay 62", "2026-07-16", "2026-07-18", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 1
        assert result.skipped == 1


# ---------------------------------------------------------------------------
# 5-column format: personal
# ---------------------------------------------------------------------------


class TestImport5ColPersonal:
    """Tests for 5-column format with personal resources."""

    async def test_creates_personal_assignment(self):
        """Personal resource gets an assignment with start_date/end_date/allocation."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[],
            personal_resources=[_make_personal()],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Max Mustermann", "2026-07-12", "2026-07-15", "50"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 1
        assert result.errors == []

        added = session.add.call_args_list[-1][0][0]
        assert isinstance(added, Assignment)
        assert added.resource_type == "personal"
        assert added.start_date == date(2026, 7, 12)
        assert added.end_date == date(2026, 7, 15)
        assert added.allocation_percent == 50.0
        assert added.start_at is None

    async def test_default_allocation_is_100(self):
        """Empty allocation column defaults to 100%."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[],
            personal_resources=[_make_personal()],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Max Mustermann", "2026-07-12", "2026-07-15", ""),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 1
        added = session.add.call_args_list[-1][0][0]
        assert added.allocation_percent == 100.0

    async def test_infra_preferred_over_personal_on_name_collision(self):
        """When both infra and personal match, infrastructure wins."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra("Shared Name")],
            personal_resources=[_make_personal("Shared Name")],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Shared Name", "2026-07-12", "2026-07-15", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 1
        added = session.add.call_args_list[-1][0][0]
        assert added.resource_type == "infrastructure"


# ---------------------------------------------------------------------------
# 6-column format
# ---------------------------------------------------------------------------


class TestImport6Col:
    """Tests for 6-column format (Project;Work Package;Resource;Start;End;Allocation)."""

    async def test_detects_6col_format_by_header(self):
        """Header with 'Work Package' as second column triggers 6-col mode."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra()],
            work_packages=[_make_wp("Finish")],
        )

        rows = [
            ("Project", "Work Package", "Resource", "Start", "End", "Allocation"),
            (
                "Test Project Alpha",
                "Finish",
                "Bay 62",
                "2026-07-12",
                "2026-07-15",
                "100",
            ),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 1
        assert result.errors == []

    async def test_error_on_nonexistent_work_package(self):
        """Reports error when explicit WP name is not found."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra()],
            work_packages=[],  # No matching WP
        )

        rows = [
            ("Project", "Work Package", "Resource", "Start", "End", "Allocation"),
            (
                "Test Project Alpha",
                "Ghost WP",
                "Bay 62",
                "2026-07-12",
                "2026-07-15",
                "100",
            ),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 0
        assert len(result.errors) == 1
        assert "not found" in result.errors[0].lower()
        assert "work package" in result.errors[0].lower()

    async def test_case_insensitive_project_lookup(self):
        """Project lookup is case-insensitive."""
        session = _build_mock_session(
            projects=[_make_project("Test Project Alpha")],
            infra_resources=[_make_infra()],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("test project alpha", "Bay 62", "2026-07-12", "2026-07-15", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 1
        assert result.errors == []


# ---------------------------------------------------------------------------
# Multiple rows / batch
# ---------------------------------------------------------------------------


class TestImportBatch:
    """Tests for multi-row imports with mixed success/failure."""

    async def test_mixed_valid_and_invalid_rows(self):
        """Valid rows succeed, invalid rows report errors, processing continues."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra()],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Bay 62", "2026-07-12", "2026-07-15", "100"),
            ("Nonexistent", "Bay 62", "2026-07-16", "2026-07-18", "100"),
        ]

        result = await import_assignments(session, rows)

        assert result.created == 1
        assert len(result.errors) == 1

    async def test_commits_once_at_end(self):
        """session.commit() is called exactly once after all rows."""
        session = _build_mock_session(
            projects=[_make_project()],
            infra_resources=[_make_infra()],
            work_packages=[_make_wp()],
        )

        rows = [
            ("Project", "Resource", "Start", "End", "Allocation"),
            ("Test Project Alpha", "Bay 62", "2026-07-12", "2026-07-15", "100"),
        ]

        await import_assignments(session, rows)

        session.commit.assert_called_once()
