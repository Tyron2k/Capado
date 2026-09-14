"""
Unit tests for SQLModel models.

Validates instantiation, defaults, enums, and validation rules for the
current schema (Alembic head: 012):

- ``PersonalResource``: no free-text qualification field; management
  responsibility is derived from User scopes.
- ``InfrastructureResource``: no ``type`` enum and no ``capacity_per_day``
  anymore (Alembic 006). Equipment runs via ``equipment_types``.
  Absences and maintenance are managed as regular Assignments.
- ``Assignment`` carries two shapes: Personal (start_date/end_date/
  allocation_percent) and Infrastructure (start_at/end_at).
"""

from datetime import date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models import (
    Assignment,
    Conflict,
    ConflictAssignment,
    InfrastructureResource,
    PersonalResource,
    Project,
    ResourceType,
    WorkPackage,
)


class TestPersonalResource:
    """Tests for PersonalResource model."""

    def test_create_valid(self):
        group_id = "00000000-0000-0000-0000-000000000001"
        r = PersonalResource(
            name="Resource 1",
            group_id=group_id,
        )
        assert isinstance(r.id, UUID)
        assert r.name == "Resource 1"
        assert str(r.group_id) == group_id
        assert r.is_active is True
        assert isinstance(r.created_at, datetime)
        assert isinstance(r.updated_at, datetime)

    def test_name_required(self):
        with pytest.raises(ValidationError):
            PersonalResource.model_validate(
                {
                    "group_id": "00000000-0000-0000-0000-000000000001",
                }
            )


class TestInfrastructureResource:
    """Tests for InfrastructureResource model."""

    def test_create_valid(self):
        group_id = "00000000-0000-0000-0000-000000000001"
        r = InfrastructureResource(
            name="Hall A",
            group_id=group_id,
        )
        assert isinstance(r.id, UUID)
        assert r.name == "Hall A"
        assert str(r.group_id) == group_id
        assert r.is_active is True


class TestProject:
    """Tests for Project model."""

    def test_create_valid(self):
        p = Project(
            name="Projekt Alpha",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        assert isinstance(p.id, UUID)
        assert p.name == "Projekt Alpha"
        assert p.start_date == date(2025, 1, 1)
        assert p.end_date == date(2025, 12, 31)

    def test_name_required(self):
        with pytest.raises(ValidationError):
            Project.model_validate(
                {
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                }
            )


class TestWorkPackage:
    """Tests for WorkPackage model."""

    def test_create_valid(self):
        wp = WorkPackage(
            project_id="00000000-0000-0000-0000-000000000001",
            name="Arbeitspaket 1",
            start_date=date(2025, 2, 1),
            end_date=date(2025, 3, 31),
        )
        assert isinstance(wp.id, UUID)
        assert wp.name == "Arbeitspaket 1"
        assert wp.start_date == date(2025, 2, 1)
        assert wp.end_date == date(2025, 3, 31)


class TestAssignment:
    """Tests for Assignment model."""

    def test_create_personal_shape(self):
        a = Assignment(
            resource_id="00000000-0000-0000-0000-000000000001",
            resource_type=ResourceType.personal,
            work_package_id="00000000-0000-0000-0000-000000000002",
            start_date=date(2025, 2, 1),
            end_date=date(2025, 2, 28),
            allocation_percent=50.0,
        )
        assert isinstance(a.id, UUID)
        assert a.resource_type == ResourceType.personal
        assert a.allocation_percent == 50.0
        assert a.start_at is None and a.end_at is None

    def test_create_infrastructure_shape(self):
        a = Assignment(
            resource_id="00000000-0000-0000-0000-000000000001",
            resource_type=ResourceType.infrastructure,
            work_package_id="00000000-0000-0000-0000-000000000002",
            start_at=datetime(2026, 6, 1, 6, 0),
            end_at=datetime(2026, 6, 1, 15, 0),
        )
        assert a.resource_type == ResourceType.infrastructure
        assert a.start_date is None and a.end_date is None
        assert a.allocation_percent is None

    def test_allocation_must_be_positive(self):
        with pytest.raises(ValidationError):
            Assignment.model_validate(
                {
                    "resource_id": "00000000-0000-0000-0000-000000000001",
                    "resource_type": "personal",
                    "work_package_id": "00000000-0000-0000-0000-000000000002",
                    "start_date": "2025-02-01",
                    "end_date": "2025-02-28",
                    "allocation_percent": 0,
                }
            )


class TestConflict:
    """Tests for Conflict model."""

    def test_create_valid(self):
        c = Conflict(
            resource_id="00000000-0000-0000-0000-000000000001",
            resource_type=ResourceType.personal,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 5),
            total_assigned_percent=150.0,
            available_percent=100.0,
        )
        assert isinstance(c.id, UUID)
        assert c.total_assigned_percent == 150.0
        assert c.available_percent == 100.0
        assert isinstance(c.detected_at, datetime)


class TestConflictAssignment:
    """Tests for ConflictAssignment link table."""

    def test_create_valid(self):
        ca = ConflictAssignment(
            conflict_id="00000000-0000-0000-0000-000000000001",
            assignment_id="00000000-0000-0000-0000-000000000002",
        )
        assert ca.conflict_id is not None
        assert ca.assignment_id is not None


class TestEnums:
    """Tests for enum values."""

    def test_resource_type_values(self):
        assert ResourceType.personal.value == "personal"
        assert ResourceType.infrastructure.value == "infrastructure"
