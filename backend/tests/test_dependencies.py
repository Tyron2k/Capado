"""Tests for :mod:`app.services.dependencies`.

Two things are easy to get wrong here and both are silent when wrong: the off-by-one at
the boundary between predecessor and successor, and a cycle that makes the graph
unschedulable.

Pure over an ``is_working_day`` predicate. No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.services.dependencies import (
    DependencyEdge,
    check_violation,
    earliest_successor_start,
    reaches,
    successors_of,
    would_create_cycle,
)

STRAHLEN = UUID("aaaaaaaa-0000-0000-0000-000000000001")
GRUNDIEREN = UUID("aaaaaaaa-0000-0000-0000-000000000002")
DECKLACK = UUID("aaaaaaaa-0000-0000-0000-000000000003")
ABNAHME = UUID("aaaaaaaa-0000-0000-0000-000000000004")

# 2026-06-05 is a Friday, 2026-06-08 the following Monday.
FRIDAY = date(2026, 6, 5)
SATURDAY = date(2026, 6, 6)
MONDAY = date(2026, 6, 8)
TUESDAY = date(2026, 6, 9)
WEDNESDAY = date(2026, 6, 10)


def five_day_week(day: date) -> bool:
    """Monday to Friday are working days."""
    return day.weekday() < 5


def never(_day: date) -> bool:
    """A calendar with no working days at all."""
    return False


def _chain() -> list[DependencyEdge]:
    """Strahlen -> Grundieren -> Decklack, the ordinary case."""
    return [
        DependencyEdge(STRAHLEN, GRUNDIEREN),
        DependencyEdge(GRUNDIEREN, DECKLACK),
    ]


class TestTraversal:
    """Following the graph."""

    def test_direct_successors(self):
        assert successors_of(STRAHLEN, _chain()) == [GRUNDIEREN]

    def test_a_leaf_has_no_successors(self):
        assert successors_of(DECKLACK, _chain()) == []

    def test_reach_is_transitive(self):
        assert reaches(STRAHLEN, DECKLACK, _chain()) is True

    def test_reach_does_not_run_backwards(self):
        assert reaches(DECKLACK, STRAHLEN, _chain()) is False

    def test_a_node_reaches_itself(self):
        assert reaches(STRAHLEN, STRAHLEN, _chain()) is True

    def test_traversal_terminates_on_corrupt_data(self):
        """Cycles are refused at the write, but a reader must not hang on data an
        older version of the code let through."""
        cyclic = [
            DependencyEdge(STRAHLEN, GRUNDIEREN),
            DependencyEdge(GRUNDIEREN, STRAHLEN),
        ]
        assert reaches(STRAHLEN, ABNAHME, cyclic) is False


class TestCycleGuard:
    """Refused at the write, because a cycle has no valid reading at all."""

    def test_a_package_cannot_depend_on_itself(self):
        assert would_create_cycle(STRAHLEN, STRAHLEN, []) is True

    def test_a_direct_reversal_is_refused(self):
        edges = [DependencyEdge(STRAHLEN, GRUNDIEREN)]
        assert would_create_cycle(GRUNDIEREN, STRAHLEN, edges) is True

    def test_closing_a_longer_loop_is_refused(self):
        assert would_create_cycle(DECKLACK, STRAHLEN, _chain()) is True

    def test_extending_the_chain_is_allowed(self):
        assert would_create_cycle(DECKLACK, ABNAHME, _chain()) is False

    def test_a_second_predecessor_is_allowed(self):
        """Two things can both have to finish before a third starts."""
        assert would_create_cycle(ABNAHME, DECKLACK, _chain()) is False


class TestEarliestStart:
    """Where the successor may begin. The off-by-one lives here."""

    def test_no_lag_means_the_next_working_day(self):
        """Not the same day. A successor starting the day its predecessor ends would
        overlap it, which finish-to-start denies by definition."""
        assert earliest_successor_start(FRIDAY, 0, five_day_week) == MONDAY

    def test_a_weekend_is_skipped(self):
        assert earliest_successor_start(FRIDAY, 0, five_day_week) != SATURDAY

    def test_one_lag_day_adds_one_working_day(self):
        assert earliest_successor_start(FRIDAY, 1, five_day_week) == TUESDAY

    def test_two_lag_days_add_two_working_days(self):
        """Curing time is not satisfied by a weekend."""
        assert earliest_successor_start(FRIDAY, 2, five_day_week) == WEDNESDAY

    def test_a_midweek_end_with_no_lag(self):
        assert earliest_successor_start(MONDAY, 0, five_day_week) == TUESDAY

    def test_a_negative_lag_is_treated_as_zero(self):
        assert earliest_successor_start(FRIDAY, -3, five_day_week) == MONDAY

    def test_a_calendar_with_no_working_days_yields_nothing(self):
        assert earliest_successor_start(FRIDAY, 0, never) is None


class TestViolation:
    """Whether the entered dates contradict the link."""

    def test_a_successor_starting_the_next_working_day_is_fine(self):
        edge = DependencyEdge(STRAHLEN, GRUNDIEREN)
        assert check_violation(edge, FRIDAY, MONDAY, five_day_week) is None

    def test_a_successor_starting_later_is_fine(self):
        edge = DependencyEdge(STRAHLEN, GRUNDIEREN)
        assert check_violation(edge, FRIDAY, WEDNESDAY, five_day_week) is None

    def test_a_successor_starting_the_same_day_is_a_violation(self):
        """The pair overlaps, which is what finish-to-start rules out."""
        edge = DependencyEdge(STRAHLEN, GRUNDIEREN)
        result = check_violation(edge, FRIDAY, FRIDAY, five_day_week)
        assert result is not None
        assert result.earliest_start == MONDAY
        assert result.working_days_short == 1

    def test_a_successor_starting_before_its_predecessor_ends(self):
        edge = DependencyEdge(STRAHLEN, GRUNDIEREN)
        result = check_violation(edge, FRIDAY, date(2026, 6, 3), five_day_week)
        assert result is not None
        assert result.working_days_short == 3

    def test_the_lag_is_part_of_the_violation(self):
        """The same dates pass without a lag and fail with one."""
        no_lag = DependencyEdge(STRAHLEN, GRUNDIEREN, lag_working_days=0)
        with_lag = DependencyEdge(STRAHLEN, GRUNDIEREN, lag_working_days=2)
        assert check_violation(no_lag, FRIDAY, MONDAY, five_day_week) is None
        result = check_violation(with_lag, FRIDAY, MONDAY, five_day_week)
        assert result is not None
        assert result.lag_working_days == 2
        assert result.earliest_start == WEDNESDAY

    def test_the_shortfall_is_counted_in_working_days(self):
        """A weekend inside the gap is not something anyone can recover."""
        edge = DependencyEdge(STRAHLEN, GRUNDIEREN)
        result = check_violation(
            edge, date(2026, 6, 12), date(2026, 6, 11), five_day_week
        )
        assert result is not None
        # 11 June is a Thursday; the earliest start is Monday 15 June. Two working
        # days to move, not four calendar days.
        assert result.working_days_short == 2

    def test_a_broken_calendar_reports_no_violation(self):
        """A calendar that defines no working days is not evidence of a mistake."""
        edge = DependencyEdge(STRAHLEN, GRUNDIEREN)
        assert check_violation(edge, FRIDAY, FRIDAY, never) is None

    def test_the_violation_carries_both_ends(self):
        """A warning naming only one side cannot be acted on."""
        edge = DependencyEdge(STRAHLEN, GRUNDIEREN)
        result = check_violation(edge, FRIDAY, FRIDAY, five_day_week)
        assert result is not None
        assert result.predecessor_id == STRAHLEN
        assert result.successor_id == GRUNDIEREN
        assert result.predecessor_end == FRIDAY
        assert result.successor_start == FRIDAY
