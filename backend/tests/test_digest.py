"""Tests for :mod:`app.services.digest`.

The detection rules are trivial; the suppression rules are where a digest lives or dies. A
digest that reports everything true gets ignored within a week, and then the mechanism is
worse than nothing because everyone believes they are being warned.

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.digest import (
    DigestBuilder,
    DigestThresholds,
    FindingKind,
    Severity,
    severity_for,
    summarise,
    within_horizon,
)

TODAY = date(2026, 8, 26)
DEFAULTS = DigestThresholds()


def in_days(n: int) -> date:
    return TODAY + timedelta(days=n)


class TestSeverity:
    """Derived from proximity, never from the kind of problem."""

    def test_something_due_tomorrow_is_critical(self):
        assert severity_for(in_days(1), TODAY, DEFAULTS) is Severity.critical

    def test_something_due_inside_the_critical_window_is_critical(self):
        assert severity_for(in_days(14), TODAY, DEFAULTS) is Severity.critical

    def test_something_due_just_outside_it_is_a_warning(self):
        assert severity_for(in_days(15), TODAY, DEFAULTS) is Severity.warning

    def test_something_far_out_is_informational(self):
        assert severity_for(in_days(60), TODAY, DEFAULTS) is Severity.info

    def test_an_overdue_finding_stays_critical_however_old(self):
        """Letting age decay the severity would quietly bury exactly the findings
        somebody already failed to act on."""
        assert severity_for(in_days(-1), TODAY, DEFAULTS) is Severity.critical
        assert severity_for(in_days(-400), TODAY, DEFAULTS) is Severity.critical

    def test_thresholds_are_configurable(self):
        """A workshop planning in quarters and a job shop planning in days do not want
        the same numbers."""
        tight = DigestThresholds(critical_days=2, warning_days=5)
        assert severity_for(in_days(3), TODAY, tight) is Severity.warning
        assert severity_for(in_days(3), TODAY, DEFAULTS) is Severity.critical


class TestHorizon:
    def test_a_finding_inside_the_horizon_is_reported(self):
        assert within_horizon(in_days(30), TODAY, DEFAULTS) is True

    def test_a_finding_beyond_the_horizon_is_not(self):
        """A qualification lapsing in 2029 is true and useless."""
        assert within_horizon(in_days(400), TODAY, DEFAULTS) is False

    def test_the_boundary_is_included(self):
        assert within_horizon(in_days(90), TODAY, DEFAULTS) is True
        assert within_horizon(in_days(91), TODAY, DEFAULTS) is False

    def test_an_overdue_finding_is_always_in_horizon(self):
        """The horizon cuts off speculation about the far future, not things that already
        went wrong."""
        assert within_horizon(in_days(-200), TODAY, DEFAULTS) is True


class TestCollapsing:
    """One line per subject, not one per consequence."""

    def test_the_first_finding_for_a_subject_wins(self):
        builder = DigestBuilder(today=TODAY)
        assert (
            builder.add(
                FindingKind.qualification_expiring,
                subject_key="person-1:welding",
                params={"skill": "Schweißzeugnis", "person": "A", "days": "10"},
                due=in_days(10),
            )
            is True
        )
        assert (
            builder.add(
                FindingKind.qualification_expiring,
                subject_key="person-1:welding",
                params={"skill": "Schweißzeugnis", "person": "A", "days": "10"},
                due=in_days(10),
            )
            is False
        )
        assert len(builder.result()) == 1

    def test_ten_blocked_assignments_from_one_certificate_are_one_finding(self):
        builder = DigestBuilder(today=TODAY)
        for _ in range(10):
            builder.add(
                FindingKind.qualification_expired,
                subject_key="person-2:crane",
                params={"skill": "Kranschein", "person": "B", "days": "5"},
                due=in_days(-5),
            )
        assert len(builder.result()) == 1

    def test_different_subjects_stay_separate(self):
        builder = DigestBuilder(today=TODAY)
        builder.add(
            FindingKind.qualification_expiring, "person-1:welding", {}, in_days(5)
        )
        builder.add(
            FindingKind.qualification_expiring, "person-2:welding", {}, in_days(5)
        )
        assert len(builder.result()) == 2

    def test_an_out_of_horizon_finding_is_not_kept(self):
        builder = DigestBuilder(today=TODAY)
        assert (
            builder.add(
                FindingKind.qualification_expiring,
                "person-3:forklift",
                {},
                in_days(365),
            )
            is False
        )
        assert builder.result() == []


class TestOrderingAndCap:
    def test_the_most_urgent_comes_first(self):
        builder = DigestBuilder(today=TODAY)
        builder.add(FindingKind.commitment_at_risk, "wp-late", {}, in_days(40))
        builder.add(FindingKind.qualification_expired, "p-now", {}, in_days(-3))
        builder.add(FindingKind.dependency_violated, "wp-soon", {}, in_days(7))
        assert [f.subject_key for f in builder.result()] == [
            "p-now",
            "wp-soon",
            "wp-late",
        ]

    def test_the_order_is_stable_between_calls(self):
        """An unstable digest looks like it is changing when nothing has."""
        builder = DigestBuilder(today=TODAY)
        for key in ["c", "a", "b"]:
            builder.add(FindingKind.requirement_uncovered, key, {}, in_days(5))
        assert [f.subject_key for f in builder.result()] == ["a", "b", "c"]
        assert [f.subject_key for f in builder.result()] == ["a", "b", "c"]

    def test_the_cap_is_applied_and_the_excess_counted(self):
        builder = DigestBuilder(
            today=TODAY, thresholds=DigestThresholds(max_findings=3)
        )
        for i in range(10):
            builder.add(
                FindingKind.requirement_uncovered, f"wp-{i:02d}", {}, in_days(i + 1)
            )
        result = builder.result()
        assert len(result) == 3
        assert builder.suppressed_count == 7

    def test_the_cap_keeps_the_most_urgent_not_the_first_added(self):
        builder = DigestBuilder(
            today=TODAY, thresholds=DigestThresholds(max_findings=2)
        )
        builder.add(FindingKind.commitment_at_risk, "far", {}, in_days(80))
        builder.add(FindingKind.commitment_at_risk, "near", {}, in_days(2))
        builder.add(FindingKind.commitment_at_risk, "mid", {}, in_days(30))
        assert [f.subject_key for f in builder.result()] == ["near", "mid"]


class TestSummarise:
    def test_counts_every_severity_even_at_zero(self):
        """A header that omits a zero reads as if the check did not run."""
        assert summarise([]) == {"critical": 0, "warning": 0, "info": 0}

    def test_counts_by_severity(self):
        builder = DigestBuilder(today=TODAY)
        builder.add(FindingKind.qualification_expired, "a", {}, in_days(-1))
        builder.add(FindingKind.qualification_expiring, "b", {}, in_days(20))
        builder.add(FindingKind.commitment_at_risk, "c", {}, in_days(70))
        assert summarise(builder.result()) == {"critical": 1, "warning": 1, "info": 1}
