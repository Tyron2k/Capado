"""Pydantic request/response schemas for tenant settings."""

from datetime import date

from pydantic import BaseModel, Field


class OrganizationSettingsResponse(BaseModel):
    """Response shape for tenant branding settings (GET /api/settings).

    Includes a boolean indicating whether an uploaded logo exists in the DB,
    so the frontend can decide which logo source to use without an extra request.
    """

    company_name: str
    company_subtitle: str
    logo_url: str
    primary_color: str
    has_uploaded_logo: bool
    # Exposed on read so an admin can see the current period without guessing, and
    # so the value is visible to anyone auditing the deployment.
    audit_retention_months: int
    digest_horizon_days: int
    digest_critical_days: int
    digest_warning_days: int
    digest_max_findings: int
    planning_freeze_before: date | None = None
    scheduler_enabled: bool
    maintenance_hour: int
    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    smtp_username: str
    # The password itself is deliberately absent. A settings page that renders it into the DOM
    # leaks it to anybody looking over a shoulder, which is a realistic threat — unlike database
    # exfiltration, where a relay password is the least of the losses.
    smtp_password_set: bool = False
    smtp_from_address: str
    digest_recipients: str
    mail_config_errors: list[str] = []
    baseline_retention_months: int

    model_config = {"from_attributes": True}


class OrganizationSettingsUpdate(BaseModel):
    """Request body for updating tenant settings (PUT /api/settings).

    All fields are optional — only provided fields are updated.
    """

    company_name: str | None = Field(default=None, max_length=255)
    company_subtitle: str | None = Field(default=None, max_length=255)
    logo_url: str | None = Field(default=None, max_length=1024)
    primary_color: str | None = Field(default=None, max_length=50)
    # 0 disables pruning entirely. Kept as an explicit value rather than null so
    # that "keep forever" is something an admin chooses, not something that happens
    # by omission.
    audit_retention_months: int | None = Field(default=None, ge=0, le=600)
    digest_horizon_days: int | None = Field(default=None, ge=1, le=730)
    digest_critical_days: int | None = Field(default=None, ge=0, le=365)
    digest_warning_days: int | None = Field(default=None, ge=0, le=730)
    digest_max_findings: int | None = Field(default=None, ge=1, le=1000)
    # Sent explicitly as null to LIFT the freeze, so this cannot use the "None means
    # unchanged" convention the other fields use. model_fields_set carries the difference.
    planning_freeze_before: date | None = None
    # 0 disables pruning and is the default for baselines, deliberately unlike the
    # audit log: a baseline is a record somebody chose to create.
    baseline_retention_months: int | None = Field(default=None, ge=0, le=600)
    scheduler_enabled: bool | None = None
    # In the PROCESS clock, normally UTC in a container. No timezone setting pretends
    # otherwise, so an operator wanting 02:00 local has to account for the offset.
    maintenance_hour: int | None = Field(default=None, ge=0, le=23)
    smtp_enabled: bool | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_use_tls: bool | None = None
    smtp_username: str | None = Field(default=None, max_length=255)
    # Omitted leaves the stored password untouched; an empty string CLEARS it. Without that
    # distinction a settings page that cannot read the password back could never save without
    # wiping it.
    smtp_password: str | None = Field(default=None, max_length=512)
    smtp_from_address: str | None = Field(default=None, max_length=255)
    digest_recipients: str | None = Field(default=None, max_length=2000)
