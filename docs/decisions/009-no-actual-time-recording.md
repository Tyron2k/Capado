# ADR-009: Capado Does Not Record Actual Working Time

## Status

Accepted

## Context

Capado stores planned allocations: who is expected to work on what, for what share
of a normative day, over which dates. It stores no record of what actually happened.

That distinction is not incidental. It is the load-bearing argument in a German
works-council negotiation, and the first operator to deploy Capado has a works
council. A tool that plans is a scheduling aid; a tool that records what a named
person actually did is a *technische Einrichtung zur Überwachung von Verhalten oder
Leistung* in the sense of § 87 Abs. 1 Nr. 6 BetrVG, and its whole character changes.

The problem is that right now the distinction holds only because nobody has added
the field. Nothing stops a future change from putting `actual_minutes` next to
`allocation_percent`, or a `worked_hours` column on `Assignment`. Each would look
like a small, useful increment. Together with the audit trail — which already
records who changed what and when, retained indefinitely — they would turn a
planning tool into a monitoring tool without anyone having decided to.

A commitment made in a document to a works council, and not represented anywhere in
the code, is a commitment that erodes silently.

## Decision

**Capado does not store actual working time, and the boundary is explicit.**

Concretely, the following are out of scope and must not be added without a decision
that supersedes this ADR:

- Any per-person record of time actually worked — clock-in/clock-out, worked hours,
  a planned-versus-actual comparison at person level.
- Any measure of output, throughput or quality attributable to a named person.
- Any presence signal derived from system use — login times, session duration, or
  activity as a proxy for attendance.
- Any per-person monetary rate. When rates are built they attach to a `ResourceGroup`
  (a cost centre), never to a person — no rate column exists on any model today, so this
  is the rule the costing work inherits rather than a description of it.
  A personal rate is salary-adjacent data and was rejected when costs were designed.

Two things that look adjacent are deliberately still in scope, because they are
statements about *work*, not about a person:

- `WorkPackage.completed_at` — when a work package was finished. It attaches to the
  package, not to whoever finished it, and answers "was the schedule met".
- `Absence` — a forward-looking reduction of available capacity. It is entered in
  advance rather than measured, which is why it is planning data. Its `reason`
  field is a separate problem, addressed below.

## Consequences

A feature request phrased as "we should compare planned against actual" now has a
documented answer rather than an implementation. That is the point: the refusal has
to be as easy to find as the request.

Costing is affected and stays affected. Cost is computed as
`min(demand, available) × rate` from *planned* minutes, never from recorded ones.
That is less precise than a time-tracking integration would be, and the imprecision
is accepted in exchange for the boundary. An operator who wants actual-cost
reporting should get it from their ERP, which already has the recorded hours.

`AbsenceReason.sick` was a defect against the spirit of this ADR and is **resolved**
by migration 013: the reason is now `planned` / `unplanned`, and the cause is not
recorded. It was a health datum — an Art. 9 GDPR special category — that the capacity
calculation never used, since only the date range and the share enter the arithmetic.

Two details of that fix are worth keeping in view, because both were nearly missed.
`other` maps to `unplanned` as well, so the new value is not a synonym for the old
`sick`; a bucket fed from one source lets any reader recover what it replaced.
And the audit log was rewritten in the same migration, because its payloads carried
the old values verbatim and it is the one table with no retention limit — without
that, the change would have been cosmetic.

Two free-text fields remain: `Absence.note` and `AuditLog.reason`. Nothing technical
prevents health information being typed into either. They are kept because
traceability of planning decisions is their purpose, and the mitigation is purpose
limitation stated to users rather than a filter that cannot work on free text. Both
are named in the works-council document rather than left to be found.

The audit trail still covers absences, and that is now acceptable: with the cause
gone, what survives the deletion of an absence is that somebody was absent, not why.
`UNAUDITED_TABLES` remains available if that changes, but narrowing the trail trades
against the reason it exists — settling disputes about who promised what — so it is
not done pre-emptively.

Retention is now bounded: `organization_settings.audit_retention_months`, 24 by
default, applied by `app/scripts/prune_audit_log.py`. Deletion is real deletion, since
a soft delete would report that an obligation was met while the data stayed. Existing
deployments are moved to 24 months on upgrade rather than keeping their unlimited log,
because the unlimited log is the condition being fixed.

**The residual gap is now closed.** It used to be that the job had to be SCHEDULED by the
operator, and this document said plainly that a period with no scheduled job is a promise
rather than a mechanism. That is exactly what happened: the live instance ran for months with
retention set to 24 and never deleted a row. Since migration 022 the application runs the prune
itself (`app/services/scheduler.py`, on by default, hour configurable) and records every attempt
in `scheduled_job_runs`, readable under Settings and via `GET /api/maintenance/runs`.

The run log is not decoration. The failure this closes was not "no scheduler" but "nobody could
tell whether the setting had ever taken effect" — a scheduler nobody can inspect reproduces that
one level up. The number in the works-council document is a fact only for as long as the run log
shows successful runs, and an operator who disables the scheduler puts it back to being a
promise. That is now visible on the same screen as the number.

## Alternatives considered

**Say nothing and rely on nobody adding the field.** How the boundary is currently
maintained, and the reason for writing this down. An undocumented boundary is
indistinguishable from an oversight, and the next contributor cannot tell that the
missing column is a decision.

**Add actual-time recording behind a configuration flag.** Rejected. A flag that
can be switched on is a capability that exists, and the works-council question is
about what the software *can* do, not what it is currently configured to do. An
operator who needs time tracking should use a time-tracking system.

**Keep the boundary only in the German works-council document.** Rejected. That
document is a template for one legal context; the constraint it promises applies to
the software everywhere. The document points at this ADR so that the promise and
the design rule are the same statement.
