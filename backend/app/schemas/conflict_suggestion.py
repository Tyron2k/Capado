"""Pydantic schemas for conflict resolution suggestions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas import ResponseModel

SuggestionType = Literal[
    "shift_forward",
    "shift_backward",
    "shift_into_window",
    "reduce_allocation",
    "swap_resource",
]


class ConflictSuggestionResponse(ResponseModel):
    """A single resolution suggestion for a conflict."""

    type: SuggestionType
    assignment_id: UUID
    description: str
    shift_days: int | None = None
    new_allocation_percent: float | None = None
    target_resource_id: UUID | None = None
    target_resource_name: str | None = None
    new_start_at: datetime | None = None
    new_end_at: datetime | None = None
