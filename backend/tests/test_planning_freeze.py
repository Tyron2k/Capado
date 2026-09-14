"""Tests for :mod:`app.services.planning_freeze`.

The rule that needs pinning is that a change has TWO states and both count. The plausible
implementation — check where the assignment ends up — passes every obvious test and still lets
somebody drag a frozen booking into the open period, rewriting frozen history through an edit
that looks entirely legitimate afterwards.

No database. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date

from app.services.planning_freeze import (
    Span,
    change_is_blocked,
    explain_block,
    touches_frozen_period,
)

FREEZE = date(2026, 8, 1)
FROZEN = Span(start=date(2026, 7, 10), end=date(2026, 7, 20))
OPEN = Span(start=date(2026, 9, 1), end=date(2026, 9, 10))
STRADDLING = Span(start=date(2026, 7, 25), end=date(2026, 8, 10))


class TestTouchesFrozenPeriod:
    def test_no_freeze_means_nothing_is_frozen(self):
        assert touches_frozen_period(FROZEN, None) is False

    def test_a_span_entirely_before_the_freeze_touches_it(self):
        assert touches_frozen_period(FROZEN, FREEZE) is True

    def test_a_span_entirely_after_does_not(self):
        assert touches_frozen_period(OPEN, FREEZE) is False

    def test_the_freeze_date_itself_is_editable(self):
        """freeze_before is exclusive — it names the first still-editable day, which is
        what somebody closing a period has in mind."""
        assert touches_frozen_period(Span(start=FREEZE, end=FREEZE), FREEZE) is False

    def test_the_day_before_is_frozen(self):
        day_before = date(2026, 7, 31)
        assert (
            touches_frozen_period(Span(start=day_before, end=day_before), FREEZE)
            is True
        )

    def test_a_straddling_span_touches_the_freeze(self):
        assert touches_frozen_period(STRADDLING, FREEZE) is True

    def test_a_span_without_a_start_is_treated_as_reaching_back(self):
        """Assuming the opposite would let a booking with unknown dates through the one
        check meant to be conservative."""
        assert touches_frozen_period(Span(start=None, end=OPEN.end), FREEZE) is True


class TestChangeIsBlocked:
    def test_an_edit_inside_the_open_period_is_allowed(self):
        assert change_is_blocked(OPEN, OPEN, FREEZE, is_admin=False) is False

    def test_an_edit_inside_the_frozen_period_is_blocked(self):
        assert change_is_blocked(FROZEN, FROZEN, FREEZE, is_admin=False) is True

    def test_creating_something_in_the_frozen_period_is_blocked(self):
        assert change_is_blocked(None, FROZEN, FREEZE, is_admin=False) is True

    def test_deleting_something_in_the_frozen_period_is_blocked(self):
        """A deletion of frozen work is a change to frozen history."""
        assert change_is_blocked(FROZEN, None, FREEZE, is_admin=False) is True

    def test_dragging_a_frozen_booking_into_the_open_period_is_blocked(self):
        """The case an "check the result" implementation gets wrong: afterwards the
        assignment sits entirely in the open period and looks legitimate, but frozen
        history was rewritten."""
        assert change_is_blocked(FROZEN, OPEN, FREEZE, is_admin=False) is True

    def test_dragging_an_open_booking_into_the_frozen_period_is_blocked(self):
        assert change_is_blocked(OPEN, FROZEN, FREEZE, is_admin=False) is True

    def test_editing_a_straddling_booking_is_blocked_entirely(self):
        """Including the part in the open period. A real restriction rather than an
        oversight: it is the only reading under which the frozen period is stable."""
        assert change_is_blocked(STRADDLING, STRADDLING, FREEZE, is_admin=False) is True

    def test_an_admin_is_never_blocked(self):
        """The audit log records what they did. Refusing everybody would make correcting
        a genuine data-entry error impossible."""
        assert change_is_blocked(FROZEN, FROZEN, FREEZE, is_admin=True) is False
        assert change_is_blocked(None, FROZEN, FREEZE, is_admin=True) is False

    def test_without_a_freeze_nothing_is_blocked(self):
        assert change_is_blocked(FROZEN, FROZEN, None, is_admin=False) is False

    def test_a_creation_with_no_state_at_all_is_allowed(self):
        """Degenerate input, but it must not be read as "block everything"."""
        assert change_is_blocked(None, None, FREEZE, is_admin=False) is False


class TestExplainBlock:
    def test_the_message_names_the_date_and_the_way_out(self):
        message = explain_block(FREEZE)
        assert "2026-08-01" in message
        assert "Administrator" in message
