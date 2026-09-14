"""Calendar router: working-time configuration.

Sites, holidays, week profiles, their bindings, and infrastructure availability
windows — the supply side of the capacity model.

    GET    /api/sites                          List sites
    POST   /api/sites                          Create a site
    PUT    /api/sites/{id}                     Update a site
    DELETE /api/sites/{id}                     Deactivate a site

    GET    /api/holidays?site_id=&from=&to=    List calendar exceptions
    POST   /api/holidays                       Create a calendar exception
    PUT    /api/holidays/{id}                  Update a calendar exception
    DELETE /api/holidays/{id}                  Delete a calendar exception

    GET    /api/work-week-profiles             List week profiles
    POST   /api/work-week-profiles             Create a week profile
    PUT    /api/work-week-profiles/{id}        Update a week profile
    DELETE /api/work-week-profiles/{id}        Delete a week profile

    GET    /api/resource-work-profiles         List bindings
    POST   /api/resource-work-profiles         Bind a resource to a profile
    DELETE /api/resource-work-profiles/{id}    Remove a binding

    GET    /api/infrastructure/{id}/windows    List availability windows
    POST   /api/infrastructure-windows         Create an availability window
    DELETE /api/infrastructure-windows/{id}    Delete an availability window

Reads require authentication; writes require admin. This is organization-wide
configuration in the same class as branding: a change to a week profile silently
alters the capacity of every resource using it, so it does not belong to
group-scoped editors.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.calendar import (
    AvailabilityWindowCreate,
    AvailabilityWindowResponse,
    HolidayCreate,
    HolidayResponse,
    HolidayUpdate,
    ResourceWorkProfileCreate,
    ResourceWorkProfileResponse,
    SiteCreate,
    SiteResponse,
    SiteUpdate,
    WorkWeekProfileCreate,
    WorkWeekProfileResponse,
    WorkWeekProfileUpdate,
)
from app.services.calendar_service import CalendarService, weekly_minutes
from app.services.permissions import get_current_user, require_admin

router = APIRouter(tags=["Calendar"])


def _profile_response(profile) -> WorkWeekProfileResponse:  # noqa: ANN001
    """Attach the weekly total, which the UI would otherwise recompute."""
    response = WorkWeekProfileResponse.model_validate(profile)
    response.weekly_minutes = weekly_minutes(profile)
    return response


# --------------------------------------------------------------------- sites


@router.get("/sites", response_model=list[SiteResponse])
async def list_sites(
    include_inactive: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[SiteResponse]:
    """List sites."""
    sites = await CalendarService(session).list_sites(include_inactive)
    return [SiteResponse.model_validate(site) for site in sites]


@router.post("/sites", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
async def create_site(
    body: SiteCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> SiteResponse:
    """Create a site."""
    site = await CalendarService(session).create_site(
        body.name, body.region_code, body.is_default
    )
    return SiteResponse.model_validate(site)


@router.put("/sites/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: UUID,
    body: SiteUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> SiteResponse:
    """Update a site."""
    site = await CalendarService(session).update_site(
        site_id, **body.model_dump(exclude_unset=True)
    )
    return SiteResponse.model_validate(site)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_site(
    site_id: UUID,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Deactivate a site (soft delete)."""
    await CalendarService(session).deactivate_site(site_id)


# ------------------------------------------------------------------ holidays


