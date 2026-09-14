"""Tests for :mod:`app.services.baseline_service`.

The diff is the deliverable, not the snapshot (ADR-007), so it is what gets tested.
Both functions under test are pure over dictionaries, which is why they are
module-level rather than methods — no database, matching the rest of this project.

All data is inline and clearly fictional.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.models.assignment import Assignment
from app.models.resource import ResourceType
from app.services.baseline_service import (
    diff_payloads,
    diff_snapshots,
    snapshot_payload,
)

WP = UUID("11111111-0000-0000-0000-000000000001")
A1 = UUID("22222222-0000-0000-0000-000000000001")
A2 = UUID("22222222-0000-0000-0000-000000000002")


def _payload(**overrides: object) -> dict[str, object]:
    """A fictional assignment snapshot."""
    base: dict[str, object] = {
        "id": str(A1),
        "resource_id": str(UUID("33333333-0000-0000-0000-000000000001")),
        "work_package_id": str(WP),
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "allocation_percent": 50.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# snapshot_payload
# ---------------------------------------------------------------------------


class TestSnapshotPayload:
    """What gets frozen for one entity."""

    def test_fields_are_captured_and_json_reduced(self):
        """Dates become strings so the payload survives JSON storage."""
        assignment = Assignment(
            id=A1,
            resource_id=UUID("33333333-0000-0000-0000-000000000001"),
            resource_type=ResourceType.personal,
            work_package_id=WP,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            allocation_percent=50.0,
        )
        payload = snapshot_payload(assignment)
        assert payload["start_date"] == "2026-06-01"
        assert payload["allocation_percent"] == 50.0
        assert payload["id"] == str(A1)

    def test_bookkeeping_columns_are_excluded(self):
        """created_at and updated_at change on every write.

        Including them would report a row as drifted when nothing about the plan
        moved.
        """
        assignment = Assignment(
            id=A1,
            resource_id=UUID("33333333-0000-0000-0000-000000000001"),
            resource_type=ResourceType.personal,
            work_package_id=WP,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            allocation_percent=50.0,
        )
        payload = snapshot_payload(assignment)
        assert "created_at" not in payload
        assert "updated_at" not in payload


# ---------------------------------------------------------------------------
# diff_payloads
# ---------------------------------------------------------------------------


class TestDiffPayloads:
    """Field-by-field comparison of one entity."""

    def test_identical_payloads_have_no_changes(self):
        assert diff_payloads(_payload(), _payload()) == {}

    def test_changed_field_is_reported_both_ways(self):
        """A reader needs the old value as much as the new one."""
        changes = diff_payloads(_payload(), _payload(allocation_percent=80.0))
        assert changes == {"allocation_percent": {"baseline": 50.0, "current": 80.0}}

    def test_several_changed_fields(self):
        changes = diff_payloads(
            _payload(), _payload(start_date="2026-06-08", end_date="2026-06-12")
        )
        assert set(changes) == {"start_date", "end_date"}

    def test_field_added_since_the_baseline_is_not_a_change(self):
        """Only keys present in BOTH are compared.

        A column added to the model after the freeze would otherwise report as a
        change from None, which claims the old plan said something it never said.
        """
        current = _payload()
        current["requirement_mode"] = "headcount"
        assert diff_payloads(_payload(), current) == {}

    def test_field_removed_since_the_baseline_stops_being_compared(self):
        """The frozen value is not wrong, it is no longer meaningful."""
        baseline = _payload()
        baseline["legacy_field"] = "gone"
        assert diff_payloads(baseline, _payload()) == {}


# ---------------------------------------------------------------------------
# diff_snapshots
# ---------------------------------------------------------------------------


class TestDiffSnapshots:
    """Drift of a whole plan."""

    def test_unchanged_plan_yields_an_empty_diff(self):
        """An unchanged plan must not list everything it contains."""
        snapshot = {("assignments", A1): _payload()}
        diff = diff_snapshots(snapshot, dict(snapshot))
        assert not diff.has_drift
        assert diff.added == []
        assert diff.removed == []
        assert diff.changed == []

    def test_new_entity_is_added_not_an_error(self):
        """Work created after the freeze is genuinely new."""
        diff = diff_snapshots({}, {("assignments", A1): _payload()})
        assert diff.has_drift
        assert [d.entity_id for d in diff.added] == [A1]
        assert diff.added[0].entity_type == "assignments"
        assert diff.added[0].changes == {}

    def test_missing_entity_is_removed(self):
        """Work deleted after the freeze is work that went away."""
        diff = diff_snapshots({("assignments", A1): _payload()}, {})
        assert [d.entity_id for d in diff.removed] == [A1]

    def test_modified_entity_carries_its_field_changes(self):
        diff = diff_snapshots(
            {("assignments", A1): _payload()},
            {("assignments", A1): _payload(start_date="2026-06-08")},
        )
        assert diff.changed[0].entity_id == A1
        assert diff.changed[0].changes["start_date"] == {
            "baseline": "2026-06-01",
            "current": "2026-06-08",
        }

    def test_same_id_in_different_entity_types_does_not_collide(self):
        """The key is (type, id), so a project and an assignment can share an id."""
        shared = UUID("44444444-0000-0000-0000-000000000001")
        diff = diff_snapshots(
            {("projects", shared): {"name": "A"}},
            {("assignments", shared): {"name": "A"}},
        )
        assert [d.entity_type for d in diff.added] == ["assignments"]
        assert [d.entity_type for d in diff.removed] == ["projects"]

    def test_all_three_kinds_at_once(self):
        baseline = {
            ("assignments", A1): _payload(),
            ("assignments", A2): _payload(id=str(A2)),
        }
        current = {
            ("assignments", A1): _payload(allocation_percent=100.0),
            ("work_packages", WP): {"name": "Strahlen"},
        }
        diff = diff_snapshots(baseline, current)
        assert [d.entity_id for d in diff.changed] == [A1]
        assert [d.entity_id for d in diff.removed] == [A2]
        assert [d.entity_id for d in diff.added] == [WP]

    def test_output_is_ordered_deterministically(self):
        """A report that reorders between runs cannot be diffed by a human."""
        current = {
            ("work_packages", WP): {"name": "x"},
            ("assignments", A2): _payload(id=str(A2)),
            ("assignments", A1): _payload(),
        }
        first = diff_snapshots({}, current)
        second = diff_snapshots({}, dict(reversed(list(current.items()))))
        assert [(d.entity_type, d.entity_id) for d in first.added] == [
            (d.entity_type, d.entity_id) for d in second.added
        ]
