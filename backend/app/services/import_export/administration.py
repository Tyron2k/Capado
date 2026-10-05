"""Complete CSV export and import of administration data."""

from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m

from .common import ImportResult
from .csv_format import CsvArea, CsvBatch, dump_area, entity, parse_area_rows
from .csv_storage import (
    ImportContext,
    load_data,
    write_records,
)

CSV_AREA = CsvArea(
    "administration",
    (
        entity(
            m.User,
            "id email name role scope_group_ids scope_project_ids is_active resource_id created_at updated_at",
            json_columns=("scope_group_ids", "scope_project_ids"),
            defaults={"password_hash": ""},
            reference_tables=("resource_groups", "projects"),
        ),
        entity(
            m.OrganizationSettings,
            "id company_name company_subtitle logo_url primary_color time_zone audit_retention_months baseline_retention_months digest_horizon_days digest_critical_days digest_warning_days digest_max_findings planning_freeze_before scheduler_enabled maintenance_hour smtp_enabled smtp_host smtp_port smtp_use_tls smtp_username smtp_from_address digest_recipients logo_data logo_mime_type singleton_key updated_at",
            binary_columns=("logo_data",),
        ),
    ),
)


async def load_export(session: AsyncSession) -> dict[str, list[dict]]:
    """Read public account/configuration fields and normalize database scope arrays."""
    data = await load_data(session, CSV_AREA.entities)
    normalize_scopes(data["users"])
    return data


def export_csv(data: dict[str, list[dict]]) -> bytes:
    """Produce the complete area CSV used by both downloads and ZIP exports."""
    return dump_area(CSV_AREA, data)


def parse_csv(rows: list[tuple] | list[list[str]]) -> CsvBatch:
    """Decode and check the versioned CSV belonging to this domain."""
    return parse_area_rows(CSV_AREA, rows)


def validate_import(context: ImportContext) -> None:
    """Check account scopes, roles, singleton configuration and logo limits."""
    by_id = context.merged
    for row in by_id["users"].values():
        if row["role"] not in {"admin", "editor", "viewer"}:
            context.fail("users", row, "role", "Invalid user role.")
        for column, table in (
            ("scope_group_ids", "resource_groups"),
            ("scope_project_ids", "projects"),
        ):
            if any(value not in by_id[table] for value in row[column] or []):
                context.fail("users", row, column, f"Unknown user {column} reference.")
    settings = list(by_id["organization_settings"].values())
    if len(settings) > 1:
        raise ValueError("Multiple organization settings records.")
    for row in settings:
        try:
            ZoneInfo(row["time_zone"])
        except (ZoneInfoNotFoundError, ValueError):
            context.fail(
                "organization_settings", row, "time_zone", "Unknown display time zone."
            )
        if row["singleton_key"] != "default" or (
            row["logo_data"] is not None and len(row["logo_data"]) > 2 * 1024 * 1024
        ):
            context.fail(
                "organization_settings",
                row,
                "singleton_key/logo_data",
                "Invalid singleton settings or oversized logo.",
            )
        if row["logo_data"] and row["logo_mime_type"] not in {
            "image/png",
            "image/jpeg",
            "image/svg+xml",
            "image/webp",
            "image/gif",
        }:
            context.fail(
                "organization_settings",
                row,
                "logo_mime_type",
                "Invalid logo media type.",
            )


async def write_import(
    session: AsyncSession, batch: CsvBatch, context: ImportContext
) -> ImportResult:
    """Apply public fields while retaining destination credentials and disabling jobs/mail."""
    result = ImportResult()
    old_settings = context.existing["organization_settings"]
    old_zone = old_settings[0]["time_zone"] if old_settings else "Europe/Berlin"
    if any(row["time_zone"] != old_zone for row in batch.data["organization_settings"]):
        context.refresh_all_conflicts = True
    for schema in CSV_AREA.entities:
        current_ids = {row["id"] for row in context.existing[schema.name]}
        records = []
        for record in batch.data[schema.name]:
            row = dict(record)
            if schema.name == "users" and row["id"] not in current_ids:
                row.update(
                    password_hash="", must_change_password=True, external_id=None
                )
            if schema.name == "organization_settings":
                row.update(
                    smtp_password="", smtp_enabled=False, scheduler_enabled=False
                )
            records.append(row)
        partial = await write_records(
            session,
            schema,
            records,
            context.existing[schema.name],
            replace=schema.name in REPLACE_TABLES,
            context=context,
        )
        result.created += partial.created
        result.updated += partial.updated
    return result


# Setup settings are replaced as a singleton; other records are ordinary upserts.
REPLACE_TABLES = {"organization_settings"}


def normalize_scopes(users: list[dict]) -> None:
    """Normalize SQLite JSON and PostgreSQL UUID arrays before comparing references."""
    for row in users:
        for column in ("scope_group_ids", "scope_project_ids"):
            if row[column] is not None:
                row[column] = [UUID(str(value)) for value in row[column]]


def prepare_import(context: ImportContext) -> None:
    """Preserve the bootstrap identity and supply safe settings for an empty source."""
    if context.complete:
        if any(user["id"] != context.admin_id for user in context.existing["users"]):
            raise ValueError(
                "CSV migration requires an empty destination with only its bootstrap administrator."
            )
        if not context.data["organization_settings"]:
            settings = m.OrganizationSettings(scheduler_enabled=False).model_dump()
            context.data["organization_settings"] = [
                {key: settings[key] for key in CSV_AREA.entities[1].columns}
            ]
    if "users" not in context.data:
        return
    admin = next(
        (row for row in context.existing["users"] if row["id"] == context.admin_id),
        None,
    )
    if admin is None or admin["role"] != "admin" or not admin["is_active"]:
        raise ValueError("An active destination administrator is required.")
    mapped_user = None
    for row in context.data["users"]:
        if row["email"].lower() == admin["email"].lower() or row["id"] == admin["id"]:
            if (
                mapped_user is not None
                or row["email"].lower() != admin["email"].lower()
                or row["role"] != "admin"
                or not row["is_active"]
            ):
                context.fail(
                    "users",
                    row,
                    "id/email/role/is_active",
                    "Source user conflicts with the destination administrator.",
                )
            mapped_user = row["id"]
            row["id"] = admin["id"]
            batch = context.batches.get(CSV_AREA.name)
            if batch and ("users", mapped_user) in batch.row_numbers:
                batch.row_numbers[("users", admin["id"])] = batch.row_numbers[
                    ("users", mapped_user)
                ]
    if mapped_user is not None:
        context.user_aliases[mapped_user] = admin["id"]
    batch = context.batches.get(CSV_AREA.name)
    if batch:
        batch.data.update({name: context.data[name] for name in CSV_AREA.tables})