@router.get("/holidays", response_model=list[HolidayResponse])
async def list_holidays(
    site_id: UUID | None = Query(default=None),
    from_day: date | None = Query(default=None, alias="from"),
    to_day: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[HolidayResponse]:
    """List calendar exceptions."""
    holidays = await CalendarService(session).list_holidays(site_id, from_day, to_day)
    return [HolidayResponse.model_validate(holiday) for holiday in holidays]


@router.post(
    "/holidays",
    response_model=HolidayResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_holiday(
    body: HolidayCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> HolidayResponse:
    """Create a calendar exception."""
    holiday = await CalendarService(session).create_holiday(
        body.site_id, body.day, body.name, body.working_minutes
    )
    return HolidayResponse.model_validate(holiday)


@router.put("/holidays/{holiday_id}", response_model=HolidayResponse)
async def update_holiday(
    holiday_id: UUID,
    body: HolidayUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> HolidayResponse:
    """Update a calendar exception."""
    holiday = await CalendarService(session).update_holiday(
        holiday_id, **body.model_dump(exclude_unset=True)
    )
    return HolidayResponse.model_validate(holiday)


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holiday(
    holiday_id: UUID,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Delete a calendar exception."""
    await CalendarService(session).delete_holiday(holiday_id)


# ------------------------------------------------------------------ profiles


@router.get("/work-week-profiles", response_model=list[WorkWeekProfileResponse])
async def list_profiles(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[WorkWeekProfileResponse]:
    """List week profiles."""
    profiles = await CalendarService(session).list_profiles()
    return [_profile_response(profile) for profile in profiles]


@router.post(
    "/work-week-profiles",
    response_model=WorkWeekProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile(
    body: WorkWeekProfileCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> WorkWeekProfileResponse:
    """Create a week profile."""
    profile = await CalendarService(session).create_profile(**body.model_dump())
    return _profile_response(profile)


@router.put("/work-week-profiles/{profile_id}", response_model=WorkWeekProfileResponse)
async def update_profile(
    profile_id: UUID,
    body: WorkWeekProfileUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> WorkWeekProfileResponse:
    """Update a week profile."""
    profile = await CalendarService(session).update_profile(
        profile_id, **body.model_dump(exclude_unset=True)
    )
    return _profile_response(profile)


@router.delete(
    "/work-week-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_profile(
    profile_id: UUID,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Delete a week profile."""
    await CalendarService(session).delete_profile(profile_id)


# ------------------------------------------------------------------ bindings


@router.get("/resource-work-profiles", response_model=list[ResourceWorkProfileResponse])
async def list_bindings(
    resource_id: UUID | None = Query(default=None),
    group_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[ResourceWorkProfileResponse]:
    """List profile bindings."""
    bindings = await CalendarService(session).list_bindings(resource_id, group_id)
    return [ResourceWorkProfileResponse.model_validate(binding) for binding in bindings]


@router.post(
    "/resource-work-profiles",
    response_model=ResourceWorkProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_binding(
    body: ResourceWorkProfileCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> ResourceWorkProfileResponse:
    """Bind a week profile to a resource or a group for a period."""
    binding = await CalendarService(session).create_binding(
        body.profile_id,
        body.valid_from,
        body.valid_until,
        resource_id=body.resource_id,
        group_id=body.group_id,
    )
    return ResourceWorkProfileResponse.model_validate(binding)


@router.delete(
    "/resource-work-profiles/{binding_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_binding(
    binding_id: UUID,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Remove a binding, returning the resource to the default profile."""
    await CalendarService(session).delete_binding(binding_id)


# ------------------------------------------------------------------- windows


@router.get(
    "/infrastructure/{resource_id}/windows",
    response_model=list[AvailabilityWindowResponse],
)
async def list_windows(
    resource_id: UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[AvailabilityWindowResponse]:
    """List availability windows. An empty list means unrestricted."""
    windows = await CalendarService(session).list_windows(resource_id)
    return [AvailabilityWindowResponse.model_validate(window) for window in windows]


@router.post(
    "/infrastructure-windows",
    response_model=AvailabilityWindowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_window(
    body: AvailabilityWindowCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> AvailabilityWindowResponse:
    """Add an availability window to an infrastructure resource."""
    window = await CalendarService(session).create_window(
        body.resource_id, body.weekday, body.start_time, body.end_time
    )
    return AvailabilityWindowResponse.model_validate(window)


@router.delete(
    "/infrastructure-windows/{window_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_window(
    window_id: UUID,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Delete an availability window."""
    await CalendarService(session).delete_window(window_id)
