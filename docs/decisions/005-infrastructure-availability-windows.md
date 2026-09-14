# ADR-005: Availability Windows for Infrastructure Resources

## Status

Accepted

## Context

Infrastructure resources (halls, tracks, crane bays, cabins, machines) are
booked with minute precision via `start_at` / `end_at` and treated as 100%
exclusive: any two overlapping bookings on the same resource are a conflict.

That model knows only exclusivity, not opening hours. A booking on Sunday at
03:00 is accepted, and the plan looks feasible even when nobody is on site and
the hall is locked. ADR-004 introduces working-time capacity for personal
resources; leaving infrastructure as pure wall-clock exclusivity would mean a
work package whose people are correctly limited to working hours can still be
scheduled onto a machine at a time that machine is never operated.

Infrastructure cannot simply reuse `WorkWeekProfile`, because it carries no
`allocation_percent`: the question is not "how much of the day" but "which
clock windows on which weekday".

## Decision

**Infrastructure resources get their own availability windows.**

`InfrastructureAvailabilityWindow` binds a resource to a weekday and a clock
interval (`weekday`, `start_time`, `end_time`). Several windows per weekday
are allowed, which is how a two-shift or three-shift operation is expressed
(06:00–14:00 and 14:00–22:00 as two rows rather than one artificial span).

A booking that falls partly or wholly outside every window for its weekday is
a conflict of its own kind, distinct from an overlap with another booking.
Holidays from the site calendar (ADR-004) suppress all windows for that date;
a holiday row with `working_minutes > 0` does **not** re-open a window, because
a half-day is a statement about people, not about which clock hours a machine
runs.

**A resource with no windows defined is available at all times.** This keeps
the current behaviour as the default, so introducing the table changes no
existing plan until an operator opts in by defining windows.

## Shifts crossing midnight

A window whose `end_time` is **before** its `start_time` runs past midnight. It
contributes `[start, 24:00)` to its own weekday and `[00:00, end)` to the next
one, so a night shift is one row — `weekday=0, 22:00, 06:00` — rather than two
that a reader has to mentally join.

The first version of this ADR enforced `end_time > start_time` and recorded the
resulting inability to model a night shift as a known limitation. That was the
wrong trade: the tool is built first for one plant but the model has to stay
general, and a three-shift operation is ordinary rather than exotic. Migration
006 replaces the constraint with `end_time <> start_time`; equal times stay
rejected because they are ambiguous, not useful.

Existing rows are unaffected — every one satisfies `end_time > start_time` and
keeps its meaning. The new reading only adds a case that could not be stored
before, which is why no data migration is needed.

**The tail belongs to the day the shift started.** A site holiday on Monday
cancels a Monday-night shift including its Tuesday-morning hours, because a
holiday cancels a shift and the small hours after midnight belong to the shift
that began the evening before. Attributing the tail to Tuesday instead would let
a holiday cancel half a shift and leave the rest standing.

The downgrade path deletes wrapping rows: the older shape has no representation
for them, so a downgrade of a schema carrying night shifts loses them.

## Consequences

- Two distinct infrastructure conflict causes now exist: double booking
  (existing) and booking outside availability (new). `Conflict.cause` names
  which one fired, otherwise the resolution suggestions cannot propose the right
  fix — shifting into a window is a different action from moving to another
  resource.
- The existing sweep-line overlap detection is unchanged. Window violation is
  a separate, per-booking check, which keeps it out of the O(n log n) overlap
  path.
- Callers ask `covered_spans` / `covered_minutes_within` rather than reading
  windows directly, because a wrapping window is not answerable from its own row
  alone — the previous day's rows matter too.
- Time zones are deliberately out of scope: windows are local clock times and
  the deployment is one company, so a single local timezone is assumed. A
  multi-site operator spanning timezones would need this revisited.
- Suggestions gain a `shift_into_window` strategy. Until it exists, a window
  violation is reported without an automatic fix. **It exists now — see
  [Resolved since](#resolved-since).**
- Seed data and the import path must tolerate resources without windows,
  since that is the default state.

---

## Resolved since

Appended rather than edited, for the reason given in ADR-006's note of the same name.

**`shift_into_window` exists.** `ConflictSuggestionService._suggest_shift_into_window` returns a
suggestion of type `shift_into_window` carrying an explicit target timestamp, so a window violation
is no longer reported without an automatic fix. The consequence above described the interim state.

Detection landed too: `ConflictService._detect_window_violations` finds bookings outside every window,
and `Conflict.cause` carries the discriminator this ADR asked for. A resource with no windows still
produces no violations — the inverted default is intact.
