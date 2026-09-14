"""Pydantic schemas for projects and work packages (request/response)."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.project import ProjectPriority

# --- Project Schemas ---


class ProjectFolderCreate(BaseModel):
    """Request schema for creating a project folder."""

    name: str
    parent_id: UUID | None = None
    position: int = Field(default=0, ge=0)
    # The grouping's own identifier — an order number where a folder is an order.
    external_ref: str | None = Field(default=None, max_length=128)
    # Set here and inherited by every project inside, which is the point: one entry per
    # job instead of one per stage.
    customer_id: UUID | None = None


class ProjectFolderUpdate(BaseModel):
    """Request schema for updating a folder (partial update).

    Sending ``parent_id`` as null moves the folder to the top level; omitting it
    leaves the parent alone. The router tells the two apart by what was sent.
    """

    name: str | None = None
    parent_id: UUID | None = None
    position: int | None = Field(default=None, ge=0)
    external_ref: str | None = Field(default=None, max_length=128)
    customer_id: UUID | None = None


class ProjectFolderResponse(BaseModel):
    """Response schema for a project folder."""

    id: UUID
    name: str
    parent_id: UUID | None = None
    position: int = 0
    external_ref: str | None = None
    customer_id: UUID | None = None
    customer_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectFolderDeleteResponse(BaseModel):
    """What a folder deletion did.

    Reported rather than silent: the user should see that their projects survived
    and merely became unfiled.
    """

    projects_unfiled: int
    subfolders_moved: int


class ProjectCreate(BaseModel):
    """Request schema for creating a project.

    ``folder_id`` is optional grouping and NULL by default. A deployment that never
    creates a folder behaves exactly as it did before folders existed (ADR-008).
    """

    name: str
    start_date: date
    end_date: date
    folder_id: UUID | None = None
    # Explicit sequence. The units of an order are worked through in order, and
    # deriving that from start dates breaks the moment two of them start on the
    # same day.
    position: int = Field(default=0, ge=0)
    # A foreign key into whatever the customer already uses — a unit number for one
    # operator, a serial or batch id elsewhere. Not unique: the same reference
    # legitimately recurs when a unit is reworked under a second order.
    external_ref: str | None = Field(default=None, max_length=128)
    # What was PROMISED, as opposed to end_date which is what is planned. Nullable:
    # internal work has no customer date, and inventing one would produce warnings
    # about promises nobody made.
    committed_delivery_date: date | None = None
    customer_id: UUID | None = None
    # Cross-project urgency, distinct from position which orders within a folder.
    priority: ProjectPriority = ProjectPriority.normal


class ProjectUpdate(BaseModel):
    """Request schema for updating a project (partial update).

    ``folder_id`` and ``external_ref`` are nullable fields, so sending them as null
    means "take out of the folder" / "clear the reference", while omitting them leaves
    them alone. The router distinguishes the two by what the client actually sent, not
    by the value.
    """

    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    folder_id: UUID | None = None
    position: int | None = Field(default=None, ge=0)
    external_ref: str | None = Field(default=None, max_length=128)
    committed_delivery_date: date | None = None
    customer_id: UUID | None = None
    priority: ProjectPriority | None = None


class ProjectResponse(BaseModel):
    """Response schema for a project."""

    id: UUID
    name: str
    start_date: date
    end_date: date
    folder_id: UUID | None = None
    position: int = 0
    external_ref: str | None = None
    committed_delivery_date: date | None = None
    customer_id: UUID | None = None
    # The RESOLVED name, folder inheritance included, so a client does not reimplement the walk.
    customer_name: str | None = None
    # True when the name came from a folder rather than from the project. Surfaced so an
    # operator does not "correct" a value they never typed and pin it by accident.
    customer_inherited: bool = False
    priority: ProjectPriority = ProjectPriority.normal
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- WorkPackage Schemas ---


class WorkPackageCreate(BaseModel):
    """Request schema for creating a work package."""

    name: str
    start_date: date
    end_date: date
    # Duration in WORKING days, the unit the templates were already written in.
    # Used to warn when the entered end date cannot hold the process; the entered
    # date itself is never overwritten.
    lead_time_working_days: int | None = Field(default=None, ge=1)


class WorkPackageUpdate(BaseModel):
    """Request schema for updating a work package (partial update)."""

    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    lead_time_working_days: int | None = Field(default=None, ge=1)
    # A timestamp rather than a boolean: "when did it finish" is what a delay
    # analysis asks, and a flag cannot answer it. Sending null reopens the package.
    completed_at: datetime | None = None


class WorkPackageResponse(BaseModel):
    """Response schema for a work package."""

    id: UUID
    project_id: UUID
    name: str
    start_date: date
    end_date: date
    lead_time_working_days: int | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkPackageDependencyCreate(BaseModel):
    """Request schema for linking two work packages, finish to start."""

    predecessor_id: UUID
    # Working days that must pass after the predecessor ends. Zero means the next
    # working day, since a successor starting the same day would overlap.
    lag_working_days: int = Field(default=0, ge=0)


class WorkPackageDependencyUpdate(BaseModel):
    """Request schema for changing the waiting time on an existing link.

    Only the lag is editable. Repointing a link is indistinguishable from deleting and
    recreating it, and would need the cycle check again.
    """

    lag_working_days: int = Field(ge=0)


class WorkPackageDependencyResponse(BaseModel):
    """Response schema for one finish-to-start link."""

    id: UUID
    predecessor_id: UUID
    successor_id: UUID
    lag_working_days: int

    model_config = {"from_attributes": True}


class WorkPackageDependenciesResponse(BaseModel):
    """Both directions, because the question a user asks is directional.

    "What has to finish before this can start" is a different question from "what is
    waiting on this", and one merged list answers neither clearly.
    """

    predecessors: list[WorkPackageDependencyResponse]
    successors: list[WorkPackageDependencyResponse]


class WorkPackageCreateResponse(BaseModel):
    """Response schema for a newly created work package (with warnings)."""

    work_package: WorkPackageResponse
    warnings: list[str] = []


class WorkPackageUpdateResponse(BaseModel):
    """Response schema for an updated work package (with warnings)."""

    work_package: WorkPackageResponse
    warnings: list[str] = []
