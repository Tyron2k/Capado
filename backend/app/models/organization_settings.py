"""SQLAlchemy entity for organization-wide application settings (branding).

Renamed from ``TenantSettings`` per ADR-003: this deployment serves exactly
one organization, and the old name implied a multi-tenancy model the project
has deliberately rejected.
"""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ORMModel
from app.utils.utc_datetime import UTCDateTime


def _utcnow() -> datetime:
    """Current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class OrganizationSettings(ORMModel, kw_only=True, eq=False):
    """Single-row table holding organization-wide branding settings.

    Enforced as a singleton via a unique constraint on ``singleton_key``
    (always 'default'). The service layer creates the row on first access
    if it doesn't exist.

    Attributes:
        company_name: Name displayed in the header.
        company_subtitle: Optional subtitle below the company name.
        logo_url: External URL to a logo image (fallback if no file uploaded).
        primary_color: Hex color string for the UI accent color.
        audit_retention_months: How many whole months of audit history to keep.
            Deleting older entries requires something to RUN the pruning (see
            app/scripts/prune_audit_log.py); the setting alone deletes nothing.
            0 disables pruning and keeps everything — a deliberate choice rather
            than a default, since the audit log is otherwise the one table from
            which nothing is ever removed.
        baseline_retention_months: How many whole months of plan baselines to keep.
            0 disables pruning and is the DEFAULT, deliberately unlike the audit log:
            a baseline is a record somebody chose to create, so losing it by omission
            would be worse than keeping it. The baseline marked is_current is never
            deleted regardless of age.
        digest_horizon_days: How far ahead the digest looks. A finding beyond this is
            true but not actionable, and reporting it trains people to skim.
        digest_critical_days: Inside this, a finding is critical — too close to solve by
            rescheduling. Anything already overdue is critical regardless.
        digest_warning_days: Inside this, a warning; beyond it, informational.
        digest_max_findings: Cap on the digest length. The excess is counted and
            reported, never silently dropped.
        planning_freeze_before: First day that may still be edited, or NULL for no
            freeze. Changes touching an earlier date are refused for non-admins. Both the
            state before and after a change are tested, so a booking cannot be dragged out
            of the frozen period either — see app/services/planning_freeze.py.
        scheduler_enabled: Whether the in-process maintenance loop runs periodic conflict
            reconciliation and the pruning jobs. Immediate checks after edits and imports
            are independent of this switch. ON by default — see the inline comment.
        maintenance_hour: Hour of day (0-23) after which maintenance jobs may run, in the
            process clock. A missed day is made up ONCE on return, not once per missed day.
        smtp_enabled: Whether the mail path is active. OFF by default.
        smtp_host: Relay host name. Empty means unconfigured.
        smtp_port: Relay port, 587 by default (STARTTLS).
        smtp_use_tls: STARTTLS rather than implicit TLS. Internal relays overwhelmingly speak
            the former; an operator whose relay wants 465 changes both fields together.
        smtp_username: Login, empty for a relay that authenticates by IP.
        smtp_password: Login password. NEVER returned by the API.
        smtp_from_address: Sender address the digest is sent from.
        digest_recipients: Comma-, semicolon- or newline-separated recipient list. A separate
            table would be tidier and is not worth it for configuration nobody queries.
        logo_data: Binary content of an uploaded logo image (max 2 MB).
            Read paths defer this column (see settings_service) to avoid
            fetching up to 2 MB on every settings read.
        logo_mime_type: MIME type of the uploaded logo (e.g. "image/png").
        singleton_key: Fixed value 'default' with a unique constraint to
            guarantee only one row exists.
    """

    __tablename__ = "organization_settings"
    __table_args__ = (
        UniqueConstraint("singleton_key", name="uq_organization_settings_singleton"),
    )

    id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    company_name: Mapped[str] = mapped_column(
        sa.String(255), nullable=False, default="Capado"
    )
    company_subtitle: Mapped[str] = mapped_column(
        sa.String(255), nullable=False, default=""
    )
    logo_url: Mapped[str] = mapped_column(sa.String(1024), nullable=False, default="")
    primary_color: Mapped[str] = mapped_column(
        sa.String(50), nullable=False, default="blue"
    )
    # Organization-wide IANA zone for displayed and entered timestamps. The
    # historic availability calendars remain Europe/Berlin local-clock rules.
    # Instants in the database are stored in UTC independently of this setting.
    time_zone: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, default="Europe/Berlin"
    )
    # 24 months as the default: long enough to settle a dispute about who promised
    # what, short enough not to accumulate behavioural data indefinitely. Capped at
    # 600 to keep "effectively forever" expressed as 0 rather than as a huge number.
    audit_retention_months: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=24
    )
    # DISABLED by default, unlike the audit log. An audit entry accumulates as a side
    # effect of working; a baseline is something somebody deliberately froze because
    # that state mattered. Losing the state a commitment was measured against by
    # omission would be worse than keeping it (see baseline_retention).
    baseline_retention_months: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=0
    )
    # Digest thresholds. Configurable because the right numbers depend on the operation:
    # a rail workshop planning in quarters and a job shop planning in days do not want the
    # same horizon, and hard-coding either would make the digest useless for the other.
    digest_horizon_days: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=90
    )
    digest_critical_days: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=14
    )
    digest_warning_days: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=45
    )
    # A digest nobody finishes reading is a digest nobody reads. The excess is reported as
    # a count rather than silently dropped.
    digest_max_findings: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=100
    )
    # First still-editable day. NULL means no freeze. EXCLUSIVE by name and by behaviour:
    # "before" rather than "until", because "until" reads inclusive to most people and an
    # off-by-one in a permission check surfaces as an argument, not as an error.
    planning_freeze_before: Mapped[date | None] = mapped_column(
        sa.Date(), nullable=True, default=None
    )
    # ON by default, unlike most new behaviour here. The setting it makes real (audit
    # retention) is already configured and already promised in the compliance document;
    # leaving the scheduler off by default would preserve the exact discrepancy being fixed.
    scheduler_enabled: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, default=True
    )
    # Hour after which maintenance may run, in the PROCESS clock — normally UTC in a
    # container. No timezone setting pretends otherwise; an operator wanting 02:00 local has
    # to account for the offset.
    maintenance_hour: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=2
    )
    # Mail path for pushing the digest. OFF by default: a configuration that starts sending the
    # moment it is saved would send a first digest to whatever is in the recipient field.
    smtp_enabled: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, default=False
    )
    smtp_host: Mapped[str] = mapped_column(sa.String(255), nullable=False, default="")
    smtp_port: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=587)
    smtp_use_tls: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, default=True
    )
    smtp_username: Mapped[str] = mapped_column(
        sa.String(255), nullable=False, default=""
    )
    # NEVER returned by the API — the read schema exposes a boolean instead. Stored in plaintext
    # as a documented decision, see migration 024 for the alternatives that were rejected.
    smtp_password: Mapped[str] = mapped_column(
        sa.String(512), nullable=False, default=""
    )
    smtp_from_address: Mapped[str] = mapped_column(
        sa.String(255), nullable=False, default=""
    )
    digest_recipients: Mapped[str] = mapped_column(
        sa.String(2000), nullable=False, default=""
    )
    logo_data: Mapped[bytes | None] = mapped_column(
        sa.LargeBinary, nullable=True, default=None
    )
    logo_mime_type: Mapped[str | None] = mapped_column(
        sa.String(100), nullable=True, default=None
    )
    singleton_key: Mapped[str] = mapped_column(
        sa.String(10), nullable=False, default="default"
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default_factory=_utcnow, insert_default=_utcnow
    )
