"""Generic CSV database operations and transaction context; no domain policies."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Never
from uuid import UUID

from sqlalchemy import Index, insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import ColumnCollectionConstraint
from sqlmodel import SQLModel, select

from .common import ImportResult
from .csv_format import MAX_ROWS, CsvBatch, CsvEntity


def id_batches(ids: set[UUID]) -> list[list[UUID]]:
    """Keep IN queries below driver parameter limits for large CSV files."""
    ordered = list(ids)
    return [ordered[offset : offset + 500] for offset in range(0, len(ordered), 500)]


@dataclass
class ImportContext:
    """Existing and planned records shared by all validators in one transaction."""

    existing: dict[str, list[dict]]
    data: dict[str, list[dict]]
    admin_id: UUID | None = None
    complete: bool = False
    user_references: list[dict] = field(default_factory=list)
    user_aliases: dict[UUID, UUID] = field(default_factory=dict)
    batches: dict[str, CsvBatch] = field(default_factory=dict)
    merged: dict[str, dict[UUID, dict]] = field(default_factory=dict)
    affected_resources: set[UUID] = field(default_factory=set)
    refresh_all_conflicts: bool = False

    def fail(self, table: str, row: dict, fields: str, message: str) -> Never:
        """Locate a bad supplied row, or identify a related destination record."""
        for batch in self.batches.values():
            number = batch.row_numbers.get((table, row["id"]))
            if number is not None:
                raise ValueError(
                    f"{batch.area.name}.csv, row {number}, field {fields}: {message}"
                )
        raise ValueError(f"{table}, record {row['id']}, field {fields}: {message}")

    def constraint_failure(
        self, entity: CsvEntity, rows: list[dict], error: IntegrityError
    ) -> Never:
        """Identify the failed input batch/fields without exposing SQL values."""
        message = str(error.orig)
        fields: set[str] = set()
        if message.startswith(
            ("UNIQUE constraint failed:", "NOT NULL constraint failed:")
        ):
            fields.update(
                part.strip().split(".")[-1]
                for part in message.split(":", 1)[1].split(",")
            )
        match = re.search(r"Key \(([^)]+)\)=", message)
        if match:
            fields.update(part.strip().strip('"') for part in match.group(1).split(","))
        name = getattr(error.orig.__cause__, "constraint_name", None)
        if name:
            for constraint in (*entity.table.constraints, *entity.table.indexes):
                if (
                    isinstance(constraint, (ColumnCollectionConstraint, Index))
                    and constraint.name == name
                ):
                    fields.update(column.name for column in constraint.columns)
        columns = (
            "/".join(column for column in entity.columns if column in fields)
            or "record"
        )
        for batch in self.batches.values():
            positions = sorted(
                batch.row_numbers[(entity.name, row["id"])]
                for row in rows
                if (entity.name, row["id"]) in batch.row_numbers
            )
            if positions:
                location = (
                    f"row {positions[0]}"
                    if len(positions) == 1
                    else f"rows {positions[0]}-{positions[-1]}"
                )
                raise ValueError(
                    f"{batch.area.name}.csv, {location}, field {columns}: {entity.name} database constraint violated; nothing was imported."
                ) from error
        raise ValueError(
            f"{entity.name}, field {columns}: database constraint violated; nothing was imported."
        ) from error

    def track_resources(self, table: str, field: str = "resource_id") -> None:
        """Track both sides of an ID-based edit, including moved bookings."""
        supplied = self.data.get(table, [])
        ids = {row["id"] for row in supplied}
        rows = supplied + [row for row in self.existing[table] if row["id"] in ids]
        self.affected_resources.update(
            row[field] for row in rows if row.get(field) is not None
        )

    def merge(self, replace_tables: set[str]) -> None:
        """Build the final state after domain preparation, before any writes."""
        self.merged = {
            name: {row["id"]: row for row in rows}
            for name, rows in self.existing.items()
        }
        for name, rows in self.data.items():
            if name in replace_tables and rows:
                self.merged[name] = {}
            self.merged[name].update((row["id"], row) for row in rows)


@asynccontextmanager
async def export_snapshot(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Give every exporter the same read-only snapshot, after authentication."""
    async with AsyncSession(bind=session.bind) as snapshot:
        if snapshot.get_bind().dialect.name == "postgresql":
            await snapshot.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
        yield snapshot


