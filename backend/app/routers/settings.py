"""Router for application settings (tenant branding + logo upload via DB)."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.schemas.settings import (
    OrganizationSettingsResponse,
    OrganizationSettingsUpdate,
)
from app.services.mail_config import MailConfig, validation_errors
from app.services.permissions import get_authenticated_user, require_admin
from app.services.settings_service import (
    delete_logo,
    get_organization_settings,
    get_organization_settings_with_logo,
    save_logo,
    update_organization_settings,
)

router = APIRouter(prefix="/settings", tags=["Settings"])


# ===========================================================================
# Helpers
# ===========================================================================


def _to_response(settings) -> OrganizationSettingsResponse:
    """Convert a OrganizationSettings model instance to the API response shape.

    Uses logo_mime_type as a proxy for logo existence to avoid loading the
    deferred logo_data blob (up to 2 MB) on every settings read.
    """
    return OrganizationSettingsResponse(
        company_name=settings.company_name,
        company_subtitle=settings.company_subtitle,
        logo_url=settings.logo_url,
        primary_color=settings.primary_color,
        time_zone=settings.time_zone,
        has_uploaded_logo=settings.logo_mime_type is not None,
        audit_retention_months=settings.audit_retention_months,
        digest_horizon_days=settings.digest_horizon_days,
        digest_critical_days=settings.digest_critical_days,
        digest_warning_days=settings.digest_warning_days,
        digest_max_findings=settings.digest_max_findings,
        planning_freeze_before=settings.planning_freeze_before,
        scheduler_enabled=settings.scheduler_enabled,
        maintenance_hour=settings.maintenance_hour,
        smtp_enabled=settings.smtp_enabled,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_use_tls=settings.smtp_use_tls,
        smtp_username=settings.smtp_username,
        # A boolean, never the value. The operator needs to know whether one is stored so they
        # can leave the field blank instead of retyping it.
        smtp_password_set=bool(settings.smtp_password),
        smtp_from_address=settings.smtp_from_address,
        digest_recipients=settings.digest_recipients,
        # Reported on READ, not only on save: a configuration that was valid when saved can
        # become incomplete when a recipient is removed elsewhere, and the operator should see
        # that on the page rather than discover it from a digest that never arrived.
        mail_config_errors=validation_errors(
            MailConfig(
                enabled=settings.smtp_enabled,
                host=settings.smtp_host,
                port=settings.smtp_port,
                use_tls=settings.smtp_use_tls,
                username=settings.smtp_username,
                password=settings.smtp_password,
                from_address=settings.smtp_from_address,
                recipients_raw=settings.digest_recipients,
            )
        ),
        baseline_retention_months=settings.baseline_retention_months,
    )


# ===========================================================================
# Tenant settings (branding): GET / PUT
# ===========================================================================


@router.get(
    "",
    summary="Get tenant branding settings",
    response_model=OrganizationSettingsResponse,
)
async def get_settings(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_authenticated_user),
) -> OrganizationSettingsResponse:
    """Return tenant-wide branding settings (company name, color, logo URL).

    Available to all authenticated users, including those who still must
    change their password, so branding renders correctly on first login
    (reading branding is harmless and read-only).

    Args:
        session: Database session.
        current_user: The authenticated user.

    Returns:
        Current tenant branding settings including has_uploaded_logo flag.
    """
    settings = await get_organization_settings(session)
    return _to_response(settings)


@router.put(
    "",
    summary="Update tenant branding settings",
    response_model=OrganizationSettingsResponse,
)
async def put_settings(
    body: OrganizationSettingsUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> OrganizationSettingsResponse:
    """Update tenant-wide branding settings. Admin only.

    Only fields present in the request body are updated.

    Args:
        body: Partial update payload.
        session: Database session.
        current_user: The authenticated admin user (enforced by require_admin).

    Returns:
        Updated tenant branding settings.

    Raises:
        HTTPException 403: If the user is not an admin.
    """
    settings = await update_organization_settings(
        session,
        company_name=body.company_name,
        company_subtitle=body.company_subtitle,
        logo_url=body.logo_url,
        primary_color=body.primary_color,
        time_zone=body.time_zone,
        audit_retention_months=body.audit_retention_months,
        digest_horizon_days=body.digest_horizon_days,
        digest_critical_days=body.digest_critical_days,
        digest_warning_days=body.digest_warning_days,
        digest_max_findings=body.digest_max_findings,
        planning_freeze_before=body.planning_freeze_before,
        # An explicit null lifts the freeze, so the router has to say whether the field
        # was mentioned at all rather than letting None mean "unchanged".
        set_planning_freeze="planning_freeze_before" in body.model_fields_set,
        scheduler_enabled=body.scheduler_enabled,
        maintenance_hour=body.maintenance_hour,
        smtp_enabled=body.smtp_enabled,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
        smtp_use_tls=body.smtp_use_tls,
        smtp_username=body.smtp_username,
        smtp_password=body.smtp_password,
        # Omitted leaves the stored password alone; an explicit empty string clears it. The page
        # cannot read the password back, so without this it could never save without wiping it.
        set_smtp_password="smtp_password" in body.model_fields_set,
        smtp_from_address=body.smtp_from_address,
        digest_recipients=body.digest_recipients,
        baseline_retention_months=body.baseline_retention_months,
    )
    return _to_response(settings)


# ===========================================================================
# Logo: POST / GET / DELETE (stored as binary in organization_settings row)
# ===========================================================================

# Accepted MIME types for logo images.
ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/svg+xml",
    "image/webp",
    "image/gif",
}

# Maximum file size: 2 MB.
MAX_LOGO_SIZE = 2 * 1024 * 1024


@router.post(
    "/logo",
    summary="Upload a company logo",
    description="Accepts PNG, JPEG, SVG, WebP, or GIF. Max 2 MB. Stored in the database.",
    status_code=204,
)
async def upload_logo(
    file: UploadFile = File(
        ..., description="Logo image file (PNG, JPEG, SVG, WebP, GIF)"
    ),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> None:
    """Upload a company logo image and store it in the database.

    Validates MIME type and file size. Only one logo is kept — uploading
    replaces the previous one.

    Args:
        file: The uploaded image file.
        session: Database session.
        current_user: The authenticated admin user (enforced by require_admin).

    Raises:
        HTTPException 403: If the user is not an admin.
        HTTPException 400: If the file type is not allowed or exceeds size limit.
    """
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. "
            f"Allowed: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
        )

    content = await file.read()
    if len(content) > MAX_LOGO_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(content)} bytes). Maximum is {MAX_LOGO_SIZE} bytes (2 MB).",
        )

    await save_logo(session, data=content, mime_type=file.content_type)


@router.get(
    "/logo",
    summary="Get the uploaded company logo",
    description="Returns the uploaded logo from the database, or 404 if none exists.",
)
async def get_logo(
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Serve the currently uploaded company logo from the database.

    No authentication required so browsers can load it as an image src.
    Uses get_organization_settings_with_logo to explicitly load the deferred blob.

    Returns:
        The logo image bytes with appropriate content type.

    Raises:
        HTTPException 404: If no logo has been uploaded.
    """
    settings = await get_organization_settings_with_logo(session)

    if settings.logo_data is None or settings.logo_mime_type is None:
        raise HTTPException(status_code=404, detail="No logo uploaded.")

    return Response(
        content=settings.logo_data,
        media_type=settings.logo_mime_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.delete(
    "/logo",
    summary="Delete the uploaded company logo",
    status_code=204,
)
async def remove_logo(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> None:
    """Remove the uploaded logo from the database.

    Args:
        session: Database session.
        current_user: The authenticated admin user (enforced by require_admin).

    Raises:
        HTTPException 403: If the user is not an admin.
    """
    await delete_logo(session)
