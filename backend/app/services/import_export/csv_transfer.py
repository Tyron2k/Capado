"""Coordinate complete domain CSVs, a consistent ZIP snapshot and atomic imports.

Domain modules own fields and business rules. This service owns the archive
envelope, import ordering and the single transaction used by all participants.
"""

import asyncio
import csv
import hashlib
import io
from uuid import UUID
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import AREAS, CSV_DOMAINS, DOMAIN_BY_NAME, ENTITIES, administration, history
from .common import ImportResult, check_import_conflicts
from .csv_format import (
    _CSV_VERSION,
    MAX_EXPANDED_BYTES,
    MAX_ROWS,
    CsvBatch,
    CsvEntity,
    _csv_bytes,
    _read_csv,
)
from .csv_storage import (
    ImportContext,
    _lock_destination,
    export_snapshot,
    load_data,
    required_entities,
    validate_references,
)

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_MANIFEST = ("Format", "Version", "File", "Rows", "SHA256")
_BOOTSTRAP_TABLES = {"users", "organization_settings", "audit_log"}


async def export_area(session: AsyncSession, name: str) -> bytes:
    """Run the dedicated exporter inside its own consistent source snapshot."""
    domain = DOMAIN_BY_NAME[name]
    async with export_snapshot(session) as snapshot:
        data = await domain.load_export(snapshot)
        return await asyncio.to_thread(domain.export_csv, data)


async def export_migration(session: AsyncSession) -> bytes:
    """Call all dedicated exporters within one shared database snapshot."""
    files = {}
    expanded = 0
    async with export_snapshot(session) as snapshot:
        for domain in CSV_DOMAINS:
            data = await domain.load_export(snapshot)
            files[domain.CSV_AREA.name + ".csv"] = await asyncio.to_thread(
                domain.export_csv, data
            )
            expanded += len(files[domain.CSV_AREA.name + ".csv"])
            if expanded > MAX_EXPANDED_BYTES:
                raise ValueError("CSV migration exceeds the 100 MiB expanded limit.")
    return await asyncio.to_thread(_pack_archive, files)


def _build_archive(data: dict[str, list[dict]]) -> bytes:
    """Bundle supplied data through the same dedicated serializers as downloads."""
    return _pack_archive(
        {
            domain.CSV_AREA.name + ".csv": domain.export_csv(data)
            for domain in CSV_DOMAINS
        }
    )


def _pack_archive(files: dict[str, bytes]) -> bytes:
    """Add bounded CSV files and their manifest, without changing their bytes."""
    output = io.BytesIO()
    manifest = []
    expanded = count = 0
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            expanded += len(content)
            rows = len(_read_csv(content)) - 2
            count += rows
            if expanded > MAX_EXPANDED_BYTES:
                raise ValueError("CSV migration exceeds the 100 MiB expanded limit.")
            if count > MAX_ROWS:
                raise ValueError("CSV migration exceeds the 200,000 row limit.")
            archive.writestr(filename, content)
            manifest.append(
                dict(
                    zip(
                        _MANIFEST,
                        (
                            "capado-csv-migration",
                            _CSV_VERSION,
                            filename,
                            rows,
                            hashlib.sha256(content).hexdigest(),
                        ),
                        strict=True,
                    )
                )
            )
        manifest_content = _csv_bytes(_MANIFEST, manifest)
        if expanded + len(manifest_content) > MAX_EXPANDED_BYTES:
            raise ValueError("CSV migration exceeds the 100 MiB expanded limit.")
        archive.writestr("manifest.csv", manifest_content)
    if output.tell() > MAX_ARCHIVE_BYTES:
        raise ValueError("CSV migration exceeds the 50 MiB archive limit.")
    return output.getvalue()


def _parse_archive(content: bytes) -> tuple[CsvBatch, ...]:
    """Verify the ZIP envelope, then delegate every CSV to its owning importer."""
    if len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError("CSV migration exceeds the 50 MiB archive limit.")
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            expected = {area.name + ".csv" for area in AREAS} | {"manifest.csv"}
            if (
                len(members) != len(expected)
                or {item.filename for item in members} != expected
            ):
                raise ValueError(
                    "CSV migration must contain exactly manifest.csv and all area CSVs."
                )
            if sum(item.file_size for item in members) > MAX_EXPANDED_BYTES:
                raise ValueError("CSV migration exceeds the 100 MiB expanded limit.")
            files = {item.filename: archive.read(item) for item in members}
        manifest = _read_csv(files["manifest.csv"])
        if (
            not manifest
            or tuple(manifest[0]) != _MANIFEST
            or len(manifest) != len(AREAS) + 1
        ):
            raise ValueError("Invalid CSV migration manifest.")
        specs = {}
        for row in manifest[1:]:
            if len(row) != 5 or row[:2] != ["capado-csv-migration", _CSV_VERSION]:
                raise ValueError("Unsupported CSV migration format/version.")
            if row[2] in specs:
                raise ValueError("Duplicate file in CSV migration manifest.")
            specs[row[2]] = (int(row[3]), row[4])
        if set(specs) != expected - {"manifest.csv"}:
            raise ValueError("Manifest does not list every area CSV.")
        count = 0
        batches = []
        for domain in CSV_DOMAINS:
            filename = domain.CSV_AREA.name + ".csv"
            rows = _read_csv(files[filename], filename)
            if specs[filename] != (
                len(rows) - 2,
                hashlib.sha256(files[filename]).hexdigest(),
            ):
                raise ValueError(
                    f"{filename}: row count or checksum mismatch; export the package again."
                )
            count += len(rows) - 2
            if count > MAX_ROWS:
                raise ValueError("CSV migration exceeds the 200,000 row limit.")
            batches.append(domain.parse_csv(rows))
        return tuple(batches)
    except (BadZipFile, UnicodeError, csv.Error, KeyError, RuntimeError) as exc:
        raise ValueError("Invalid or unreadable CSV migration archive.") from exc


