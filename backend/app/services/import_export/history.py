"""Complete CSV export and import of history data."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.schemas.transfer.audit import AuditLogTransfer
from app.schemas.transfer.baseline import BaselineEntryTransfer, BaselineTransfer
from app.schemas.transfer.user import UserTransfer

from .common import ImportResult
from .csv_format import CsvArea, CsvBatch, dump_area, entity, parse_area_rows
from .csv_storage import (
    ImportContext,
    load_data,
    validate_single_flag,
    write_area,
)

CSV_AREA = CsvArea(
    "history",
    (
        entity(
            m.Baseline,
            "id name note created_by is_current created_at",
            validation_model=BaselineTransfer,
        ),
        entity(
            m.BaselineEntry,
            "id baseline_id entity_type entity_id payload",
            json_columns=("payload",),
            existing_by_id=True,
            validation_model=BaselineEntryTransfer,
        ),
        entity(
            m.AuditLog,
            "id entity_type entity_id action actor_id reason changes recorded_at",
            json_columns=("changes",),
            existing_by_id=True,
            validation_model=AuditLogTransfer,
        ),
    ),
    ("Author Email", "Actor Email"),
)


async def load_export(session: AsyncSession) -> dict[str, list[dict]]:
    """Read this area's approved data and the references needed by its exporter."""
    return await load_data(
        session,
        CSV_AREA.entities
        + (entity(m.User, "id email", validation_model=UserTransfer),),
    )


def export_csv(data: dict[str, list[dict]]) -> bytes:
    """Enrich authors with public emails and redact secrets in historical payloads."""
    emails = {row["id"]: row["email"] for row in data.get("users", [])}
    extras = {}
    for row in data["baselines"]:
        extras[("baselines", row["id"])] = {
            "Author Email": emails.get(row["created_by"], "")
        }
    for row in data["audit_log"]:
        extras[("audit_log", row["id"])] = {
            "Actor Email": emails.get(row["actor_id"], "")
        }
    sanitized = {
        name: [{key: _redact(value) for key, value in row.items()} for row in rows]
        for name, rows in data.items()
    }
    return dump_area(CSV_AREA, sanitized, extras)


def parse_csv(rows: list[tuple] | list[list[str]]) -> CsvBatch:
    """Validate public author/actor references and sanitize nested history values."""
    batch = parse_area_rows(CSV_AREA, rows)
    for number, row in enumerate(rows[2:], start=3):
        values = dict(zip(CSV_AREA.columns, row, strict=True))
        reference_column = (
            "Author Email"
            if values["Record Type"] == "baselines"
            else "Actor Email"
            if values["Record Type"] == "audit_log"
            else None
        )
        if any(
            values[column]
            for column in CSV_AREA.extra_columns
            if column != reference_column
        ):
            raise ValueError(
                f"history.csv, row {number}, field Author Email/Actor Email: values outside this record type."
            )
        id_column = "created_by" if reference_column == "Author Email" else "actor_id"
        if reference_column and values[id_column] != r"\N":
            if not values[reference_column]:
                raise ValueError(
                    f"history.csv, row {number}, field {reference_column}: user reference needs its email."
                )
            batch.user_references.append(
                {
                    "id": UUID(values[id_column]),
                    "email": values[reference_column],
                    "table": values["Record Type"],
                    "row_id": UUID(values["id"]),
                    "fields": id_column + "/" + reference_column,
                }
            )
    for records in batch.data.values():
        for record in records:
            for key, value in record.items():
                record[key] = _redact(value)
    return batch


def validate_import(context: ImportContext) -> None:
    """Allow at most one current baseline in the final state."""
    validate_single_flag(
        list(context.merged["baselines"].values()),
        "is_current",
        "baselines",
        context=context,
    )


async def write_import(
    session: AsyncSession, batch: CsvBatch, context: ImportContext
) -> ImportResult:
    """Write this area's prepared records inside the caller's transaction."""
    return await write_area(session, CSV_AREA.entities, batch.data, context)


