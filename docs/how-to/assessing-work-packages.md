# Assess a work package

Open **Planning → Overview**, then select an active work package under
**Work package readiness**. The picker includes unfinished packages whose end
date has not passed, including packages with no reported problems.

The selected view brings together three checks:

- **Personnel coverage and capacity:** daily qualified headcount or effort-FTE
  coverage, plus capacity conflicts for the assigned people.
- **Equipment coverage and bookings:** qualified booked equipment, timestamp
  overlaps and operating-window violations.
- **Assignment qualifications:** whether each assignment satisfies at least one
  applicable package requirement, including minimum level and full-period validity.

These use the existing requirement, qualification, working-time and conflict
rules. Selecting a package performs read-only checks; it does not save conflicts,
reserve capacity or modify assignments.

## Read the result

**No blockers within scope** means the applicable, defined checks found no known
blockers. It is reachable even when informational precision notes apply.
**Missing requirements**
means qualifying booking coverage is insufficient. **Conflicting** identifies a
known capacity, booking or qualification blocker. **Not fully assessable** means
necessary evidence is missing or a check could not run. Qualification checks are
incomplete when there are no bookings to examine. An unused resource domain without
requirements is shown as undefined and does not prevent a successful result for
the defined scope. Known blockers remain visible even when another check is
incomplete.

The scope notice explains the limits that apply to this package. In particular:

- Date/percentage personnel bookings cannot establish attendance during a
  particular machine shift.
- Equipment requirement coverage counts qualified booked resources; it does not
  establish continuous equipment coverage throughout the package.
- An absent requirement definition does not establish that no resources are needed.
- A missing standard work-week profile prevents daily personnel coverage assessment.
- A booked person can have zero individual calendar capacity on a standard-profile
  workday. This supply loss is shown separately, even when calendar-gated demand
  produces no stored over-allocation conflict.

See [combined planning guarantees](../explanation/combined-planning.md) for the
underlying contracts and synthetic examples.

## Act on a blocker

For a missing requirement, expand its existing requirement card and preview a
qualified resource suggestion. Confirming the preview saves the assignment;
opening or cancelling it does not. The preview is an estimate, not a reservation.

Each conflict card combines suggestions for its involved bookings, with the fewest
remaining capacity/booking conflicts first. The list shows the number remaining
and the count before the change, using the ordinary preview calculation. Counts
cover the affected resources and old/proposed periods, not a full project verdict.
An unassessable effect is marked explicitly and sorted last. Opening the preview
checks the current data again; it can differ after concurrent changes.

Before confirming a suggestion, review the **Proposed change** comparison. It shows
resource, start/end and personnel allocation before and after, and marks unchanged
values. Equipment bookings include exact clock times, UTC offsets, the display time
zone and elapsed duration. A new booking is identified explicitly with its complete
proposed period and allocation. The conflict impact is shown separately below. The
comparison uses the same proposal sent for preview and saved on confirmation.

For a qualification blocker, expand the existing resource problem card to inspect
the booking and qualified alternatives. The rule covers the whole booking period,
not just the first day.

For a capacity conflict, machine overlap or operating-window violation, preview
one of the suggested changes directly in the assessment. Suggestions are computed
from current bookings and do not depend on saved conflict records. Replacement
resources keep the original resource type and must satisfy an applicable role,
minimum level and validity for the full booking, with room for that interval.
Operating-window moves search the nearest free continuous span within the package,
up to 30 days either side of the original start; overnight spans are joined and
competing bookings excluded. No fitting alternative produces an explanation; a
failed request instead offers a retry.

To edit manually, choose **Review all resource bookings**. This opens the existing Assignments tab filtered
by resource, retaining competing bookings from other packages. Edit the relevant
booking through the normal form. **Review package bookings** instead restricts the
list to this package. **Show all bookings** clears the contextual filter.

Return to Overview to inspect the updated result. No corrective action is applied
merely by opening the assessment or following a link.

## Freshness and large periods

The displayed timestamp is the completion time of a direct check against recorded
inputs. The selected package is checked again every minute while the view is
active; **Check again** requests a new check immediately. A running or failed
refresh does not display an old positive verdict as current evidence. Other users
can change the plan during or after a check; recheck after concurrent edits.

The general stored conflict list is reconciled separately. It can temporarily
differ from this direct assessment after a failed or delayed reconciliation.

Interactive capacity and occupancy checks cover at most **366 calendar days**,
including the package dates and its actual booking span. Longer spans explicitly
remain incompletely checked; efficient requirement and qualification checks still
report any known failures. Competing bookings are included, but their historical
or future tails do not expand the selected check's window.
