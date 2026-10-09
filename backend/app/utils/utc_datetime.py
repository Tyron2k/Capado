"""Timezone-aware timestamp storage with a UTC fallback for SQLite tests."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import types
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.sql.operators import OperatorType


class UTCDateTime(types.TypeDecorator[datetime]):
    """Store aware datetimes and return them in UTC."""

    impl = types.DateTime
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    def __repr__(self) -> str:
        return "UTCDateTime()"

    def coerce_compared_value(
        self, op: OperatorType | None, value: Any
    ) -> types.TypeEngine[Any]:
        """Keep SQL timestamp subtraction compatible with interval expressions."""
        if isinstance(value, timedelta):
            return types.Interval()
        return self

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Reject ambiguous naive instants and store normalized UTC."""
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError(
                "Datetime values must have timezone information. "
                "Use datetime.now(UTC) or convert the entered local time to UTC."
            )
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Return aware UTC instants even on databases without timezone storage."""
        if value is None:
            return None
        if value.utcoffset() is None:
            # Databases without timezone support store UTC without an offset.
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
