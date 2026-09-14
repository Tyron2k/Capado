"""Updating the bounds of a qualification a resource already holds.

Separate from adding and removing, because changing an expiry date is not the same event as
gaining or losing a qualification: a welder whose certificate is renewed still holds it, and
forcing a delete-then-recreate would lose the row's identity and, with it, any audit entry
that pointed at it.

The three bounds are all independently clearable. That is why this takes explicit sentinels
rather than ``None`` for "leave alone" — ``None`` is a legitimate target value here, meaning
"this qualification no longer expires", and a partial-update convention that cannot express
it would make an expiry date impossible to remove once entered.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlmodel import select

from app.exceptions import InputValidationError, NotFoundError
from app.models.skill import (
    InfrastructureResourceSkill,
    PersonalResourceSkill,
    Skill,
    SkillAttribute,
)
from app.schemas.skill import ResourceSkillAssignmentResponse

# Sentinel for "the caller did not mention this field". Distinct from None, which means
# "clear it" — see the module docstring.
UNSET: Any = object()

_MIN_LEVEL = 1
_MAX_LEVEL = 5


class QualificationUpdate:
    """The requested change, with unmentioned fields left at :data:`UNSET`."""

    def __init__(
        self,
        valid_from: date | None = UNSET,
        valid_until: date | None = UNSET,
        level: int | None = UNSET,
    ) -> None:
        self.valid_from = valid_from
        self.valid_until = valid_until
        self.level = level


def apply_bounds(
    assignment: PersonalResourceSkill | InfrastructureResourceSkill,
    update: QualificationUpdate,
) -> None:
    """Apply the update in place, validating the result rather than the input.

    Validation runs against the FINAL state, not the values passed in. A caller that moves
    only ``valid_from`` can still invert the window against the stored ``valid_until``, and
    checking the payload alone would let that through — the database's own check constraint
    would then reject it with an error nobody can act on.
    """
    if update.valid_from is not UNSET:
        assignment.valid_from = update.valid_from
    if update.valid_until is not UNSET:
        assignment.valid_until = update.valid_until
    if update.level is not UNSET:
        assignment.level = update.level

    if assignment.level is not None and not (
        _MIN_LEVEL <= assignment.level <= _MAX_LEVEL
    ):
        raise InputValidationError(
            f"level must be between {_MIN_LEVEL} and {_MAX_LEVEL}, "
            f"got {assignment.level}"
        )

    if (
        assignment.valid_from is not None
        and assignment.valid_until is not None
        and assignment.valid_from > assignment.valid_until
    ):
        raise InputValidationError(
            f"valid_from ({assignment.valid_from}) must not be after "
            f"valid_until ({assignment.valid_until}) — the qualification would be "
            f"valid on no day at all"
        )


async def update_resource_skill(
    session: Any,
    resource_id: UUID,
    assignment_id: UUID,
    update: QualificationUpdate,
    kind: Literal["personal", "infrastructure"],
) -> ResourceSkillAssignmentResponse:
    """Change the bounds of one held qualification.

    The ``resource_id`` is part of the lookup rather than only the URL, so an assignment id
    belonging to a different resource is a 404 instead of a silent cross-resource edit.
    """
    model: type[PersonalResourceSkill] | type[InfrastructureResourceSkill] = (
        PersonalResourceSkill if kind == "personal" else InfrastructureResourceSkill
    )

    result = await session.execute(
        select(model).where(
            model.id == assignment_id,
            model.resource_id == resource_id,
        )
    )
    assignment = result.scalars().first()
    if assignment is None:
        raise NotFoundError(
            f"Skill assignment '{assignment_id}' not found for this resource"
        )

    apply_bounds(assignment, update)
    session.add(assignment)
    await session.flush()

    attr_result = await session.execute(
        select(SkillAttribute, Skill)
        .join(Skill, SkillAttribute.skill_id == Skill.id)
        .where(SkillAttribute.id == assignment.skill_attribute_id)
    )
    row = attr_result.first()
    if row is None:
        raise NotFoundError(
            f"Skill attribute '{assignment.skill_attribute_id}' no longer exists"
        )
    attribute, skill = row

    await session.commit()

    return ResourceSkillAssignmentResponse(
        id=assignment.id,
        skill_attribute_id=assignment.skill_attribute_id,
        skill_id=skill.id,
        skill_name=skill.name,
        attribute_name=attribute.name,
        valid_from=assignment.valid_from,
        valid_until=assignment.valid_until,
        level=assignment.level,
    )
