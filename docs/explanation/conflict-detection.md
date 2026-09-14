# Conflict Detection

## Overview

Conflicts are detected server-side whenever assignments are created, updated, or
deleted. A conflict means demand exceeded the capacity a resource actually had
on a given day — not, as before, that allocations summed past a fixed 100%.
Capacity comes from `WorkingTimeService`; see
[capacity-model.md](capacity-model.md).

## Conflict Types

1. **Over-allocation (personal)** — demanded minutes exceed available minutes on
   one or more days. Demand comes from assignments, availability from week
   profile, site calendar, and absences.

2. **Time overlap (infrastructure)** — two or more bookings on the same
   infrastructure resource have overlapping time intervals (minute precision via
   `start_at` / `end_at`). Infrastructure is always 100% exclusive.

3. **Outside availability window (infrastructure)** — a booking falls partly or
   wholly outside every window defined for its weekday
   ([ADR-005](../decisions/005-infrastructure-availability-windows.md)). Carried
   by the `cause` discriminator on `Conflict`, which exists because a resolution
   that shifts a booking into a window is a different action from one that moves
   it to another resource — the two cannot share a conflict type without making
   the suggestion ambiguous.

   A resource that defines **no** windows produces no violations at all. That is
   the inverted default from ADR-005: no windows means available around the
   clock, so the first window added is a restriction.

## Detection Algorithm

### Personal Resources

- On assignment create/update/delete, `ConflictService` recalculates conflicts
  for the affected resource.
- A boundary sweep collects the start and end dates of all assignments and sorts
  them, producing spans within which the **active assignment set is constant**.
- Each span is then walked day by day, because capacity varies inside a span —
  a weekend, a holiday, or an absence changes availability without changing
  which assignments are active. For each day, demanded minutes are compared
  against available minutes.
- This is O(days + n log n): the active set and its assignment ids are resolved
  once per span rather than once per day. The earlier implementation evaluated
  each span once, which was cheaper but only correct while capacity was a
  constant.
- Absences are **not** demand intervals. They reduce availability, and
  `WorkingTimeService` owns that. Adding them here as well would count one absence
  twice.
- Non-working days produce no demand and therefore no conflict. A day fully covered by an absence
  does produce one: it is a working day with zero availability.
- Consecutive conflict days, or days sharing the same triggering assignments,
  are merged into a single conflict period.

### Infrastructure Resources

- Same boundary-sweep approach at the day level: for each span, count how many
  bookings are active. Two or more covering the same span produce a conflict
  (100% exclusive).
- A sweep-line helper (`_emit_infrastructure_period`) groups overlapping
  minute-precision intervals into conflict periods.
- Consecutive conflict days are merged into a single conflict period.
- Week profiles do not apply: infrastructure is exclusive rather than
  proportionally allocated.

## Conflict Storage

Conflicts are stored as `Conflict` rows with:

- `resource_id`, `resource_type`
- `start_date`, `end_date` (the conflict period)
- `total_assigned_percent` — peak demand during the period
- `available_percent` — availability on the day with the largest shortfall

Both percentages are **derived from minutes** so the API shape stayed stable
across the capacity rewrite. `available_percent` is therefore no longer always
100: a part-time resource reports its own day, and a day fully covered by an
absence reports zero.

`ConflictAssignment` join entries link to the involved assignments.

## Resolution Suggestions

`ConflictSuggestionService` analyzes each conflict and proposes concrete
actions:

| Type | Description |
|------|-------------|
| `shift_forward` | Move assignment N days forward past the conflict |
| `shift_backward` | Move assignment N days backward before the conflict |
| `reduce_allocation` | Lower allocation_percent to fit within available time |
| `swap_resource` | Move assignment to a skill-matched resource with capacity |

Swap suggestions use work package requirements (`work_package_requirements`) to
find resources with matching skills. If no requirements are defined, it falls
back to the skills of the currently assigned resource.

The suggestion service resolves capacity through `WorkingTimeService` and converts with
`percent_to_minutes`, so a `reduce_allocation` proposal is checked against the minutes the resource
actually has. A suggestion for a part-time resource therefore proposes a value that fits, rather than
one that merely lands below 100.

## Severity Levels

| Level | Condition |
|-------|-----------|
| Low | Total ≤ 125% |
| Medium | 125% < Total ≤ 150% |
| High | Total > 150% |

The percentages are relative to available capacity, so a part-time resource
booked at a full normative day lands in Low rather than reading as if nothing
were wrong.

## UI Integration

- Conflicts are shown inline on the **Planning** page (Overview tab).
- Each conflict card shows conflict periods, involved assignments, and
  resolution suggestions.
- Suggestions can be applied with a single click (reduce, swap) or shown as
  hints (shift).
- Deep-links allow navigating from conflict cards to the Gantt view.
