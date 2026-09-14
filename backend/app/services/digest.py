"""What in the plan needs somebody's attention, and how urgently.

Capado already detects every condition below — expiring qualifications, commitments that no
longer fit, violated dependencies, requirements nobody covers. What it could not do was tell
anyone. Each check lived where it was computed, so seeing all of them meant opening four
screens and knowing to look.

This module turns them into one comparable list. It is pure over already-loaded values: no
session, no queries, so every rule is testable and the same list can be rendered in-app,
mailed, or written to a report without three implementations drifting apart.

**The hard part is not detection, it is suppression.** A plan of any size produces hundreds
of true statements, and a digest of hundreds of true statements gets ignored within a week —
at which point the mechanism is worse than nothing, because everyone believes they are being
warned. Three deliberate limits:

- Every finding carries a ``due`` date and findings beyond the horizon are dropped. A
  qualification lapsing in 2029 is true and useless.
- Severity is derived from proximity, not from the kind of problem. An expiry next week
  outranks a dependency violation next year, because that is the order somebody would
  actually work in.
- Findings collapse per subject. One line per person per skill, not one per affected
  assignment, because ten assignments blocked by one lapsed certificate is one problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from uuid import UUID


class FindingKind(StrEnum):
    """What kind of problem a finding describes."""

    qualification_expiring = "qualification_expiring"
    qualification_expired = "qualification_expired"
    commitment_at_risk = "commitment_at_risk"
    dependency_violated = "dependency_violated"
    requirement_uncovered = "requirement_uncovered"


class Severity(StrEnum):
    """How urgently a finding needs attention.

    Derived from how soon it bites, never from the kind of problem — see the module
    docstring.
    """

    critical = "critical"
    warning = "warning"
    info = "info"


@dataclass(frozen=True)
class Finding:
    """One thing somebody should look at.

    CARRIES DATA, NOT PROSE. An earlier version composed ``title`` and ``detail`` as German
    f-strings here and shipped them as finished sentences. The client is bilingual, so
    switching its locale produced English chrome over German sentences — invisible on a
    German-only screen, and found only by screenshotting the page in English. ``kind``
    already says which sentence to use; ``params`` supplies the values, and the client owns
    the wording in the language it is already translating everything else into.

    Attributes:
        kind: Which check produced it. Also selects the sentence the client renders.
        severity: Derived from ``due``, not passed in by the caller.
        subject_key: Identity used to collapse duplicates. Ten assignments blocked by one
            lapsed certificate share a subject and become one finding.
        params: Substitution values for the client's sentence — names, counts, dates.
            Strings throughout, dates as ISO so the client can format them for its own
            locale rather than being handed a fixed representation.
        due: When it bites. In the past for something already broken.
        resource_id: The person or machine involved, when there is one.
        work_package_id: The work package involved, when there is one.
    """

    kind: FindingKind
    severity: Severity
    subject_key: str
    params: dict[str, str]
    due: date
    resource_id: UUID | None = None
    work_package_id: UUID | None = None
    project_id: UUID | None = None


@dataclass(frozen=True)
class DigestThresholds:
    """Configurable limits, because the right numbers depend on the operation.

    A rail workshop planning in quarters and a job shop planning in days do not want the
    same horizon, and hard-coding either would make the digest useless for the other.
    """

    # How far ahead to look at all. Beyond this a finding is true but not actionable.
    horizon_days: int = 90
    # Inside this, a finding is critical: too close to solve by rescheduling.
    critical_days: int = 14
    # Inside this, a warning. Beyond it, informational.
    warning_days: int = 45
    # Cap on the returned list. A digest nobody finishes reading is a digest nobody reads.
    max_findings: int = 100


def severity_for(due: date, today: date, thresholds: DigestThresholds) -> Severity:
    """Classify by proximity.

    Anything already due is critical regardless of how long ago: an expired certificate does
    not become less of a problem by being ignored for a month, and letting age decay the
    severity would quietly bury exactly the findings somebody failed to act on.
    """
    days = (due - today).days
    if days <= thresholds.critical_days:
        return Severity.critical
    if days <= thresholds.warning_days:
        return Severity.warning
    return Severity.info


def within_horizon(due: date, today: date, thresholds: DigestThresholds) -> bool:
    """Whether a finding is close enough to be worth reporting.

    Past-due findings are always in horizon. The horizon exists to cut off speculation about
    the far future, not to hide things that already went wrong.
    """
    days = (due - today).days
    return days <= thresholds.horizon_days


@dataclass
class DigestBuilder:
    """Accumulates findings, applying suppression as they arrive.

    Collapsing on arrival rather than afterwards keeps the memory bounded on a large plan
    and makes the "first one wins per subject" rule explicit: callers add findings in
    order of specificity, so the more precise statement about a subject is the one kept.
    """

    today: date
    thresholds: DigestThresholds = field(default_factory=DigestThresholds)
    _by_subject: dict[str, Finding] = field(default_factory=dict)

    def add(
        self,
        kind: FindingKind,
        subject_key: str,
        params: dict[str, str],
        due: date,
        resource_id: UUID | None = None,
        work_package_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> bool:
        """Record a finding unless it is out of horizon or already covered.

        Returns whether it was kept, so a caller can count what it suppressed rather than
        guessing.
        """
        if not within_horizon(due, self.today, self.thresholds):
            return False
        if subject_key in self._by_subject:
            return False
        self._by_subject[subject_key] = Finding(
            kind=kind,
            severity=severity_for(due, self.today, self.thresholds),
            subject_key=subject_key,
            params=params,
            due=due,
            resource_id=resource_id,
            work_package_id=work_package_id,
            project_id=project_id,
        )
        return True

    def result(self) -> list[Finding]:
        """The findings, most urgent first, capped at ``max_findings``.

        Sorted by due date rather than by severity, which orders identically inside a
        severity band and additionally orders sensibly across bands. Ties break on kind and
        subject so the list is stable between calls — an unstable digest looks like it is
        changing when nothing has.
        """
        ordered = sorted(
            self._by_subject.values(),
            key=lambda f: (f.due, f.kind.value, f.subject_key),
        )
        return ordered[: self.thresholds.max_findings]

    @property
    def suppressed_count(self) -> int:
        """How many findings exceeded the cap and are not in the result."""
        return max(0, len(self._by_subject) - self.thresholds.max_findings)


def summarise(findings: list[Finding]) -> dict[str, int]:
    """Count by severity, for a header that says how bad it is before the detail."""
    counts = {s.value: 0 for s in Severity}
    for finding in findings:
        counts[finding.severity.value] += 1
    return counts