_SECRET_KEYS = {
    "password_hash",
    "smtp_password",
    "token_hash",
    "external_id",
    "access_token",
    "refresh_token",
}


def _redact(value: Any) -> Any:
    """Remove old secret values from historical nested payloads as well."""
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: (
            dict.fromkeys(item, "<redacted>")
            if isinstance(item, dict)
            else "<redacted>"
        )
        if key in _SECRET_KEYS
        else _redact(item)
        for key, item in value.items()
    }


def _map_history_references(
    data: dict[str, list[dict]],
    references: list[dict],
    users: list[dict],
    context: ImportContext,
) -> None:
    """Resolve historical authors after a separately imported bootstrap account."""
    aliases: dict[UUID, UUID] = {}
    by_id = {user["id"]: user for user in users}
    by_email: dict[str, list[dict]] = {}
    for user in users:
        by_email.setdefault(user["email"].lower(), []).append(user)
    for reference in references:
        email = reference["email"].lower()
        matches = by_email.get(email, [])
        same_id = by_id.get(reference["id"])
        target_id = matches[0]["id"] if len(matches) == 1 else None
        if (
            target_id is None
            or (same_id and same_id["email"].lower() != email)
            or aliases.get(reference["id"], target_id) != target_id
        ):
            context.fail(
                reference["table"],
                {"id": reference["row_id"]},
                reference["fields"],
                "History references an unknown or conflicting user; import administration first.",
            )
        aliases[reference["id"]] = target_id
    for row in data.get("baselines", []):
        row["created_by"] = aliases.get(row["created_by"], row["created_by"])
    for row in data.get("audit_log", []):
        row["actor_id"] = aliases.get(row["actor_id"], row["actor_id"])
        if row["entity_type"] == "users":
            row["entity_id"] = aliases.get(row["entity_id"], row["entity_id"])


def prepare_import(context: ImportContext) -> None:
    """Apply administrator aliases, then resolve separate imports by public email."""
    aliases = context.user_aliases
    for row in context.data.get("baselines", []):
        row["created_by"] = aliases.get(row["created_by"], row["created_by"])
    for row in context.data.get("audit_log", []):
        row["actor_id"] = aliases.get(row["actor_id"], row["actor_id"])
        if row["entity_type"] == "users":
            row["entity_id"] = aliases.get(row["entity_id"], row["entity_id"])
    identities = {row["id"]: row for row in context.existing["users"]}
    identities.update((row["id"], row) for row in context.data.get("users", []))
    _map_history_references(
        context.data, context.user_references, list(identities.values()), context
    )


def validate_source_references(batches: tuple[CsvBatch, ...]) -> None:
    """Require archive history ID/email pairs to match its own exported users."""
    emails = {
        row["id"]: row["email"].lower()
        for batch in batches
        for row in batch.data.get("users", [])
    }
    for batch in batches:
        for row in batch.user_references:
            if emails.get(row["id"]) != row["email"].lower():
                number = batch.row_numbers[(row["table"], row["row_id"])]
                raise ValueError(
                    f"history.csv, row {number}, field {row['fields']}: History user ID/email mismatch."
                )


async def write_import_marker(session: AsyncSession, context: ImportContext) -> None:
    """Record the successful transfer inside its owning transaction."""
    from sqlalchemy import insert

    from app.models.base import ORMModel, column_values

    marker = m.AuditLog(
        entity_type="csv_migration" if context.complete else "csv_import",
        entity_id=context.admin_id or UUID(int=0),
        action=m.AuditAction.created,
        actor_id=context.admin_id,
        reason="CSV-Datenumzug vollständig übernommen; Zugangsdaten ausgeschlossen; E-Mail und Wartung ausgeschaltet."
        if context.complete
        else "CSV-Datenbereich vollständig geprüft und übernommen.",
    )
    await session.execute(
        insert(ORMModel.metadata.tables["audit_log"]).values(**column_values(marker))
    )
