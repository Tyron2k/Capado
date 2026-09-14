"""A sentinel for "this field was not supplied" in partial updates.

Needed wherever a nullable field can be updated. If None meant "leave unchanged",
there would be no way to express clearing it: a project could be moved INTO a
hierarchy but never back to the top level, and a work package could be completed but
never reopened. Both are real operations, so the two cases have to be distinguishable.

The router decides which case it is from ``model_fields_set`` — what the client
actually sent — rather than from the value, because Pydantic cannot tell an omitted
field from one explicitly set to null any other way.
"""

from __future__ import annotations

from typing import Final


class UnsetType:
    """Marker type for an argument that was not supplied."""

    _instance: UnsetType | None = None

    def __new__(cls) -> UnsetType:
        """Return the single shared instance, so identity checks are reliable."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        """Always falsy, so a stray truth test cannot read UNSET as a real value."""
        return False


UNSET: Final = UnsetType()
