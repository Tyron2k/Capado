"""Store instants as timezone-aware UTC values.

Existing technical timestamps have always represented UTC. Infrastructure
booking timestamps instead represent local wall-clock time in the deployment's
legacy time zone. The migration converts those two meanings separately.

Set CAPADO_LEGACY_BOOKING_TIME_ZONE before upgrading an existing installation
whose bookings were not made in Europe/Berlin. Ambiguous or nonexistent local
booking times are rejected rather than silently assigned an arbitrary instant.

Revision ID: 002
Revises: 001
"""

import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

# These are the timestamp columns in the consolidated baseline. Calendar DATE
# columns and recurring local TIME windows are rules, not instants, and remain
# unchanged. The two assignment columns are converted separately below.
UTC_COLUMNS: dict[str, tuple[str, ...]] = {
    "absences": ("created_at", "updated_at"),
    "assignments": ("created_at", "updated_at"),
    "audit_log": ("recorded_at",),
    "baselines": ("created_at",),
    "conflicts": ("detected_at",),
    "customers": ("created_at", "updated_at"),
    "holidays": ("created_at", "updated_at"),
    "infrastructure_availability_windows": ("created_at", "updated_at"),
    "infrastructure_resource_skills": ("created_at",),
    "infrastructure_resources": ("created_at", "updated_at"),
    "organization_settings": ("updated_at",),
    "personal_resource_skills": ("created_at",),
    "personal_resources": ("created_at", "updated_at"),
    "project_folders": ("created_at", "updated_at"),
    "projects": ("created_at", "updated_at"),
    "refresh_tokens": ("expires_at", "revoked_at", "created_at"),
    "resource_groups": ("created_at", "updated_at"),
    "resource_work_profiles": ("created_at", "updated_at"),
    "scheduled_job_runs": ("started_at", "finished_at"),
    "sites": ("created_at", "updated_at"),
    "skill_attributes": ("created_at",),
    "skills": ("created_at",),
    "users": ("created_at", "updated_at"),
    "work_package_dependencies": ("created_at", "updated_at"),
    "work_package_requirements": ("created_at",),
    "work_package_template_requirements": ("created_at",),
    "work_package_templates": ("created_at", "updated_at"),
    "work_packages": ("created_at", "updated_at", "completed_at"),
    "work_week_profiles": ("created_at", "updated_at"),
}


def _legacy_zone() -> tuple[str, ZoneInfo]:
    name = os.environ.get("CAPADO_LEGACY_BOOKING_TIME_ZONE", "Europe/Berlin")
    try:
        return name, ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid CAPADO_LEGACY_BOOKING_TIME_ZONE: {name!r}"
        ) from exc


def _is_unambiguous_local_time(value: datetime, zone: ZoneInfo) -> bool:
    """A local clock reading must map to exactly one UTC instant."""
    instants = set()
    for fold in (0, 1):
        instant = value.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == value:
            instants.add(instant)
    return len(instants) == 1


def _check_existing_bookings(zone: ZoneInfo) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, start_at, end_at FROM public.assignments "
            "WHERE start_at IS NOT NULL OR end_at IS NOT NULL"
        )
    )
    invalid = [
        str(row.id)
        for row in rows
        if any(
            value is not None and not _is_unambiguous_local_time(value, zone)
            for value in (row.start_at, row.end_at)
        )
    ]
    if invalid:
        raise RuntimeError(
            "UTC migration stopped: infrastructure bookings have ambiguous or "
            "nonexistent local times. Resolve assignment IDs: "
            + ", ".join(invalid[:10])
            + (" (and more)" if len(invalid) > 10 else "")
        )


def _to_timestamptz(table: str, column: str, zone: str) -> None:
    # Table and column names come only from the constants above; the IANA zone
    # is validated by ZoneInfo before it is included in PostgreSQL's USING SQL.
    quoted_zone = zone.replace("'", "''")
    op.alter_column(
        table,
        column,
        existing_type=sa.DateTime(timezone=False),
        type_=sa.DateTime(timezone=True),
        postgresql_using=f"{column} AT TIME ZONE '{quoted_zone}'",
        schema="public",
    )


def _history_timestamp(value: object, zone: ZoneInfo) -> object:
    """Change representation, not the instant captured by a historical record."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected an ISO timestamp")
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() is None:
        if not _is_unambiguous_local_time(timestamp, zone):
            raise ValueError("Ambiguous or nonexistent historical local timestamp")
        timestamp = timestamp.replace(tzinfo=zone)
    return timestamp.astimezone(UTC).isoformat()


def _migrate_json_history(legacy_zone: ZoneInfo) -> None:
    """Keep baseline comparisons and audit field values consistent with live rows.

    Only known timestamp fields are touched: DATE/TIME rules, arbitrary strings,
    entity IDs, actors and the recorded decisions remain unchanged.
    """
    bind = op.get_bind()
    for table_name, payload_name in (
        ("baseline_entries", "payload"),
        ("audit_log", "changes"),
    ):
        table = sa.table(
            table_name,
            sa.column("id", sa.Uuid()),
            sa.column("entity_type", sa.String()),
            sa.column(payload_name, sa.JSON()),
            schema="public",
        )
        for row in bind.execute(sa.select(table)).mappings():
            payload = dict(row[payload_name])
            zones = dict.fromkeys(
                UTC_COLUMNS.get(row["entity_type"], ()), ZoneInfo("UTC")
            )
            if row["entity_type"] == "assignments":
                zones.update(start_at=legacy_zone, end_at=legacy_zone)
            try:
                for field, zone in zones.items():
                    if field not in payload:
                        continue
                    if payload_name == "changes":
                        change = dict(payload[field])
                        for side in ("from", "to"):
                            if side in change:
                                change[side] = _history_timestamp(change[side], zone)
                        payload[field] = change
                    else:
                        payload[field] = _history_timestamp(payload[field], zone)
            except (ValueError, TypeError) as exc:
                raise RuntimeError(
                    f"UTC migration stopped: resolve historical timestamp in "
                    f"{table_name} ID {row['id']}: {exc}"
                ) from exc
            if payload != row[payload_name]:
                bind.execute(
                    table.update()
                    .where(table.c.id == row["id"])
                    .values({payload_name: payload})
                )


def upgrade() -> None:
    """Convert legacy timestamp columns and add the display zone setting."""
    legacy_name, legacy_zone = _legacy_zone()
    _check_existing_bookings(legacy_zone)
    _migrate_json_history(legacy_zone)

    for table, columns in UTC_COLUMNS.items():
        for column in columns:
            _to_timestamptz(table, column, "UTC")
    for column in ("start_at", "end_at"):
        _to_timestamptz("assignments", column, legacy_name)

    op.add_column(
        "organization_settings",
        sa.Column(
            "time_zone",
            sa.String(64),
            nullable=False,
            server_default="Europe/Berlin",
        ),
        schema="public",
    )
    op.get_bind().execute(
        sa.text("UPDATE public.organization_settings SET time_zone = :zone"),
        {"zone": legacy_name},
    )


def downgrade() -> None:
    """Refuse an unsafe conversion back to timezone-less timestamps."""
    raise RuntimeError(
        "Downgrading would lose UTC offsets for new bookings in repeated local "
        "hours, including their history. Restore a pre-upgrade backup."
    )
