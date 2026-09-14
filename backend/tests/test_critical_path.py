"""Tests for :mod:`app.services.critical_path`.

A critical path is easy to compute and easy to compute *plausibly wrong*: the numbers look
reasonable either way, so the tests here pin the specific decisions rather than the shape of
the output.

The three that matter: duration comes from the lead time when it exists, the backwards pass
starts from the commitment when there is one, and float is counted in working days.

Pure over an ``is_working_day`` predicate. No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.services.critical_path import ScheduleNode, analyse, duration_working_days
from app.services.dependencies import DependencyEdge

A = UUID("aaaaaaaa-0000-0000-0000-000000000001")
B = UUID("aaaaaaaa-0000-0000-0000-000000000002")
C = UUID("aaaaaaaa-0000-0000-0000-000000000003")

# 2026-06-01 is a Monday.
MON1 = date(2026, 6, 1)
FRI1 = date(2026, 6, 5)
MON2 = date(2026, 6, 8)
FRI2 = date(2026, 6, 12)
FRI3 = date(2026, 6, 19)


def five_day_week(day: date) -> bool:
    """Monday to Friday are working days."""
    return day.weekday() < 5


def never(_day: date) -> bool:
    """A calendar with no working days at all."""
    return False


def _node(
    node_id: UUID,
    name: str,
    start: date,
    end: date,
    lead: int | None = None,
) -> ScheduleNode:
    return ScheduleNode(
        id=node_id,
        name=name,
        start_date=start,
        end_date=end,
        lead_time_working_days=lead,
    )


class TestDuration:
    """Where the length of a package comes from."""

    def test_the_lead_time_wins_over_the_entered_span(self):
        """The lead time describes the WORK; the dates describe the schedule.

        A package booked across three weeks for five days of work has float that a
        span-based duration would hide.
        """
        node = _node(A, "Strahlen", MON1, FRI3, lead=5)
        assert duration_working_days(node, five_day_week) == 5

    def test_without_a_lead_time_the_span_is_used(self):
        node = _node(A, "Strahlen", MON1, FRI1)
        assert duration_working_days(node, five_day_week) == 5

    def test_a_weekend_inside_the_span_does_not_count(self):
        node = _node(A, "Strahlen", MON1, MON2)
        assert duration_working_days(node, five_day_week) == 6

    def test_a_span_with_no_working_day_still_lasts_one(self):
        """Zero would let a package finish before it starts."""
        node = _node(A, "Strahlen", date(2026, 6, 6), date(2026, 6, 7))
        assert duration_working_days(node, five_day_week) == 1

    def test_a_zero_lead_time_is_ignored_in_favour_of_the_span(self):
        node = _node(A, "Strahlen", MON1, FRI1, lead=0)
        assert duration_working_days(node, five_day_week) == 5


class TestForwardPass:
    """Earliest dates, and how a dependency pushes them."""

    def test_a_lone_package_starts_on_its_own_date(self):
        result = analyse([_node(A, "Strahlen", MON1, FRI1)], [], FRI1, five_day_week)
        assert result[0].earliest_start == MON1
        assert result[0].earliest_finish == FRI1

    def test_a_successor_is_pushed_past_its_predecessor(self):
        """Even when its own entered start is earlier."""
        nodes = [
            _node(A, "Strahlen", MON1, FRI1, lead=5),
            _node(B, "Grundieren", MON1, FRI2, lead=5),
        ]
        edges = [DependencyEdge(A, B)]
        result = {r.id: r for r in analyse(nodes, edges, FRI2, five_day_week)}
        assert result[B].earliest_start == MON2

    def test_a_lag_pushes_it_further(self):
        nodes = [
            _node(A, "Strahlen", MON1, FRI1, lead=5),
            _node(B, "Grundieren", MON1, FRI3, lead=5),
        ]
        edges = [DependencyEdge(A, B, lag_working_days=2)]
        result = {r.id: r for r in analyse(nodes, edges, FRI3, five_day_week)}
        assert result[B].earliest_start == date(2026, 6, 10)

    def test_the_latest_predecessor_governs(self):
        """Two predecessors: the successor waits for the slower one."""
        nodes = [
            _node(A, "Kurz", MON1, MON1, lead=1),
            _node(B, "Lang", MON1, FRI1, lead=5),
            _node(C, "Danach", MON1, FRI2, lead=3),
        ]
        edges = [DependencyEdge(A, C), DependencyEdge(B, C)]
        result = {r.id: r for r in analyse(nodes, edges, FRI3, five_day_week)}
        assert result[C].earliest_start == MON2


class TestFloatAndCriticality:
    """The output people act on."""

    def test_a_chain_that_exactly_fills_the_deadline_is_all_critical(self):
        nodes = [
            _node(A, "Strahlen", MON1, FRI1, lead=5),
            _node(B, "Grundieren", MON2, FRI2, lead=5),
        ]
        edges = [DependencyEdge(A, B)]
        result = analyse(nodes, edges, FRI2, five_day_week)
        assert all(r.is_critical for r in result)
        assert all(r.float_working_days == 0 for r in result)

    def test_slack_appears_when_the_deadline_is_later(self):
        nodes = [
            _node(A, "Strahlen", MON1, FRI1, lead=5),
            _node(B, "Grundieren", MON2, FRI2, lead=5),
        ]
        edges = [DependencyEdge(A, B)]
        result = analyse(nodes, edges, FRI3, five_day_week)
        assert all(r.float_working_days == 5 for r in result)
        assert not any(r.is_critical for r in result)

    def test_a_short_parallel_branch_has_float_while_the_long_one_does_not(self):
        """The point of the whole analysis: which of two parallel paths matters."""
        nodes = [
            _node(A, "Lang", MON1, FRI2, lead=10),
            _node(B, "Kurz", MON1, MON1, lead=1),
        ]
        result = {r.id: r for r in analyse(nodes, [], FRI2, five_day_week)}
        assert result[A].is_critical is True
        assert result[B].is_critical is False
        assert result[B].float_working_days == 9

    def test_float_is_negative_when_the_deadline_is_unreachable(self):
        """Not clamped to zero: "three days short" is actionable, "critical" is not."""
        nodes = [_node(A, "Strahlen", MON1, FRI2, lead=10)]
        result = analyse(nodes, [], FRI1, five_day_week)
        assert result[0].float_working_days < 0
        assert result[0].is_critical is True

    def test_float_is_counted_in_working_days(self):
        """A weekend in the gap is not slack anybody can use."""
        nodes = [_node(A, "Strahlen", MON1, MON1, lead=1)]
        result = analyse(nodes, [], MON2, five_day_week)
        # Monday 1st to Monday 8th spans two weekends' worth of calendar days but only
        # five working days of slack.
        assert result[0].float_working_days == 5


class TestEdges:
    """Shapes that must not produce nonsense."""

    def test_no_nodes_yields_no_analysis(self):
        assert analyse([], [], FRI1, five_day_week) == []

    def test_a_broken_calendar_yields_no_analysis(self):
        """Reporting float against a calendar with no working days would mislead."""
        nodes = [_node(A, "Strahlen", MON1, FRI1, lead=5)]
        assert analyse(nodes, [], FRI1, never) == []

    def test_edges_pointing_outside_the_node_set_are_ignored(self):
        """A dependency may cross project boundaries; the pass must not break on it."""
        nodes = [_node(B, "Grundieren", MON1, FRI1, lead=5)]
        edges = [DependencyEdge(A, B)]
        result = analyse(nodes, edges, FRI1, five_day_week)
        assert len(result) == 1
        assert result[0].earliest_start == MON1

    def test_a_cycle_terminates_and_still_reports_every_node(self):
        """Refused at the write, but corrupt data must degrade rather than hang."""
        nodes = [
            _node(A, "Eins", MON1, FRI1, lead=5),
            _node(B, "Zwei", MON1, FRI1, lead=5),
        ]
        edges = [DependencyEdge(A, B), DependencyEdge(B, A)]
        result = analyse(nodes, edges, FRI2, five_day_week)
        assert len(result) == 2

    def test_the_result_order_matches_the_input_order(self):
        """Callers zip this against their own list."""
        nodes = [
            _node(C, "Drei", MON1, FRI1, lead=5),
            _node(A, "Eins", MON1, FRI1, lead=5),
        ]
        result = analyse(nodes, [], FRI2, five_day_week)
        assert [r.id for r in result] == [C, A]
