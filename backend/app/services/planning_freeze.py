"""Whether a change reaches into a period that has been frozen.

A plan that has already been reported on should not change underneath the report. Capado can
already record what the plan looked like (baselines) and who changed it (the audit log), but
neither prevents somebody quietly moving last month's assignment so this month's numbers add
up. The freeze is the preventive half of that pair.

**The non-obvious part is that a change has two states, and both count.** Checking only where
an assignment ends up would let somebody drag a frozen booking out of the frozen period — the
edit is then entirely in the open period while having rewritten frozen history. So the check
takes the state before AND after, and blocks if EITHER touches the freeze. The consequence is
worth stating plainly: an assignment straddling the boundary cannot be edited at all while
the freeze stands, not even the part of it that lies in the open period. That is a real
restriction rather than an oversight, and it is the only reading under which the frozen period
is actually stable.

Admins can override, and the override is what the audit log is for. The alternative — nobody
can, ever — makes correcting a genuine data-entry error impossible, which turns the freeze
from a safeguard into a trap. Making it advisory for everybody would make it decoration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Span:
    """A booking's date range. Either bound may be missing.

    Infrastructure bookings are stored with datetimes rather than dates and personnel
    bookings with dates (see known-limitations: two booking models in one table), so a
    caller may legitimately have only one bound or neither.
    """

    start: date | None
    end: date | None


def touches_frozen_period(span: Span, freeze_before: date | None) -> bool:
    """Whether any part of the span lies strictly before the freeze date.

    ``freeze_before`` is EXCLUSIVE: it names the first still-editable day. Expressing it
    that way rather than as "last frozen day" means moving the freeze forward by a month is
    setting it to the first of that month, which is what somebody closing a period actually
    has in mind.

    A span with no start is treated as reaching back indefinitely, so it touches any freeze.
    Assuming the opposite would let a booking with unknown dates through the one check meant
    to be conservative.
    """
    if freeze_before is None:
        return False
    if span.start is None:
        return True
    return span.start < freeze_before


def change_is_blocked(
    before: Span | None,
    after: Span | None,
    freeze_before: date | None,
    is_admin: bool,
) -> bool:
    """Whether this change must be refused.

    ``before`` is None for a creation, ``after`` is None for a deletion. Both states are
    tested: a deletion of frozen work is a change to frozen history, and so is dragging a
    frozen booking into the open period.

    Admins are never blocked. The audit log records what they did.
    """
    if is_admin or freeze_before is None:
        return False
    return any(
        touches_frozen_period(span, freeze_before)
        for span in (before, after)
        if span is not None
    )


def explain_block(freeze_before: date) -> str:
    """The message a blocked user sees.

    Names the date and who can override, because a refusal that explains neither leaves the
    user with no next step except asking around.
    """
    return (
        f"Die Planung ist bis zum {freeze_before.isoformat()} gesperrt "
        f"(erster änderbarer Tag: {freeze_before.isoformat()}). "
        f"Änderungen in diesem Zeitraum kann nur ein Administrator vornehmen."
    )