def required_entities(
    entities: tuple[CsvEntity, ...], batches: tuple[CsvBatch, ...]
) -> tuple[CsvEntity, ...]:
    """Close explicit domain references and real foreign keys over touched tables."""
    catalogue = {entity.name: entity for entity in entities}
    required = {name for batch in batches for name in batch.area.tables}
    for batch in batches:
        for name, rows in batch.data.items():
            if rows:
                required.update(catalogue[name].validation_dependents)
    pending = list(required)
    while pending:
        entity = catalogue[pending.pop()]
        references = set(entity.reference_tables) | {
            fk.column.table.name
            for column in entity.table.columns
            for fk in column.foreign_keys
        }
        pending.extend(references - required)
        required.update(references)
    return tuple(entity for entity in entities if entity.name in required)


async def _lock_destination(
    session: AsyncSession, entities: tuple[CsvEntity, ...] | None = None
) -> None:
    """Finish ongoing maintenance, then exclude concurrent destination writes."""
    if session.get_bind().dialect.name == "postgresql":
        from app.services.scheduler import lock_maintenance_for_migration

        tables = (
            {entity.name for entity in entities}
            if entities is not None
            else set(SQLModel.metadata.tables)
        )
        if entities is None or tables & {
            "audit_log",
            "baselines",
            "baseline_entries",
            "organization_settings",
        }:
            await lock_maintenance_for_migration(session)
        names = ", ".join('"' + name + '"' for name in sorted(tables))
        await session.execute(text(f"LOCK TABLE {names} IN SHARE ROW EXCLUSIVE MODE"))


async def load_data(
    session: AsyncSession,
    entities: tuple[CsvEntity, ...],
    *,
    max_rows: int | None = MAX_ROWS,
    record_ids: dict[str, set[UUID]] | None = None,
) -> dict[str, list[dict]]:
    """Read allowlisted values, bounded and ordered for reproducible downloads."""
    data: dict[str, list[dict]] = {}
    count = 0
    for entity in entities:
        ids = (record_ids or {}).get(entity.name)
        chunks = [None] if ids is None else id_batches(ids)
        records: list[dict] = []
        for chunk in chunks:
            statement = select(
                *(entity.table.c[field] for field in entity.columns)
            ).order_by(entity.table.c["id"])
            if chunk is not None:
                statement = statement.where(entity.table.c["id"].in_(chunk))
            if max_rows is not None:
                statement = statement.limit(max_rows + 1)
            rows = (await session.execute(statement)).mappings().all()
            count += len(rows)
            if max_rows is not None and count > max_rows:
                raise ValueError("CSV export/import exceeds the 200,000 row limit.")
            records.extend(dict(row) for row in rows)
        data[entity.name] = records
    return data


def _parent_order(
    rows: list[dict], *, context: ImportContext | None = None, table: str = ""
) -> list[dict]:
    """Parents before children for immediate foreign-key enforcement."""
    children: dict[UUID, list[dict]] = {}
    ready = []
    for row in rows:
        if row["parent_id"] is None:
            ready.append(row)
        else:
            children.setdefault(row["parent_id"], []).append(row)
    result = []
    while ready:
        row = ready.pop()
        result.append(row)
        ready.extend(children.get(row["id"], []))
    if len(result) != len(rows):
        if context is not None:
            visited = {row["id"] for row in result}
            row = next(row for row in rows if row["id"] not in visited)
            context.fail(table, row, "parent_id", "Cyclic hierarchy.")
        raise ValueError("Cyclic hierarchy.")
    return result


