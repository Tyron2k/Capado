"""Service layer for tenant-wide settings (branding + logo storage)."""

from datetime import UTC, date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.sql.base import ExecutableOption
from sqlmodel import select

from app.models.organization_settings import OrganizationSettings


async def _get_or_create_settings(
    session: AsyncSession, *options: ExecutableOption
) -> OrganizationSettings:
    """Retrieve the singleton settings row, creating it on first access.

    The row is guarded by a unique constraint on ``singleton_key``. On a
    fresh database two concurrent callers may both attempt to insert the
    default row; the constraint lets the database reject the loser, and we
    recover by rolling back and re-selecting the winner's row.

    Args:
        session: Active async database session.
        *options: Optional loader options (e.g. ``defer`` for logo_data).

    Returns:
        The singleton OrganizationSettings instance.
    """
    stmt = select(OrganizationSettings).limit(1)
    if options:
        stmt = stmt.options(*options)

    settings = (await session.execute(stmt)).scalars().first()
    if settings is not None:
        return settings

    settings = OrganizationSettings()
    session.add(settings)
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent request created the row first. Recover its version.
        await session.rollback()
        settings = (await session.execute(stmt)).scalars().first()
        if settings is None:  # pragma: no cover - constraint guarantees a row
            raise
        return settings

    await session.refresh(settings)
    return settings


async def get_organization_settings(session: AsyncSession) -> OrganizationSettings:
    """Retrieve the singleton tenant settings row (without the logo blob).

    Defers the logo_data column so the potentially 2 MB blob is not loaded
    on every settings read. Callers must not read ``logo_data`` on the
    returned instance (doing so would trigger a lazy load, which fails under
    async). Use ``get_organization_settings_with_logo`` when the blob is needed.

    If no row exists (fresh DB), creates one with defaults.

    Args:
        session: Active async database session.

    Returns:
        The OrganizationSettings instance (logo_data not loaded).
    """
    return await _get_or_create_settings(session, defer(OrganizationSettings.logo_data))


async def get_organization_settings_with_logo(
    session: AsyncSession,
) -> OrganizationSettings:
    """Retrieve the singleton tenant settings row including the logo blob.

    Loads logo_data eagerly for serving the logo binary.

    Args:
        session: Active async database session.

    Returns:
        The OrganizationSettings instance with logo_data loaded.
    """
    return await _get_or_create_settings(session)


