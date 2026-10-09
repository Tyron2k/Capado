"""CSV validation schemas for project rows."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.project import ProjectPriority


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class ProjectFolderTransfer(BaseModel):
    """Validate persisted project_folders rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(max_length=255)
    parent_id: UUID | None = Field(default=None)
    position: int = Field(default=0)
    external_ref: str | None = Field(default=None, max_length=128)
    customer_id: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ProjectTransfer(BaseModel):
    """Validate persisted projects rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(max_length=255)
    folder_id: UUID | None = Field(default=None)
    position: int = Field(default=0)
    external_ref: str | None = Field(default=None, max_length=128)
    committed_delivery_date: date | None = Field(default=None)
    customer_id: UUID | None = Field(default=None)
    priority: ProjectPriority = Field(default=ProjectPriority.normal)
    start_date: date
    end_date: date
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkPackageTransfer(BaseModel):
    """Validate persisted work_packages rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    name: str = Field(max_length=255)
    start_date: date
    end_date: date
    completed_at: datetime | None = Field(default=None)
    lead_time_working_days: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkPackageDependencyTransfer(BaseModel):
    """Validate persisted work_package_dependencies rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    predecessor_id: UUID
    successor_id: UUID
    lag_working_days: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
