# ADR-004: Hours as the Capacity Base, Percent as the Display Unit

## Status

Accepted

## Context

Today `allocation_percent` is the only unit in the system. It is a percentage
of an implicit base that is never defined: `docs/explanation/capacity-model.md`
states that every calendar day carries 100% capacity, weekends and holidays
included. Three consequences follow.

The arithmetic is wrong for any real operation. Counting Sunday as a full day
overstates capacity by roughly 28% on a five-day week, more once public
holidays are added, so a plan the system reports as feasible is not.

The unit cannot be reconciled with anything outside the tool. "50%" of an
undefined base cannot be compared against a quotation calculation, which is
denominated in hours or man-days.

And percent has no path to money. A cost dimension (rate, cost centre,
project budget) needs a quantity to multiply, and a percentage of an unknown
day is not one.

Part-time is currently modelled as an `Absence` with `reason=part_time`. That
is semantically wrong — a 30-hour employee is not absent — and structurally
unable to express a weekly pattern such as "Mon–Thu full, Fri off", because an
absence has a date range, not a weekday shape.

## Decision

**Hours become the arithmetic base. Percent remains the authoring and display
unit.**

### The unit of demand

`allocation_percent` is a percentage **of a normative working day**, not of
the individual resource's own capacity. The normative day is a single
constant — `NORMATIVE_DAY_MINUTES = 480` in `working_time_service`, imported by every
service that converts between the two units. It is **not** operator-configurable; see
[Resolved since](#resolved-since).

This was chosen over "percent of the resource's own capacity" because it makes
over-commitment visible instead of silent. Assigning a 30 h/week employee
(360 min/day) at 100% demands 480 min against 360 available and is reported as
a conflict — which is the truth. Under the alternative semantics the same
assignment would silently mean "3 h", and the planner would never learn that
the work does not fit.

### Supply

- `WorkWeekProfile` carries available minutes per weekday, named and reusable
  ("Standard 5-day 8 h", "Part-time 30 h Mon–Thu"). Assigned to a resource
  with a validity range, so a contract change is a new row rather than an
  edit that rewrites history.
- Public holidays live in an explicit `holidays` table scoped to a `Site`
  (see ADR-003). No runtime dependency on a holiday library: the table is the
  source of truth, so company shutdowns and bridge days are expressible with
  the same mechanism, and every deviation is auditable. An optional seed
  script pre-fills a year for a region; keeping the data in the database means
  a wrong entry is corrected by an operator, not by a dependency bump.
- A holiday row carries `working_minutes` (default 0). This makes half-days
  — 24 and 31 December in most German firms — a normal case rather than a
  special one, and allows a designated working Saturday as a positive
  exception.
- `capacity(resource, day)` is the profile's minutes for that weekday,
  overridden by a holiday row when one exists for the resource's site.

### Non-working days carry no demand

An assignment consumes capacity **only on days where `capacity(day) > 0`**.

This rule is what makes the semantics above usable. Assignments are date
ranges and naturally span weekends; without the rule, an assignment from the
1st to the 30th would raise a conflict on every Saturday and Sunday, and the
feature would drown the plan in noise on day one.

The cost of the rule is that work assigned across a holiday quietly delivers
less time than the planner assumed. That is a **shortfall**, not a capacity
conflict, and belongs to the unmet-requirements surface rather than to
conflict detection — a later phase.

### Storage

**Time is stored as integer minutes, not float hours.** Conflict detection
sums allocations across long date ranges; binary floating point drifts under
repeated addition, and a capacity check is an equality-adjacent comparison
where drift turns into a phantom conflict or a missed one. Integer minutes
make the arithmetic exact. The existing `allocation_percent` stays `FLOAT`
because it is an input, not an accumulator.

## Consequences

- No UI regression: users continue to think and enter in percent.
- Over-allocation becomes expressible in absolute time, which is what a
  decision about overtime, external capacity, or cost actually needs.
- The later cost dimension is additive rather than a second rewrite of the
  same arithmetic.
- `part_time` absences move into week profiles. `AbsenceReason.part_time` is
  removed, because leaving it in place would offer two contradictory ways to
  model the same fact.
- Every stored `Conflict` row becomes invalid on rollout and must be
  recomputed; `app/scripts/refresh_conflicts.py` already exists for exactly
  this and is the documented rollout step.
- Resources without a week profile fall back to a configured default profile
  (standard five-day week), otherwise a fresh install would report zero
  capacity everywhere and detect no conflicts at all.
- Conflict rows keep `total_assigned_percent` / `available_percent` for
  backwards compatibility of the API, but both are now derived from minutes:
  `assigned_minutes / capacity_minutes * 100`. Absolute minute fields are
  added alongside so the UI can show hours where hours are the useful unit.

---

## Resolved since

Appended rather than edited, for the reason given in ADR-006's note of the same name. Verified against
the code.

**Landed as decided.** `WorkWeekProfile` carries minutes per weekday. `holidays` is scoped to a site
with a `(site_id, day)` constraint and carries `working_minutes`, so a half-day is expressible.
`Conflict` still keeps its percent columns for display. `app/scripts/refresh_conflicts.py` exists.

**One word was wrong, and it matters to an operator.** The decision text called the normative day a
"configured constant (default 480 minutes)". It is a module-level constant, `NORMATIVE_DAY_MINUTES`,
with no setting and no column behind it — an operator whose normal day is 7.5 hours **cannot** change
it, and reading "configured" would have sent them looking for a switch that does not exist. The
constant is imported by `conflict_service`, `capacity_service`, `conflict_suggestion_service` and
`working_time_service`, so changing it is a code change with the whole conversion surface behind it.

Note what this does *not* break: a 7.5-hour employee is still modelled correctly, through their week
profile's available minutes. The normative day is only the denominator that gives `allocation_percent`
a fixed meaning, which was the point of choosing it over "percent of the resource's own capacity".

**`AbsenceReason` went further than this ADR states.** The consequence above records only that
`part_time` was removed. The enum now holds `planned` / `unplanned` and nothing else: the
cause-naming values went too, because `sick` made the column an Art. 9 GDPR special category the
capacity arithmetic never read. See ADR-009 and the compliance document.
