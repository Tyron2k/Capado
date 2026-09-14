"""Derived progress of a project, computed from its work packages.

Progress is derived rather than stored. A status field on the project was rejected
because the values a planner would write into it ARE work package names, so keeping
them on the project would be a second copy of the same truth, free to drift from what
it summarises (ADR-008).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class WorkPackageProgress:
    """The progress fields of one work package."""

    id: UUID
    name: str
    end_date: object
    completed_at: datetime | None


def derived_status(packages: list[WorkPackageProgress]) -> str | None:
    """The furthest completed work package's name, or None if none is done.

    "Furthest" is by completion time, not by schedule: if two packages were closed
    out of order, the status should say what was actually finished last rather than
    what the plan expected to be finished last. A status claiming one step because it
    was scheduled later, when another was signed off after it, would misreport the
    state of the unit.

    Returns None for a project with no completed work — accurately "not started",
    rather than a placeholder that reads like a real state.
    """
    completed = [p for p in packages if p.completed_at is not None]
    if not completed:
        return None
    latest = max(completed, key=lambda p: (p.completed_at, p.name))
    return latest.name


def completion_ratio(packages: list[WorkPackageProgress]) -> float:
    """Share of work packages completed, 0.0 to 1.0.

    Counted per package rather than weighted by duration or effort. Weighting would
    need an effort field, and there deliberately is none: deriving progress from
    effort invites deriving duration from it too, which is the substitution this
    project rejects (ADR-005's requirement modes).
    """
    if not packages:
        return 0.0
    done = sum(1 for p in packages if p.completed_at is not None)
    return done / len(packages)
