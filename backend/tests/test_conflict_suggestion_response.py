"""The operating-window suggestion must expose its exact target timestamp."""

from datetime import datetime
from uuid import uuid4

import pytest

from app.routers.conflicts import get_conflict_suggestions
from app.schemas.conflict_suggestion import ConflictSuggestionResponse
from app.services.conflict_suggestion_service import (
    ConflictSuggestionService,
    ResolutionSuggestion,
)


def test_operating_window_target_is_in_api_response() -> None:
    """Clients need the timestamp to preview and apply the same move."""
    target = datetime(2026, 9, 25, 8, 30)
    suggestion = ConflictSuggestionResponse(
        type="shift_into_window",
        assignment_id=uuid4(),
        description="Move into operating hours",
        new_start_at=target,
    )

    assert suggestion.model_dump(mode="json")["new_start_at"] == "2026-09-25T08:30:00"


async def test_suggestion_route_passes_through_operating_window_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route must not discard the proposed timestamp during serialization."""
    target = datetime(2026, 9, 25, 8, 30)
    assignment_id = uuid4()

    async def fake_suggestions(self: ConflictSuggestionService, conflict_id: object):
        return [
            ResolutionSuggestion(
                type="shift_into_window",
                assignment_id=assignment_id,
                description="Move into operating hours",
                new_start_at=target,
            )
        ]

    monkeypatch.setattr(ConflictSuggestionService, "get_suggestions", fake_suggestions)
    result = await get_conflict_suggestions(uuid4(), session=None, _current_user=None)

    assert result[0].new_start_at == target
