"""Pydantic response schemas for import/export endpoints."""

from pydantic import BaseModel


class ImportResultResponse(BaseModel):
    """Response schema for import operations."""

    created: int
    updated: int
    skipped: int
    errors: list[str]
    success: bool
    conflicts_found: int | None = None
    conflict_check_failed: bool = False
