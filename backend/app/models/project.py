"""SQLAlchemy models for projects and work packages."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ORMModel
from app.utils.utc_datetime import UTCDateTime


class ProjectPriority(StrEnum):
    """Cross-project urgency, distinct from position.

    ``position`` orders units WITHIN a folder — the sequence they are worked in.
    Priority answers a different question: which of two units gets the crane when both
    want it, regardless of which order they belong to.

    Four named levels rather than a free integer. Integers invite duelling ranks nobody
    can read — is 30 more urgent than 40? — while a small ordered set is legible at a
    glance and sorts deterministically.
    """

    low = "low"
    normal = "normal"
    high = "high"
    critical = "critical"


def _utcnow() -> datetime:
    return datetime.now(UTC)


if TYPE_CHECKING:
    from app.models.assignment import Assignment


class ProjectFolder(ORMModel, kw_only=True, eq=False):
    """A folder that projects can be grouped under. Optional by design.

    A folder is deliberately NOT a project. An earlier version made ``Project``
    self-referencing, which forced a container to carry a start date, an end date
    and potentially work packages — none of which a grouping has — and forced
    deletion to be refused whenever children existed, because deleting a project
    with children would take real planned work with it. Making the container its own
    type removes all of that: a folder has a name, deleting one merely unfiles what
    was in it, and nothing can accidentally schedule against it (ADR-008).

    In the deployment this was designed against a folder is an order and each unit a
    project inside it, because the unit is what actually gets scheduled. A customer who groups by
    customer, by year, or not at all needs no migration to say so.

    Attributes:
        parent_id: Owning folder, or NULL for a top-level one. Folders may nest
            because grouping by customer AND by order is an ordinary wish, and the
            cycle guard that makes nesting safe is the same one either way. Depth is
            not capped: a limit picked now would be a guess.
        position: Order among siblings, for a stable listing.
        external_ref: The grouping's own identifier — an order number where a
            folder groups one order. Projects have their own
            (the unit number); this is the level above. Indexed and not unique,
            because the same reference legitimately recurs.
    """

    __tablename__ = "project_folders"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("project_folders.id"),
        nullable=True,
        index=True,
        default=None,
    )
    position: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, index=True, default=0
    )
    external_ref: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True, index=True, default=None
    )
    # The customer for everything below this folder. Inherited by the projects inside it and by
    # sub-folders that name nobody — see app/services/customer_resolution.py for the rule.
    customer_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "customers.id", name="project_folders_customer_id_fkey", ondelete="SET NULL"
        ),
        nullable=True,
        index=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )


class Project(ORMModel, kw_only=True, eq=False):
    """A planned unit: whatever the plant actually schedules work against.

    Attributes:
        folder_id: Optional grouping. NULL means unfiled, which is the default and a
            perfectly normal state — a deployment that never creates a folder behaves
            exactly as it did before folders existed.
        position: Order within the folder. The units of an order are worked through
            in sequence, and deriving that from start dates breaks the moment two
            start on the same day. This states intent, not dependency — it does not
            say one unit cannot begin until another finishes.
        external_ref: Free identifier from whatever system the customer already
            uses. One operator fills it with a unit number; elsewhere it is a
            serial number, a VIN, a batch id, or empty. A column named after one
            industry's vocabulary would write that vocabulary into the schema.
        customer_id: Who the work is for, overriding the folder. A plain string
            rather than an entity: it maps to the column a planner types into today,
            and an entity would add a management surface nobody asked for. Indexed,
            because "everything for customer X" is asked across all projects at once.
        priority: Cross-project urgency, distinct from ``position``. See
            :class:`ProjectPriority`.
        committed_delivery_date: What was PROMISED, as opposed to what is planned.

            Separate from ``end_date`` on purpose. One field cannot hold both a
            commitment and a plan: the moment they differ — which is the moment that
            matters — a single date has to silently pick one, and whichever it picks
            makes the other invisible. With two fields, "the plan no longer meets the
            promise" is a question the system can answer.

            Nullable, because internal work has no customer date and inventing one
            would produce warnings about promises nobody made.
    """

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    folder_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("project_folders.id"),
        nullable=True,
        index=True,
        default=None,
    )
    position: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, index=True, default=0
    )
    external_ref: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True, index=True, default=None
    )
    committed_delivery_date: Mapped[date | None] = mapped_column(
        sa.Date(), nullable=True, index=True, default=None
    )
    # Overrides the folder's customer when set. Read it through resolve_customer_id, never
    # directly: a project that inherits from its folder has NULL here, and that is the normal
    # case rather than the exception.
    customer_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "customers.id", name="projects_customer_id_fkey", ondelete="SET NULL"
        ),
        nullable=True,
        index=True,
        default=None,
    )
    priority: Mapped[ProjectPriority] = mapped_column(
        sa.Enum(
            ProjectPriority,
            name="projectpriority",
            native_enum=True,
            length=8,
            create_constraint=False,
        ),
        nullable=False,
        index=True,
        default=ProjectPriority.normal,
    )
    start_date: Mapped[date] = mapped_column(sa.Date(), nullable=False)
    end_date: Mapped[date] = mapped_column(sa.Date(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )

    work_packages: Mapped[list["WorkPackage"]] = relationship(
        back_populates="project", init=False, repr=False, compare=False
    )


class WorkPackage(ORMModel, kw_only=True, eq=False):
    """Work package within a project.

    Skill requirements are stored directly on the work package
    (work_package_requirements table).

    Attributes:
        completed_at: When the work finished, or NULL while it has not. A
            timestamp rather than a boolean because "when did it finish" is the
            question a delay analysis asks, and a flag cannot answer it.

            This is where progress lives. A status field on the project was
            rejected: the values a planner writes there are work package names,
            so storing them on the parent would be a second copy of the truth,
            free to drift from what it summarises (ADR-008).
    """

    __tablename__ = "work_packages"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    project_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(sa.Date(), nullable=False)
    end_date: Mapped[date] = mapped_column(sa.Date(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, index=True, default=None
    )
    # Copied from the template when one is applied, so a later template edit does
    # not silently restate what an in-flight work package promised.
    lead_time_working_days: Mapped[int | None] = mapped_column(
        sa.Integer(), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )

    project: Mapped[Project | None] = relationship(
        back_populates="work_packages", init=False, repr=False, compare=False
    )
    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="work_package", init=False, repr=False, compare=False
    )


class WorkPackageDependency(ORMModel, kw_only=True, eq=False):
    """A finish-to-start link between two work packages, with an optional lag.

    One relationship type on purpose. Start-to-start and finish-to-finish are
    expressible by reordering the pair, and start-to-finish is almost never what
    anybody means. What a plant needs beyond finish-to-start is waiting time — paint
    curing before the next step can begin — and ``lag_working_days`` covers that
    without a second type.

    A violated dependency is reported as a warning rather than refused. Enforcing it
    would mean rescheduling on the planner's behalf, and a planner who cannot enter
    what they actually intend goes back to the spreadsheet — the same failure a hard
    plan freeze would cause (ADR-007). Cycles are the exception and are refused at the
    write, because "A after B after A" has no valid reading at all.

    Attributes:
        lag_working_days: Working days that must pass after the predecessor ends before
            the successor may start. Zero means the next working day, since a successor
            starting the same day would overlap — which finish-to-start denies by
            definition. Counted in working days so a weekend cannot silently satisfy
            curing time.
    """

    __tablename__ = "work_package_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "predecessor_id",
            "successor_id",
            name="uq_work_package_dependencies_pair",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    predecessor_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "work_packages.id",
            name="work_package_dependencies_predecessor_id_fkey",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    successor_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey(
            "work_packages.id",
            name="work_package_dependencies_successor_id_fkey",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    lag_working_days: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
