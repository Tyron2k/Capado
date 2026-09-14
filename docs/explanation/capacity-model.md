# Capacity Model

## Overview

Capacity is working time. It comes from a week profile, is corrected by the
site calendar, and is reduced by absences. It is stored and computed in
**integer minutes**; percent is what users type and read.

This replaced a model in which every calendar day carried 100% capacity,
weekends and holidays included. That overstated a five-day week by roughly 28%,
so plans the system called feasible were not. See
[ADR-004](../decisions/004-hours-as-capacity-base.md).

## Three layers, deliberately separate

Conflating these is the mistake the code is arranged to prevent.

| Layer | Question it answers | Source |
|-------|--------------------|--------|
| **Calendar minutes** | What does the working week grant on this date? | `WorkWeekProfile`, overridden by a `holidays` row for the resource's site |
| **Available minutes** | What is actually left after absences? | Calendar minutes minus absences |
| **Demand minutes** | What do assignments ask for? | `allocation_percent` against a normative day |

`WorkingTimeService` owns all three. Both `CapacityService` (what the dashboard
shows) and `ConflictService` (what the planning page flags) resolve capacity
through it, so they cannot report contradicting states for the same day.

## The unit of demand

`allocation_percent` is a share of a **normative working day** — 480 minutes by
default — not of the individual resource's own capacity.

This makes over-commitment visible instead of silent. Assigning a 30 h/week
employee (450 minutes on a working day) at 100% demands 480 minutes against 450
available, and is reported as a conflict. Under the alternative reading the same
assignment would quietly mean "7.5 hours" and the planner would never learn that
the work does not fit.

## Absences reduce supply, they do not add demand

An absence is a share of the resource's **own** day. A full day of leave removes
450 minutes from a 7.5-hour resource and 480 from a full-time one.

Absences are therefore never summed into demand. Doing both would count one
absence twice — once against supply, once as load — which is what the previous
model did.

An absence records only whether it was `planned` or `unplanned`, never a cause: the cause was removed
because `sick` is health data under Art. 9 GDPR, and the capacity calculation never needed it — only
period and share enter it.

Part-time is **not** an absence, and the shape of the data says why: an absence
has a date range, so it could never express "Mon–Thu full, Fri off". Part-time
lives in `WorkWeekProfile`.

## Non-working days carry no demand

An assignment consumes capacity **only on days where calendar minutes > 0**.

Assignments are date ranges and naturally span weekends. Without this rule an
assignment from the 1st to the 30th would raise a conflict on every Saturday and
Sunday, and the feature would drown the plan in noise on day one.

The rule is gated on **calendar** minutes, not on available minutes, and that
distinction carries the three cases the model must tell apart:

| Situation | Calendar | Available | Demand at 100% | Result |
|-----------|---------:|----------:|---------------:|--------|
| Sunday | 0 | 0 | 0 | no conflict |
| Public holiday | 0 | 0 | 0 | no conflict, but a shortfall |
| Absence, full day | 480 | 0 | 480 | **conflict** — "on leave but assigned" |
| Part-time, booked full | 450 | 450 | 480 | **conflict** — does not fit |
| Full-time, booked full | 480 | 480 | 480 | no conflict |

The holiday row is the cost of this rule: work assigned across it delivers less
time than the planner assumed. That is a *shortfall*, not an over-allocation,
and belongs to the unmet-requirements surface rather than to conflict detection.

## Calendar exceptions

A `holidays` row overrides the week profile for one site and one date, and
carries `working_minutes` rather than a boolean:

- `0` — public holiday, company shutdown, bridge day.
- between zero and the profile — a half day, as 24 and 31 December usually are.
- greater than zero on a day the profile calls free — a designated working
  Saturday, which real plant calendars do contain.

Holidays are an explicit table, not a library lookup. Real plant calendars treat
days such as Rosenmontag as non-working even where they are not statutory
holidays; a library would have reported capacity that does not exist. An
optional seed script pre-fills a year, but the table stays the source of truth.

## Utilization

```
utilization(resource, day) = demand_minutes / available_minutes
```

A resource with a 7.5-hour day, fully booked, reads 100% — utilization is a
statement about that resource, not about a normative day. Where availability is
zero and demand is not, utilization is reported as over-allocated rather than
divided by zero.

Weekly aggregation counts only days the calendar grants time. Counting all seven
is where the systematic overstatement came from.

## Infrastructure capacity

Infrastructure resources are booked with minute precision (`start_at` /
`end_at`) and are 100% exclusive: any overlap between two bookings on the same
resource is a conflict. They are not proportionally allocated, so the week
profile does not apply to them.

Instead they may carry availability windows — clock intervals per weekday, one
row per shift. A resource with **no** windows is available around the clock,
which preserves the behaviour that existed before windows were introduced. See
[ADR-005](../decisions/005-infrastructure-availability-windows.md).

## Dashboard visualization

The dashboard shows weekly utilization as stacked bar charts:

- **Teal segment** — utilization within available capacity.
- **Red segment** — the overbooked portion, i.e. demand beyond availability.

Both are derived from minutes and expressed as percentages of the available
time, so a peak week reads the same whether it is staffed by full-time or
part-time people.