async def update_organization_settings(
    session: AsyncSession,
    *,
    company_name: str | None = None,
    company_subtitle: str | None = None,
    logo_url: str | None = None,
    primary_color: str | None = None,
    audit_retention_months: int | None = None,
    baseline_retention_months: int | None = None,
    digest_horizon_days: int | None = None,
    digest_critical_days: int | None = None,
    digest_warning_days: int | None = None,
    digest_max_findings: int | None = None,
    planning_freeze_before: date | None = None,
    set_planning_freeze: bool = False,
    scheduler_enabled: bool | None = None,
    maintenance_hour: int | None = None,
    smtp_enabled: bool | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_use_tls: bool | None = None,
    smtp_username: str | None = None,
    smtp_password: str | None = None,
    set_smtp_password: bool = False,
    smtp_from_address: str | None = None,
    digest_recipients: str | None = None,
) -> OrganizationSettings:
    """Update the tenant settings with the provided values.

    Only non-None fields are updated. The updated_at timestamp is refreshed.

    Args:
        session: Active async database session.
        company_name: New company name (optional).
        company_subtitle: New subtitle (optional).
        logo_url: New logo URL (optional).
        primary_color: New primary color hex (optional).
        audit_retention_months: New audit retention period in whole months
            (optional). 0 disables pruning. Changing this does not delete anything
            by itself — the pruning job applies it.
        baseline_retention_months: New baseline retention period in whole months
            (optional). 0 disables pruning and is the default. Changing this does not
            delete anything by itself either.
        digest_horizon_days: How far ahead the digest looks (optional).
        digest_critical_days: Inside this many days a finding is critical (optional).
        digest_warning_days: Inside this many days a finding is a warning (optional).
        digest_max_findings: Cap on digest length (optional). The excess is counted and
            reported rather than silently dropped.
        planning_freeze_before: New freeze date, or None to LIFT the freeze. Only applied
            when set_planning_freeze is True.
        set_planning_freeze: Whether the caller mentioned the freeze at all. Needed because
            None is a meaningful VALUE here (no freeze), not "leave unchanged" — without
            this flag a freeze could never be lifted.
        scheduler_enabled: Whether the in-process maintenance loop runs (optional).
        maintenance_hour: Hour after which maintenance may run, in the process clock
            (optional).
        smtp_enabled: Whether the mail path is active (optional).
        smtp_host: Relay host (optional).
        smtp_port: Relay port (optional).
        smtp_use_tls: STARTTLS (optional).
        smtp_username: Login (optional).
        smtp_password: New password. Only applied when set_smtp_password is True; an empty
            string then CLEARS it.
        set_smtp_password: Whether the caller mentioned the password at all. Needed because the
            page cannot read it back, so "not sent" has to mean "leave alone" rather than
            "clear" — otherwise every save would wipe it.
        smtp_from_address: Sender address (optional).
        digest_recipients: Recipient list (optional).

    Returns:
        The updated OrganizationSettings instance.
    """
    settings = await get_organization_settings(session)

    if company_name is not None:
        settings.company_name = company_name
    if company_subtitle is not None:
        settings.company_subtitle = company_subtitle
    if logo_url is not None:
        settings.logo_url = logo_url
    if primary_color is not None:
        settings.primary_color = primary_color
    if audit_retention_months is not None:
        settings.audit_retention_months = audit_retention_months
    if baseline_retention_months is not None:
        settings.baseline_retention_months = baseline_retention_months
    if digest_horizon_days is not None:
        settings.digest_horizon_days = digest_horizon_days
    if digest_critical_days is not None:
        settings.digest_critical_days = digest_critical_days
    if digest_warning_days is not None:
        settings.digest_warning_days = digest_warning_days
    if digest_max_findings is not None:
        settings.digest_max_findings = digest_max_findings
    if set_planning_freeze:
        settings.planning_freeze_before = planning_freeze_before
    if scheduler_enabled is not None:
        settings.scheduler_enabled = scheduler_enabled
    if maintenance_hour is not None:
        settings.maintenance_hour = maintenance_hour
    if smtp_enabled is not None:
        settings.smtp_enabled = smtp_enabled
    if smtp_host is not None:
        settings.smtp_host = smtp_host
    if smtp_port is not None:
        settings.smtp_port = smtp_port
    if smtp_use_tls is not None:
        settings.smtp_use_tls = smtp_use_tls
    if smtp_username is not None:
        settings.smtp_username = smtp_username
    if set_smtp_password and smtp_password is not None:
        settings.smtp_password = smtp_password
    if smtp_from_address is not None:
        settings.smtp_from_address = smtp_from_address
    if digest_recipients is not None:
        settings.digest_recipients = digest_recipients

    settings.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


async def save_logo(
    session: AsyncSession, *, data: bytes, mime_type: str
) -> OrganizationSettings:
    """Store an uploaded logo image in the database.

    Replaces any previously stored logo.

    Args:
        session: Active async database session.
        data: Raw binary content of the image file.
        mime_type: MIME type of the image (e.g. "image/png").

    Returns:
        The updated OrganizationSettings instance.
    """
    settings = await get_organization_settings(session)
    settings.logo_data = data
    settings.logo_mime_type = mime_type
    settings.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


async def delete_logo(session: AsyncSession) -> OrganizationSettings:
    """Remove the stored logo from the database.

    Args:
        session: Active async database session.

    Returns:
        The updated OrganizationSettings instance (with logo fields set to None).
    """
    settings = await get_organization_settings(session)
    settings.logo_data = None
    settings.logo_mime_type = None
    settings.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings
