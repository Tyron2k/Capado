"""PostgreSQL-specific column types with SQLite fallback for testing.

Provides TypeDecorator wrappers that render as PostgreSQL ARRAY in production
and fall back to JSON storage when running on SQLite (used in the test suite).
"""

import json
from typing import Any

from sqlalchemy import JSON, String, TypeDecorator
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


class UUIDArray(TypeDecorator):
    """PostgreSQL UUID[] that falls back to JSON on SQLite.

    Use this for columns that store a list of UUIDs (e.g. scope_project_ids).
    """

    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        """Return ARRAY(UUID) for PostgreSQL, JSON for others."""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(PG_UUID(as_uuid=True)))
        return dialect.type_descriptor(JSON)

    def process_bind_param(self, value: list[Any] | None, dialect: Any) -> Any:
        """Serialize UUID list to JSON string for non-PostgreSQL dialects."""
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps([str(v) for v in value])

    def process_result_value(self, value: Any, dialect: Any) -> list[Any] | None:
        """Deserialize JSON string back to list for non-PostgreSQL dialects."""
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if isinstance(value, str):
            return json.loads(value)
        return value
