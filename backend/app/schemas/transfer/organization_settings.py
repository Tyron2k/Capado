"""CSV validation schemas for organization settings rows."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Create timezone-aware defaults for omitted transfer fields."""
    return datetime.now(UTC)


class OrganizationSettingsTransfer(BaseModel):
    """Validate persisted organization_settings rows without constructing ORM entities."""

    id: UUID = Field(default_factory=uuid4)
    company_name: str = Field(default="Capado", max_length=255)
    company_subtitle: str = Field(default="", max_length=255)
    logo_url: str = Field(default="", max_length=1024)
    primary_color: str = Field(default="blue", max_length=50)
    time_zone: str = Field(default="Europe/Berlin", max_length=64)
    audit_retention_months: int = Field(default=24, ge=0, le=600)
    baseline_retention_months: int = Field(default=0, ge=0, le=600)
    digest_horizon_days: int = Field(default=90, ge=1, le=730)
    digest_critical_days: int = Field(default=14, ge=0, le=365)
    digest_warning_days: int = Field(default=45, ge=0, le=730)
    digest_max_findings: int = Field(default=100, ge=1, le=1000)
    planning_freeze_before: date | None = Field(default=None)
    scheduler_enabled: bool = Field(default=True)
    maintenance_hour: int = Field(default=2, ge=0, le=23)
    smtp_enabled: bool = Field(default=False)
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_use_tls: bool = Field(default=True)
    smtp_username: str = Field(default="", max_length=255)
    smtp_from_address: str = Field(default="", max_length=255)
    digest_recipients: str = Field(default="", max_length=2000)
    logo_data: bytes | None = Field(default=None)
    logo_mime_type: str | None = Field(default=None, max_length=100)
    singleton_key: str = Field(default="default", max_length=10)
    updated_at: datetime = Field(default_factory=_utcnow)
