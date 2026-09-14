"""Whether a held qualification actually satisfies a requirement.

Three conditions, and the interesting part is what each one refuses.

**Validity is checked against the work, not against today.** A certificate expiring in March
does not cover a job planned for April, and asking "is it valid now" would answer yes. The
window has to COVER the whole assignment: the point of an expiry date is that work after it
is not covered, so a certificate lapsing mid-job fails for that job rather than half of it.

**An unrecorded level does not satisfy a minimum.** NULL means nobody assessed it, which is
not evidence of being good enough. Reading it in the resource's favour would be the wrong
direction for a check that exists to keep unqualified people off a task.

**No requirement, no problem.** A requirement without a minimum level is met by any held
level including none, because the requirement did not ask.

Pure over already-loaded values, so every rule is testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class HeldQualification:
    """One qualification a resource holds, with its bounds."""

    valid_from: date | None = None
    valid_until: date | None = None
    level: int | None = None


def covers(
    qualification: HeldQualification, start: date | None, end: date | None
) -> bool:
    """Whether the qualification is valid for the whole of the given span.

    An open bound never restricts: a qualification with no ``valid_until`` covers any
    future, and one with no ``valid_from`` covers any past.

    A span of None on either side means the caller could not determine when the work
    happens. That is treated as covered rather than as a failure — refusing on missing
    information would turn every assignment whose dates cannot be resolved into a skill
    mismatch, which is a different problem reported in the wrong place.
    """
    starts_too_early = (
        start is not None
        and qualification.valid_from is not None
        and start < qualification.valid_from
    )
    ends_too_late = (
        end is not None
        and qualification.valid_until is not None
        and end > qualification.valid_until
    )
    return not (starts_too_early or ends_too_late)


def meets_level(qualification: HeldQualification, min_level: int | None) -> bool:
    """Whether the held level is high enough.

    True when the requirement states no minimum. False when it states one and the held
    level is unrecorded — NULL is "nobody assessed it", not "good enough".
    """
    if min_level is None:
        return True
    if qualification.level is None:
        return False
    return qualification.level >= min_level


def satisfies(
    qualification: HeldQualification,
    min_level: int | None,
    start: date | None,
    end: date | None,
) -> bool:
    """Both conditions together, for the common case of one candidate qualification."""
    return covers(qualification, start, end) and meets_level(qualification, min_level)


def expires_within(
    qualification: HeldQualification, reference: date, days: int
) -> bool:
    """Whether the qualification lapses within ``days`` of ``reference``.

    For the warning a planner needs BEFORE the expiry bites: a certificate running out in
    three weeks is not yet a mismatch, but it is the last moment to book a refresher.

    Already-expired qualifications count as expiring, because a list of "needs attention"
    that silently drops the ones already past is worse than one that includes them.
    """
    if qualification.valid_until is None:
        return False
    return (qualification.valid_until - reference).days <= days