async def _insert_records(
    session: AsyncSession,
    entity: CsvEntity,
    records: list[dict],
    context: ImportContext | None = None,
) -> int:
    """Insert bounded batches, retaining the caller's parent-before-child order."""
    for offset in range(0, len(records), 500):
        batch = records[offset : offset + 500]
        try:
            await session.execute(insert(entity.table), batch)
        except IntegrityError as exc:
            if context is not None:
                context.constraint_failure(entity, batch, exc)
            raise
    return len(records)


def validate_references(
    entities: tuple[CsvEntity, ...], context: ImportContext
) -> None:
    """Check duplicate IDs and real foreign keys against the complete final state."""
    for entity in entities:
        rows = context.data.get(entity.name, [])
        if len(rows) != len({row["id"] for row in rows}):
            context.fail(entity.name, rows[-1], "id", "duplicate IDs.")
        for row in context.merged[entity.name].values():
            for column in entity.table.columns:
                for foreign_key in column.foreign_keys:
                    value = row.get(column.name)
                    if (
                        value is not None
                        and value not in context.merged[foreign_key.column.table.name]
                    ):
                        context.fail(
                            entity.name, row, column.name, "unknown reference."
                        )


def validate_ranges(
    rows: list[dict], *, context: ImportContext | None = None, table: str = ""
) -> None:
    """Check standard date and validity intervals without knowing their domain."""
    for row in rows:
        for start, end in (("start_date", "end_date"), ("valid_from", "valid_until")):
            if (
                row.get(start) is not None
                and row.get(end) is not None
                and row[end] < row[start]
            ):
                message = f"Invalid {start}/{end} range."
                if context is not None:
                    context.fail(table, row, end, message)
                raise ValueError(message)


def validate_single_flag(
    rows: list[dict], flag: str, table: str, *, context: ImportContext | None = None
) -> None:
    """Ensure an explicitly chosen flag has at most one selected record."""
    if sum(row[flag] for row in rows) > 1:
        message = f"{table}: multiple {flag} records."
        if context is not None:
            supplied = {row["id"] for row in context.data.get(table, [])}
            row = next(
                (row for row in rows if row[flag] and row["id"] in supplied),
                next(row for row in rows if row[flag]),
            )
            context.fail(table, row, flag, message)
        raise ValueError(message)


async def write_records(
    session: AsyncSession,
    entity: CsvEntity,
    records: list[dict],
    existing: list[dict],
    *,
    hierarchical: bool = False,
    replace: bool = False,
    context: ImportContext | None = None,
) -> ImportResult:
    """Apply approved rows by ID without committing or changing their fields."""
    result = ImportResult()
    if hierarchical:
        supplied = {row["id"] for row in records}
        ordered = _parent_order(
            [
                {
                    **row,
                    "parent_id": row["parent_id"]
                    if row["parent_id"] in supplied
                    else None,
                }
                for row in records
            ]
        )
        by_id = {row["id"]: row for row in records}
        records = [by_id[row["id"]] for row in ordered]
    current_ids = {row["id"] for row in existing}
    if replace and records:
        await session.execute(entity.table.delete())
        current_ids = set()
    additions: list[dict] = []
    for row in records:
        if row["id"] in current_ids:
            result.created += await _insert_records(session, entity, additions, context)
            additions = []
            try:
                await session.execute(
                    entity.table.update()
                    .where(entity.table.c["id"] == row["id"])
                    .values(**row)
                )
            except IntegrityError as exc:
                if context is not None:
                    context.constraint_failure(entity, [row], exc)
                raise
            result.updated += 1
        else:
            additions.append(row)
    result.created += await _insert_records(session, entity, additions, context)
    return result


async def write_area(
    session: AsyncSession,
    entities: tuple[CsvEntity, ...],
    data: dict[str, list[dict]],
    context: ImportContext,
    *,
    hierarchical: tuple[str, ...] = (),
) -> ImportResult:
    """Share ordinary per-table mechanics; special field policies stay in domains."""
    result = ImportResult()
    for entity in entities:
        partial = await write_records(
            session,
            entity,
            data[entity.name],
            context.existing[entity.name],
            hierarchical=entity.name in hierarchical,
            context=context,
        )
        result.created += partial.created
        result.updated += partial.updated
    return result