def _combine(batches: tuple[CsvBatch, ...]) -> dict[str, list[dict]]:
    """Collect rows for a shared validation context, retaining domain ownership."""
    data: dict[str, list[dict]] = {}
    for batch in batches:
        for name, rows in batch.data.items():
            data.setdefault(name, []).extend(rows)
    return data


def _validate(
    context: ImportContext, entities: tuple[CsvEntity, ...] = ENTITIES
) -> None:
    """Run shared reference checks followed by every domain's own rules."""
    validate_references(entities, context)
    for domain in CSV_DOMAINS:
        domain.validate_import(context)


def parse_migration(content: bytes) -> dict[str, list[dict]]:
    """Validate an archive's source state without accessing a destination database."""
    batches = _parse_archive(content)
    history.validate_source_references(batches)
    data = _combine(batches)
    context = ImportContext(
        {entity.name: [] for entity in ENTITIES},
        data,
        batches={batch.area.name: batch for batch in batches},
    )
    context.merge(administration.REPLACE_TABLES)
    _validate(context)
    return data


async def import_area_rows(
    session: AsyncSession,
    name: str,
    rows: list[tuple] | list[list[str]],
    admin_id: UUID | None = None,
) -> ImportResult:
    """Import one domain atomically, updating IDs and retaining omitted records."""
    try:
        batch = await asyncio.to_thread(DOMAIN_BY_NAME[name].parse_csv, rows)
        return await _import_batches(session, (batch,), admin_id, complete=False)
    except (ValueError, UnicodeError, csv.Error) as exc:
        await session.rollback()
        return ImportResult(errors=[str(exc)])


async def import_migration(
    session: AsyncSession, content: bytes, admin_id: UUID
) -> ImportResult:
    """Restore all areas into an empty destination using one transaction."""
    try:
        batches = await asyncio.to_thread(_parse_archive, content)
        history.validate_source_references(batches)
        return await _import_batches(session, batches, admin_id, complete=True)
    except ValueError as exc:
        await session.rollback()
        return ImportResult(errors=[str(exc)])


async def _import_batches(
    session: AsyncSession,
    batches: tuple[CsvBatch, ...],
    admin_id: UUID | None,
    *,
    complete: bool,
) -> ImportResult:
    result = ImportResult()
    try:
        entities = ENTITIES if complete else required_entities(ENTITIES, batches)
        await _lock_destination(session, None if complete else entities)
        data = _combine(batches)
        record_ids = (
            None
            if complete
            else {
                entity.name: {row["id"] for row in data.get(entity.name, [])}
                for entity in entities
                if entity.existing_by_id
            }
        )
        existing: dict[str, list[dict]] = {entity.name: [] for entity in ENTITIES}
        existing.update(
            await load_data(session, entities, max_rows=None, record_ids=record_ids)
        )
        administration.normalize_scopes(existing["users"])
        if complete and any(
            rows for name, rows in existing.items() if name not in _BOOTSTRAP_TABLES
        ):
            raise ValueError(
                "CSV migration requires an empty destination; existing planning/master data was found."
            )
        context = ImportContext(
            existing,
            data,
            admin_id,
            complete,
            user_references=[row for batch in batches for row in batch.user_references],
            batches={batch.area.name: batch for batch in batches},
        )
        administration.prepare_import(context)
        history.prepare_import(context)
        context.merge(administration.REPLACE_TABLES)
        _validate(context, entities)
        for domain in CSV_DOMAINS:
            batch = context.batches.get(domain.CSV_AREA.name)
            if batch is not None:
                partial = await domain.write_import(session, batch, context)
                result.created += partial.created
                result.updated += partial.updated
        await history.write_import_marker(session, context)
        await session.commit()
    except (ValueError, IntegrityError) as exc:
        await session.rollback()
        return ImportResult(
            errors=[
                str(exc)
                if isinstance(exc, ValueError)
                else "CSV import violates a database constraint; nothing was imported."
            ]
        )
    except BaseException:
        # Domain writers share this transaction even on cancellation or an
        # unexpected failure. Never leave partly written data in the caller.
        await session.rollback()
        raise
    affected = None if context.refresh_all_conflicts else context.affected_resources
    await check_import_conflicts(session, result, affected)
    return result
