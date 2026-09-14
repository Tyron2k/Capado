"""Generic pagination schema for list endpoints.

Provides a reusable PaginatedResponse wrapper that includes items, total count,
and the limit/offset used for the query.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Query parameters for paginated list endpoints."""

    limit: int = Field(default=100, ge=1, le=500, description="Max items to return")
    offset: int = Field(default=0, ge=0, description="Number of items to skip")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper for list endpoints.

    Args:
        items: The page of results.
        total: Total number of matching records (before pagination).
        limit: The limit applied to this query.
        offset: The offset applied to this query.

    """

    items: list[T]
    total: int
    limit: int
    offset: int
