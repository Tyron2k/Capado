"""Pydantic response schemas for import/export endpoints."""

from app.schemas import ResponseModel


class ImportResultResponse(ResponseModel):
    """Response schema for import operations."""

    created: int
    updated: int
    skipped: int
    errors: list[str]
    success: bool
    atomic: bool = False
    conflicts_found: int | None = None
    conflict_check_failed: bool = False
