"""Tests for :mod:`app.services.digest_collector`.

The collector's job is translation, so the tests check two things: that the real detection
functions are the ones deciding (a record that those functions consider fine produces no
finding), and that the ``due`` date chosen for each kind is the day somebody can still act,
not the day the consequence lands. The second is where a plausible-looking wrong answer
hides — every wrong choice still produces a finding, just at the wrong time.

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.services.dependencies import DependencyEdge
from app.services.digest import DigestThresholds, FindingKind, Severity
from app.services.digest_collector import (
    CommitmentRecord,
    DependencyRecord,
    QualificationRecord,
    UncoveredRequirement,
    collect,
)
from app.services.qualification import HeldQualification

TODAY = date(2026, 8, 26)


def weekdays_only(day: date) -> bool:
    """Mon-Fri, which is enough calendar for these tests."""
    return day.weekday() < 5


def run(**kwargs):
    """Call collect with empty defaults for whatever the test does not provide."""
    return collect(
        today=kwargs.pop("today", TODAY),
        is_working_day=kwargs.pop("is_working_day", weekdays_only),
        qualifications=kwargs.pop("qualifications", []),
        commitments=kwargs.pop("commitments", []),
        dependencies=kwargs.pop("dependencies", []),
        uncovered=kwargs.pop("uncovered", []),
        thresholds=kwargs.pop("thresholds", None),
    )


class TestQualifications:
    def test_an_unbounded_qualification_produces_nothing(self):
        record = QualificationRecord(
            resource_id=uuid4(),
            resource_name="A. Beispiel",
            skill_label="Schweißen E1",
            qualification=HeldQualification(),
        )
        assert run(qualifications=[record]).result() == []

    def test_an_expiring_qualification_is_due_on_its_expiry_date(self):
        expiry = date(2026, 9, 10)
        record = QualificationRecord(
            resource_id=uuid4(),
            resource_name="A. Beispiel",
            skill_label="Schweißen E1",
            qualification=HeldQualification(valid_until=expiry),
        )
        findings = run(qualifications=[record]).result()
        assert len(findings) == 1
        assert findings[0].kind is FindingKind.qualification_expiring
        assert findings[0].due == expiry
        # Asserted on the PARAMS, not on wording: the collector no longer composes prose,
        # and a test that checked for "läuft ab" was pinning German rather than behaviour.
        assert findings[0].params == {
            "skill": "Schweißen E1",
            "person": "A. Beispiel",
            "days": "15",
            "date": expiry.isoformat(),
        }

    def test_an_already_expired_qualification_is_reported_as_expired_and_critical(self):
        record = QualificationRecord(
            resource_id=uuid4(),
            resource_name="B. Beispiel",
            skill_label="Kranschein",
            qualification=HeldQualification(valid_until=date(2026, 7, 1)),
        )
        findings = run(qualifications=[record]).result()
        assert findings[0].kind is FindingKind.qualification_expired
        assert findings[0].severity is Severity.critical
        # The direction lives in the KIND, so `days` is the absolute distance either way.
        # That is the property worth pinning: a signed number here would let the client
        # render "in -5 days".
        assert findings[0].params["skill"] == "Kranschein"
        assert findings[0].params["days"] == "56"
        assert findings[0].params["date"] == "2026-07-01"

    def test_a_far_future_expiry_is_dropped(self):
        record = QualificationRecord(
            resource_id=uuid4(),
            resource_name="C. Beispiel",
            skill_label="Staplerschein",
            qualification=HeldQualification(valid_until=date(2029, 1, 1)),
        )
        assert run(qualifications=[record]).result() == []

    def test_the_same_person_and_skill_collapses(self):
        resource_id = uuid4()
        records = [
            QualificationRecord(
                resource_id=resource_id,
                resource_name="D. Beispiel",
                skill_label="Schweißen E1",
                qualification=HeldQualification(valid_until=date(2026, 9, 1)),
            )
            for _ in range(4)
        ]
        assert len(run(qualifications=records).result()) == 1


class TestCommitments:
    def test_a_commitment_the_plan_meets_produces_nothing(self):
        record = CommitmentRecord(
            project_id=uuid4(),
            label="WP-1",
            committed=date(2026, 10, 1),
            planned_end=date(2026, 9, 20),
            derived_end=date(2026, 9, 20),
        )
        assert run(commitments=[record]).result() == []

    def test_a_work_package_without_a_commitment_produces_nothing(self):
        """A project nobody promised anything about is not a project running late."""
        record = CommitmentRecord(
            project_id=uuid4(),
            label="WP-2",
            committed=None,
            planned_end=date(2026, 9, 20),
            derived_end=None,
        )
        assert run(commitments=[record]).result() == []

    def test_a_breach_is_due_on_the_committed_date_not_the_planned_end(self):
        """Using the planned end would report the problem as arriving when the work
        slips, which is after the last moment somebody could still renegotiate."""
        committed = date(2026, 9, 15)
        record = CommitmentRecord(
            project_id=uuid4(),
            label="WP-3",
            committed=committed,
            planned_end=date(2026, 10, 30),
            derived_end=date(2026, 10, 30),
        )
        findings = run(commitments=[record]).result()
        assert len(findings) == 1
        assert findings[0].kind is FindingKind.commitment_at_risk
        assert findings[0].due == committed


class TestDependencies:
    def test_a_consistent_pair_produces_nothing(self):
        pred, succ = uuid4(), uuid4()
        record = DependencyRecord(
            edge=DependencyEdge(predecessor_id=pred, successor_id=succ),
            predecessor_label="WP-A",
            successor_label="WP-B",
            successor_id=succ,
            project_id=uuid4(),
            predecessor_end=date(2026, 9, 1),
            successor_start=date(2026, 9, 10),
        )
        assert run(dependencies=[record]).result() == []

    def test_a_violation_is_due_on_the_successor_start(self):
        """That is the day somebody would otherwise begin work that cannot yet be
        done — the predecessor's end is when the blockage was created, not when it
        bites."""
        pred, succ = uuid4(), uuid4()
        successor_start = date(2026, 9, 2)
        record = DependencyRecord(
            edge=DependencyEdge(predecessor_id=pred, successor_id=succ),
            predecessor_label="WP-A",
            successor_label="WP-B",
            successor_id=succ,
            project_id=uuid4(),
            predecessor_end=date(2026, 9, 15),
            successor_start=successor_start,
        )
        findings = run(dependencies=[record]).result()
        assert len(findings) == 1
        assert findings[0].kind is FindingKind.dependency_violated
        assert findings[0].due == successor_start
        # Both ends are named: a warning that says only one side cannot be acted on,
        # because the reader has to know what waits on what before deciding which date moves.
        assert findings[0].params["successor"] == "WP-B"
        assert findings[0].params["predecessor"] == "WP-A"
        assert int(findings[0].params["days"]) > 0


class TestUncoveredRequirements:
    def test_an_uncovered_requirement_is_reported(self):
        wp_id = uuid4()
        record = UncoveredRequirement(
            work_package_id=wp_id,
            project_id=uuid4(),
            label="WP-9",
            skill_label="Drehen",
            needed_by=date(2026, 9, 5),
        )
        findings = run(uncovered=[record]).result()
        assert len(findings) == 1
        assert findings[0].kind is FindingKind.requirement_uncovered
        assert findings[0].work_package_id == wp_id


class TestAcrossKinds:
    def test_findings_of_all_kinds_share_one_ordered_list(self):
        resource_id, succ, wp = uuid4(), uuid4(), uuid4()
        builder = run(
            qualifications=[
                QualificationRecord(
                    resource_id=resource_id,
                    resource_name="E. Beispiel",
                    skill_label="Schweißen",
                    qualification=HeldQualification(valid_until=date(2026, 8, 20)),
                )
            ],
            dependencies=[
                DependencyRecord(
                    edge=DependencyEdge(predecessor_id=uuid4(), successor_id=succ),
                    predecessor_label="WP-A",
                    successor_label="WP-B",
                    successor_id=succ,
                    project_id=uuid4(),
                    predecessor_end=date(2026, 10, 1),
                    successor_start=date(2026, 9, 1),
                )
            ],
            uncovered=[
                UncoveredRequirement(
                    work_package_id=wp,
                    project_id=uuid4(),
                    label="WP-C",
                    skill_label="Fräsen",
                    needed_by=date(2026, 10, 15),
                )
            ],
        )
        findings = builder.result()
        assert [f.kind for f in findings] == [
            FindingKind.qualification_expired,
            FindingKind.dependency_violated,
            FindingKind.requirement_uncovered,
        ]

    def test_the_cap_is_reported_rather_than_hidden(self):
        records = [
            QualificationRecord(
                resource_id=uuid4(),
                resource_name=f"Person {i}",
                skill_label="Schweißen",
                qualification=HeldQualification(valid_until=date(2026, 9, 1)),
            )
            for i in range(8)
        ]
        builder = run(
            qualifications=records, thresholds=DigestThresholds(max_findings=3)
        )
        assert len(builder.result()) == 3
        assert builder.suppressed_count == 5
