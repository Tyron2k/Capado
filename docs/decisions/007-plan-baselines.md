# ADR-007: Plan Baselines

## Status

Accepted

## Context

There is no way to freeze a plan and compare against it. Without one there is no
plan-versus-actual deviation, only a picture that is always current and therefore
always right. "We are three weeks behind" is unprovable, and so is its opposite.

ADR-006's audit trail answers *why* something changed — who moved it, when, and
with what stated reason. It cannot answer *what the plan was*: replaying a
thousand entries to reconstruct a state is not a report anybody runs. The two are
complementary, and both are needed for a deviation to be actionable.

## Decision

### A baseline snapshots the schedule, not the world

Captured: **projects**, **work packages**, **assignments**.

Excluded, and the reason matters more than the list:

- **Absences** are facts about people, not statements about the plan. A vacation
  appearing after the freeze is not plan drift, it is reality; its effect on the
  plan surfaces as a conflict or as an assignment that someone moved, and that
  movement *is* captured.
- **Working-time configuration** — week profiles, holidays, availability windows —
  is the calendar, for the same reason. A bridge day added in December did not
  change the plan; it changed what the plan runs against.
- **Requirements** are scope rather than schedule. A requirement changing means
  the plan needs different people, which is arguably drift, but it is
  second-order: the first question is always "did the dates and the staffing
  move". This is named as the most likely first extension, and the storage shape
  below makes adding it a zero-migration change.

A snapshot that captures everything is a database copy, and one that captures too
little cannot explain a slip. This is the line: what a planner *decided*, not what
the world did to them.

### One generic entry table, diffed in Python

`baselines` holds the header; `baseline_entries` holds one row per captured
entity as `(baseline_id, entity_type, entity_id, payload)` with the payload as
JSON.

Typed tables per entity — `baseline_assignments`, `baseline_work_packages` — would
allow comparing `start_date` in SQL. They were rejected for the same reason as in
ADR-006: three tables and three migrations now, plus another one for every entity
that later becomes part of the plan. With the generic shape, adding requirements
is a change to one function.

Replaying the audit log to reconstruct state was rejected outright. It is smaller
on disk, but the log deliberately omits derived state and excludes the conflict
tables, so a replay would produce something that is *nearly* the old plan — the
worst possible property for a document meant to settle disagreements.

The diff is computed in Python as a set comparison over dicts, and it is a pure
function so it is testable without a database. Volume makes this safe: the reference
seed carries roughly 1,600 assignments, so a monthly baseline is roughly twenty
thousand rows a year.

### A baseline is a marker, not a lock

Creating a baseline does not prevent edits.

The original gap analysis asked for a planning freeze, and this deliberately does
not deliver one. A hard lock on a live production plan is worse than no lock: the
plant does not stop because a plan was agreed, so the schedule has to stay
editable. A tool that refuses the edit does not prevent the change — it moves the
change into a spreadsheet, and then the plan and reality diverge invisibly, which
is precisely the failure the baseline exists to expose.

What the request was actually reaching for is not prevention but visibility. The
diff against the agreed plan is the deliverable. One baseline is marked current so
that drift can always be shown without the user having to pick a comparison point.

## Retention

Baselines have their own retention period, and it is **disabled by default** — the
opposite of the audit log's 24 months.

The asymmetry is the point. An audit entry accumulates as a side effect of working;
nobody decided to create it, so deleting it after a period costs nothing and satisfies a
privacy interest. A baseline is the reverse: somebody deliberately froze the plan because
that state mattered, usually a sign-off. Deleting the state a commitment was measured
against is destructive in a way an expired audit row is not, so it has to be chosen
rather than inherited.

The baseline marked ``is_current`` is exempt regardless of age. It is what drift is
measured against, and removing it would turn every "the plan has not moved" answer into
"there is nothing to compare with" — a comparison tool that quietly stops comparing.

Manual deletion stays the normal path for a baseline that is simply no longer wanted.
Retention exists for the case where an operator has an obligation covering the people
named inside the snapshots, not as routine housekeeping.

## Consequences

- Creating a baseline is a bulk insert of one row per assignment, work package and
  project. It is a write, so it appears in the audit trail — which is correct: who
  froze the plan and when is exactly the kind of thing that gets disputed.
- `baseline_entries` rows are immutable. Nothing edits a snapshot; a wrong
  baseline is superseded by a new one, not corrected. Correcting history would
  destroy the only reason to keep it.
- Deleting a baseline cascades to its entries, because a header without its rows
  is not a partial baseline, it is a lie.
- An entity created after the baseline appears in the diff as *added*, and one
  deleted as *removed*. Neither is an error state; both are the answer.
- The payload is a snapshot of field values, so a schema change makes old payloads
  describe a shape that no longer exists. The diff compares field by field on keys
  present in both, so an added column shows up as *added in current* rather than
  crashing. A removed column silently stops being compared, which is the honest
  behaviour — the old value is not wrong, it is no longer meaningful.
- Retention is unsolved, as with the audit trail, and for the same reason: a
  baseline naming a person is personal data and belongs with the GDPR work.
  **The mechanism now exists — see [Resolved since](#resolved-since). Pruning is still off by
  default, so the practical effect described here is unchanged.**

---

## Resolved since

Appended rather than edited, for the reason given in ADR-006's note of the same name.

- **"Retention is unsolved, as with the audit trail."** Baseline retention is now a setting
  (`organization_settings.baseline_retention_months`) with a dedicated service. It **defaults to `0`,
  meaning keep everything** — so the consequence above still describes the out-of-the-box behaviour,
  and an operator who wants pruning chooses it. The baseline marked as the reference is never pruned.

  The Retention section earlier in this ADR already described the period as disabled by default; that
  and the consequence line were written at different times and read as a contradiction. They are not
  one: the mechanism exists, the pruning is off.
