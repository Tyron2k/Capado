"""Customer CRUD.

Small on purpose. A customer here is a name, a reference and a note — everything else about a
customer lives in whatever system actually manages customers, and inventing an address book in a
capacity planning tool would be a second place to keep the same data current.

Duplicates are refused case-insensitively at the database level. That is the entire reason this
entity exists, replacing a free-text column where "Acme" and "Acme GmbH" were two customers and
nothing could say they were one.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.database import get_session
from app.models.customer import Customer
from app.models.project import Project, ProjectFolder
from app.models.user import User
from app.services.permissions import (
    EntityType,
    check_write_permission,
    get_current_user,
)

# main.py adds the /api prefix.
router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerCreate(BaseModel):
    """Request body for creating a customer."""

    name: str = Field(min_length=1, max_length=255)
    reference: str = Field(default="", max_length=128)
    note: str = Field(default="", max_length=1000)


class CustomerUpdate(BaseModel):
    """Partial update. Omitted fields are left alone."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    reference: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class CustomerResponse(BaseModel):
    """A customer, with what depends on it."""

    id: UUID
    name: str
    reference: str
    note: str
    is_active: bool
    folder_count: int = Field(
        default=0,
        description="Folders naming this customer. Shown before a delete, because deleting one "
        "clears the link on every folder and project that pointed at it.",
    )
    project_count: int = Field(
        default=0, description="Projects naming this customer directly, folders aside."
    )

    model_config = {"from_attributes": True}


async def _counts(session: AsyncSession) -> tuple[dict[UUID, int], dict[UUID, int]]:
    """Folder and project counts per customer, in two queries rather than per row."""
    folder_rows = await session.execute(
        select(ProjectFolder.customer_id, func.count())
        .where(ProjectFolder.customer_id.is_not(None))
        .group_by(ProjectFolder.customer_id)
    )
    project_rows = await session.execute(
        select(Project.customer_id, func.count())
        .where(Project.customer_id.is_not(None))
        .group_by(Project.customer_id)
    )
    return (
        {row[0]: row[1] for row in folder_rows.all()},
        {row[0]: row[1] for row in project_rows.all()},
    )


@router.get("", response_model=list[CustomerResponse], summary="List customers")
async def list_customers(
    include_inactive: bool = Query(
        default=False,
        description="Include retired customers. Off by default so pickers stay short, but "
        "available because a report over historical projects needs them.",
    ),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[CustomerResponse]:
    """Customers, active first, by name."""
    statement = select(Customer)
    if not include_inactive:
        statement = statement.where(Customer.is_active == True)  # noqa: E712
    statement = statement.order_by(Customer.name.asc())
    customers = (await session.execute(statement)).scalars().all()
    folder_counts, project_counts = await _counts(session)
    return [
        CustomerResponse(
            id=customer.id,
            name=customer.name,
            reference=customer.reference,
            note=customer.note,
            is_active=customer.is_active,
            folder_count=folder_counts.get(customer.id, 0),
            project_count=project_counts.get(customer.id, 0),
        )
        for customer in customers
    ]


@router.post(
    "",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer",
)
async def create_customer(
    data: CustomerCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CustomerResponse:
    """Create a customer, refusing a case-insensitive duplicate."""
    check_write_permission(current_user, EntityType.project)
    customer = Customer(
        name=data.name.strip(), reference=data.reference.strip(), note=data.note
    )
    session.add(customer)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # 409 rather than 422: the request is well-formed, the name is simply taken. The message
        # names the collision so the operator can pick the existing one instead of inventing a
        # variant spelling, which is the behaviour this entity exists to prevent.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ein Kunde mit dem Namen „{data.name.strip()}“ existiert bereits.",
        ) from exc
    await session.refresh(customer)
    return CustomerResponse.model_validate(customer, from_attributes=True)


@router.patch(
    "/{customer_id}", response_model=CustomerResponse, summary="Update a customer"
)
async def update_customer(
    customer_id: UUID,
    data: CustomerUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CustomerResponse:
    """Update a customer. Retiring one leaves every project's link intact."""
    check_write_permission(current_user, EntityType.project)
    customer = (
        (await session.execute(select(Customer).where(Customer.id == customer_id)))
        .scalars()
        .first()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden.")

    if data.name is not None:
        customer.name = data.name.strip()
    if data.reference is not None:
        customer.reference = data.reference.strip()
    if data.note is not None:
        customer.note = data.note
    if data.is_active is not None:
        customer.is_active = data.is_active
    customer.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.add(customer)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ein Kunde mit diesem Namen existiert bereits.",
        ) from exc
    await session.refresh(customer)
    return CustomerResponse.model_validate(customer, from_attributes=True)


@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a customer",
)
async def delete_customer(
    customer_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a customer.

    The foreign keys are ON DELETE SET NULL, so folders and projects keep everything except the
    link. That is deliberate: RESTRICT would mean a customer entered by mistake can never be
    removed once a project points at it, and CASCADE would delete the work.

    Retiring (``is_active = false``) is usually what an operator actually wants — it keeps the
    customer off pickers while historical projects still name them. The API offers both rather
    than deciding.
    """
    check_write_permission(current_user, EntityType.project)
    customer = (
        (await session.execute(select(Customer).where(Customer.id == customer_id)))
        .scalars()
        .first()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden.")
    await session.delete(customer)
    await session.commit()
