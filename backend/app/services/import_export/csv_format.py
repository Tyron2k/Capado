"""Versioned CSV syntax and explicit field descriptions, independent of domains."""

import base64
import binascii
import csv
import io
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import islice
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import Table
from sqlmodel import SQLModel

from app.models.base import ORMModel

MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_ROWS = 200_000
MAX_FIELD_BYTES = 4 * 1024 * 1024
_NULL = r"\N"
_CSV_FORMAT = "Capado CSV"
_CSV_VERSION = "2"


@dataclass(frozen=True)
class CsvEntity:
    """Approved fields and their wire encodings, owned by a domain module."""

    model: type[SQLModel] | type[ORMModel]
    columns: tuple[str, ...]
    json_columns: tuple[str, ...] = ()
    binary_columns: tuple[str, ...] = ()
    defaults: dict[str, Any] = field(default_factory=dict)
    reference_tables: tuple[str, ...] = ()
    validation_dependents: tuple[str, ...] = ()
    existing_by_id: bool = False
    validation_model: type[BaseModel] | None = None

    @property
    def name(self) -> str:
        """Stable record type and database table identifier."""
        return str(self.model.__tablename__)

    @property
    def table(self) -> Table:
        """Typed metadata for generic database operations."""
        return SQLModel.metadata.tables[self.name]


def entity(
    model: type[SQLModel] | type[ORMModel], columns: str, **kwargs: Any
) -> CsvEntity:
    """Declare a field allowlist; never discover exportable fields automatically."""
    return CsvEntity(model, tuple(columns.split()), **kwargs)


@dataclass(frozen=True)
class CsvArea:
    """A domain-owned description of one complete CSV file."""

    name: str
    entities: tuple[CsvEntity, ...]
    extra_columns: tuple[str, ...] = ()

    @property
    def tables(self) -> tuple[str, ...]:
        """Tables whose rows this domain owns."""
        return tuple(entity.name for entity in self.entities)

    @property
    def columns(self) -> tuple[str, ...]:
        """Union header with optional domain-specific reference columns."""
        return (
            ("Record Type",)
            + tuple(
                dict.fromkeys(
                    column for entity in self.entities for column in entity.columns
                )
            )
            + self.extra_columns
        )


@dataclass
class CsvBatch:
    """Parsed domain data with explicit public identity references."""

    area: CsvArea
    data: dict[str, list[dict]]
    user_references: list[dict] = field(default_factory=list)
    row_numbers: dict[tuple[str, UUID], int] = field(default_factory=dict)


class _CsvBuffer(io.StringIO):
    """Stop serialization at the same UTF-8 byte limit as the reader."""

    def __init__(self, filename: str):
        super().__init__(newline="")
        self.filename = filename
        self.size = 0

    def write(self, value: str) -> int:
        """Check cumulative bytes before storing another CSV row."""
        self.size += len(value.encode("utf-8"))
        if self.size + 3 > MAX_EXPANDED_BYTES:  # UTF-8 BOM
            raise ValueError(f"{self.filename}: CSV exceeds the 100 MiB limit.")
        return super().write(value)


def _check_field(value: str, filename: str, row: int, column: str) -> None:
    if len(value.encode("utf-8")) > MAX_FIELD_BYTES:
        raise ValueError(
            f"{filename}, row {row}, field {column[:80]}: exceeds the 4 MiB field limit."
        )


class _FieldError(ValueError):
    """A field diagnostic without echoing the uploaded value."""

    def __init__(self, column: str, message: str):
        self.column = column
        super().__init__(message)


def dump_area(
    area: CsvArea,
    data: dict[str, list[dict]],
    extras: dict[tuple[str, Any], dict[str, str]] | None = None,
) -> bytes:
    """Serialize prepared domain rows without making business decisions."""
    filename = area.name + ".csv"
    output = _CsvBuffer(filename)
    writer = csv.writer(output, delimiter=";")
    writer.writerow((_CSV_FORMAT, _CSV_VERSION, area.name))
    writer.writerow(area.columns)
    count = 0
    for entity in area.entities:
        for row in data[entity.name]:
            count += 1
            if count > MAX_ROWS:
                raise ValueError(f"{filename}: CSV exceeds the 200,000 row limit.")
            extra = (extras or {}).get((entity.name, row["id"]), {})
            values = (entity.name,) + tuple(
                _encode(row[column])
                if column in entity.columns
                else extra.get(column, "")
                for column in area.columns[1:]
            )
            for column, value in zip(area.columns, values, strict=True):
                _check_field(value, filename, count + 2, column)
            writer.writerow(values)
    content = output.getvalue().encode("utf-8-sig")
    if len(content) > MAX_EXPANDED_BYTES:
        raise ValueError("CSV export exceeds the 100 MiB limit.")
    return content


def is_area_csv(rows: list[tuple] | list[list[str]]) -> bool:
    """Recognize new exports before falling back to legacy editing imports."""
    return bool(rows and rows[0] and str(rows[0][0]).startswith(_CSV_FORMAT))


def _encode(value: Any) -> str:
    if value is None:
        return _NULL
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict | list):
        return json.dumps(value, default=str, ensure_ascii=False, allow_nan=False)
    if isinstance(value, datetime):
        # SQLite drops offsets; actual migrated PostgreSQL columns are timestamptz.
        value = (
            value.replace(tzinfo=UTC)
            if value.utcoffset() is None
            else value.astimezone(UTC)
        )
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    value = str(value)
    return "\\" + value if value.startswith("\\") else value


