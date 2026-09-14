"""Turn the plan's existing checks into a single digest.

Every condition here is already detected somewhere: :mod:`app.services.qualification` knows
when a certificate lapses, :func:`app.services.lead_time.assess_commitment` knows when a
promise no longer fits, :func:`app.services.dependencies.check_violation` knows when a
successor starts too early. This module calls those functions — it does not re-implement any
of them, which is the invariant that keeps the digest from drifting away from what the
screens show.

The collector is pure over already-loaded values and takes its inputs as plain records, so it
runs in tests without a database and the loading stays in one place where it can be seen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.services.dependencies import DependencyEdge, check_violation
from app.services.digest import (
    DigestBuilder,
    DigestThresholds,
    FindingKind,
)
from app.services.lead_time import assess_commitment
from app.services.qualification import HeldQualification


@dataclass(frozen=True)
class QualificationRecord:
    """One held qualification, with enough context to name it in a finding."""

    resource_id: UUID
    resource_name: str
    skill_label: str
    qualification: HeldQualification


@dataclass(frozen=True)
class CommitmentRecord:
    """One project with a promised delivery date.

    A commitment belongs to the PROJECT, not to a work package: it is what somebody
    outside the system was told, and nobody outside the system was told about a work
    package. Modelling it per work package would invent a promise that was never made.
    """

    project_id: UUID
    label: str
    committed: date | None
    planned_end: date
    derived_end: date | None


@dataclass(frozen=True)
class DependencyRecord:
    """One dependency edge with the dates of both ends."""

    edge: DependencyEdge
    predecessor_label: str
    successor_label: str
    successor_id: UUID
    project_id: UUID
    predecessor_end: date
    successor_start: date


@dataclass(frozen=True)
class UncoveredRequirement:
    """One requirement nobody currently satisfies."""

    work_package_id: UUID
    project_id: UUID
    label: str
    skill_label: str
    needed_by: date


def collect(
    today: date,
    is_working_day: Callable[[date], bool],
    qualifications: list[QualificationRecord],
    commitments: list[CommitmentRecord],
    dependencies: list[DependencyRecord],
    uncovered: list[UncoveredRequirement],
    thresholds: DigestThresholds | None = None,
) -> DigestBuilder:
    """Build the digest from already-loaded records.

    Returns the builder rather than the list so the caller can read ``suppressed_count``
    and report honestly that the digest is truncated instead of implying it is complete.

    Order of addition matters: qualifications first, because they are the most specific
    statement about a subject and the builder keeps the first finding per subject.
    """
    builder = DigestBuilder(today=today, thresholds=thresholds or DigestThresholds())

    for record in qualifications:
        valid_until = record.qualification.valid_until
        if valid_until is None:
            continue
        already_gone = valid_until < today
        days = abs((valid_until - today).days)
        builder.add(
            kind=(
                FindingKind.qualification_expired
                if already_gone
                else FindingKind.qualification_expiring
            ),
            # Per person per skill, not per affected assignment: ten work packages
            # blocked by one lapsed certificate is one problem to solve.
            subject_key=f"qualification:{record.resource_id}:{record.skill_label}",
            # `days` is already the absolute value, and the two kinds carry the direction:
            # expired means it ran out `days` ago, expiring means it runs out in `days`.
            # Handing the client one number plus the kind keeps the sign out of the wording.
            params={
                "skill": record.skill_label,
                "person": record.resource_name,
                "days": str(days),
                "date": valid_until.isoformat(),
            },
            due=valid_until,
            resource_id=record.resource_id,
        )

    for commitment in commitments:
        breach = assess_commitment(
            committed=commitment.committed,
            planned_end=commitment.planned_end,
            derived_end=commitment.derived_end,
            is_working_day=is_working_day,
        )
        if breach is None:
            continue
        # The committed date IS the due date. Using the planned end would report the
        # problem as arriving when the work slips, which is later than the moment
        # somebody can still do something about the promise.
        assert commitment.committed is not None  # assess_commitment returned a breach
        builder.add(
            kind=FindingKind.commitment_at_risk,
            subject_key=f"commitment:{commitment.project_id}",
            params={
                "project": commitment.label,
                "committed": commitment.committed.isoformat(),
                "planned_end": commitment.planned_end.isoformat(),
            },
            due=commitment.committed,
            project_id=commitment.project_id,
        )

    for dependency in dependencies:
        violation = check_violation(
            edge=dependency.edge,
            predecessor_end=dependency.predecessor_end,
            successor_start=dependency.successor_start,
            is_working_day=is_working_day,
        )
        if violation is None:
            continue
        builder.add(
            kind=FindingKind.dependency_violated,
            subject_key=f"dependency:{dependency.successor_id}",
            params={
                "successor": dependency.successor_label,
                "predecessor": dependency.predecessor_label,
                "days": str(violation.working_days_short),
            },
            # The successor's own start is when the problem bites, not the
            # predecessor's end: that is the day somebody would otherwise begin work
            # that cannot yet be done.
            due=dependency.successor_start,
            work_package_id=dependency.successor_id,
            project_id=dependency.project_id,
        )

    for requirement in uncovered:
        builder.add(
            kind=FindingKind.requirement_uncovered,
            subject_key=(
                f"requirement:{requirement.work_package_id}:{requirement.skill_label}"
            ),
            params={
                "skill": requirement.skill_label,
                "work_package": requirement.label,
                "needed_by": requirement.needed_by.isoformat(),
            },
            due=requirement.needed_by,
            work_package_id=requirement.work_package_id,
            project_id=requirement.project_id,
        )

    return builder