def _csv_bytes(columns: tuple[str, ...], rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(columns)
    writer.writerows([_encode(row[column]) for column in columns] for row in rows)
    return output.getvalue().encode("utf-8-sig")


def _read_csv(content: bytes, filename: str = "CSV") -> list[list[str]]:
    # Let the bounded parser return an oversized cell so its exact column can
    # be identified. Character counts alone do not bound UTF-8 byte sizes.
    if len(content) > MAX_EXPANDED_BYTES:
        raise ValueError(f"{filename}: CSV exceeds the 100 MiB limit.")
    csv.field_size_limit(MAX_EXPANDED_BYTES)
    reader = csv.reader(
        io.StringIO(content.decode("utf-8-sig"), newline=""),
        delimiter=";",
        strict=True,
    )
    rows: list[list[str]] = []
    for row in islice(reader, MAX_ROWS + 3):
        index = len(rows) + 1
        if (
            not rows
            and filename == "CSV"
            and len(row) == 3
            and row[0] == _CSV_FORMAT
            and re.fullmatch(r"[a-z][a-z0-9-]{0,40}", row[2])
        ):
            filename = row[2] + ".csv"
        header_index = 1 if rows and rows[0][0:1] == [_CSV_FORMAT] else 0
        columns = rows[header_index] if len(rows) > header_index else []
        for offset, value in enumerate(row):
            column = columns[offset] if offset < len(columns) else str(offset + 1)
            _check_field(value, filename, index, column)
        rows.append(row)
    if len(rows) > MAX_ROWS + 2:
        raise ValueError("CSV migration exceeds the 200,000 row limit.")
    return rows


def _decode(entity: CsvEntity, row: list[str]) -> dict:
    raw: dict[str, Any] = {}
    for column, value in zip(entity.columns, row, strict=True):
        try:
            if value == _NULL:
                raw[column] = None
            elif column in entity.json_columns:
                raw[column] = json.loads(value)
            elif column in entity.binary_columns:
                raw[column] = base64.b64decode(value, validate=True)
            else:
                raw[column] = value[1:] if value.startswith("\\\\") else value
        except (ValueError, binascii.Error) as exc:
            kind = "JSON" if column in entity.json_columns else "base64"
            raise _FieldError(column, f"invalid {kind} field value.") from exc
    raw.update(entity.defaults)
    try:
        validation_model = entity.validation_model
        if validation_model is None:
            if not issubclass(entity.model, BaseModel):
                raise TypeError(
                    f"{entity.name} requires an explicit CSV validation schema"
                )
            validation_model = entity.model
        obj = validation_model.model_validate(raw)
    except ValidationError as exc:
        error = exc.errors(include_input=False, include_url=False)[0]
        column = ".".join(str(part) for part in error["loc"])
        raise _FieldError(column, "invalid field value: " + error["msg"]) from exc
    data = obj.model_dump(include=set(entity.columns))
    for key, value in data.items():
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise _FieldError(key, "requires a UTC offset.")
        if isinstance(value, float) and not math.isfinite(value):
            raise _FieldError(key, "must be finite.")
    return data


def parse_area_rows(area: CsvArea, rows: list[tuple] | list[list[str]]) -> CsvBatch:
    """Decode one complete area, including its explicit version and row types."""
    if len(rows) < 2 or tuple(rows[0]) != (_CSV_FORMAT, _CSV_VERSION, area.name):
        raise ValueError(
            f"{area.name}.csv, row 1, field Format/Version/Area: choose the version-2 export for this area."
        )
    if tuple(rows[1]) != area.columns:
        raise ValueError(f"{area.name}.csv, row 2: missing or unexpected columns.")
    data: dict[str, list[dict]] = {entity.name: [] for entity in area.entities}
    entities = {entity.name: entity for entity in area.entities}
    seen: dict[str, set[UUID]] = {name: set() for name in entities}
    positions: dict[tuple[str, UUID], int] = {}
    for index, row in enumerate(rows[2:], start=3):
        if len(row) != len(area.columns):
            raise ValueError(
                f"{area.name}.csv, row {index}: expected {len(area.columns)} columns, got {len(row)}."
            )
        if row[0] not in entities:
            raise ValueError(
                f"{area.name}.csv, row {index}, field Record Type: invalid record type."
            )
        entity = entities[row[0]]
        for column, value in zip(area.columns, row, strict=True):
            _check_field(str(value), area.name + ".csv", index, column)
        values = dict(zip(area.columns[1:], row[1:], strict=True))
        unused = next(
            (
                key
                for key, value in values.items()
                if value != ""
                and key not in entity.columns
                and key not in area.extra_columns
            ),
            None,
        )
        if unused is not None:
            raise ValueError(
                f"{area.name}.csv, row {index}, field {unused}: values outside this record type."
            )
        try:
            record = _decode(entity, [values[column] for column in entity.columns])
        except _FieldError as exc:
            raise ValueError(
                f"{area.name}.csv, row {index}, field {exc.column}: {exc}"
            ) from exc
        if record["id"] in seen[entity.name]:
            raise ValueError(
                f"{area.name}.csv, row {index}, field id: duplicate IDs in {entity.name}."
            )
        seen[entity.name].add(record["id"])
        data[entity.name].append(record)
        positions[(entity.name, record["id"])] = index
    return CsvBatch(area, data, row_numbers=positions)
