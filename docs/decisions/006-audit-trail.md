# ADR-006: Audit Trail

## Status

Accepted

## Context

Nothing records who changed what. After a missed delivery date there is no way to
establish who moved an assignment, or when. Three consequences:

- A plan that any `editor` can change invisibly is not a binding plan. The
  conversation becomes "the plan says Tuesday" versus "it said Thursday last
  week", with no way to settle it.
- ISO 9001 and IATF 16949 both expect traceability of changes to production
  planning. Its absence is an audit finding, not a preference.
- ADR-007's baseline can show *that* a plan drifted. Only a change log can show
  *why*, and the two together are what make a deviation actionable.

## Decision

### One generic table, not per-entity history

`audit_log` records `entity_type`, `entity_id`, `action`, `actor_id`,
`recorded_at`, and the changed fields as JSON.

Per-entity history tables would be better typed and easier to index for "show me
this assignment's versions". They were rejected because the questions actually
asked here cross entities: *who changed anything on Friday*, *what did this user
touch*, *what happened around this work package* — each of which becomes a UNION
over ten tables in the per-entity design and a single indexed query here. A new
entity also needs no migration to become auditable.

The cost is accepted knowingly: the changed-field payload is untyped JSON, and a
query for one field's history means reading JSON rather than a column.

### Session events for the *what*, an explicit reason for the *why*

A `before_flush` listener inspects `session.new`, `session.dirty` and
`session.deleted`, reads per-attribute history, and adds `AuditLog` rows inside
the same flush.

Explicit service-layer writes were rejected as the primary mechanism for one
reason: the value of an audit log is proportional to its completeness, and any
path that forgets to write one is exactly the path someone will later ask about.
A listener cannot be forgotten.

What a listener cannot know is intent. "Shifted to resolve a conflict" and
"shifted because the customer moved the date" are the same UPDATE. A service may
therefore set a reason on the session, which the listener attaches to the rows of
that flush. The mechanism is additive: a change with no reason is still recorded.

Recording happens **inside the transaction**. An audit row written outside it
would survive a rollback and describe a change that never happened — a log that
lies is worse than no log.

### The actor rides on the session

`get_authenticated_user` stamps `session.info["actor_id"]`, and the listener
reads it there.

Threading an actor through every service signature was rejected as invasive:
services are constructed with a session and nothing else, and every constructor
and call site would have to change. A `ContextVar` would work but has to be reset
carefully to avoid leaking an actor between concurrent requests.

`session.info` is SQLAlchemy's designated place for caller-scoped data, and in
FastAPI the session already *is* request-scoped, so the lifetimes match exactly.

Unauthenticated writes — initial setup, login recording a refresh token — record
`actor_id = NULL`, which is accurate rather than a gap: there is no actor yet.

### Derived tables are not audited

`conflicts` and `conflict_assignments` are excluded.

They are recomputed, not edited: `refresh_conflicts` deletes and re-inserts every
conflict for a resource on each assignment change. Auditing them would add dozens
of rows per user action, describing a derivation rather than a decision, and would
bury the entries someone is actually looking for. The assignment change that
caused the recomputation is recorded, which is the decision that was made.

### No created_by / updated_by columns

This deviates from the original plan for this work, deliberately.

Denormalised columns on ten tables would duplicate what the log already holds,
add a dual-write that can drift, and cost a migration per table. "Last changed by"
is answerable from the log with an indexed query on
`(entity_type, entity_id, recorded_at)`.

If a list view later proves this too slow — 200 rows each needing a lookup — the
columns can be added as a cache with the log remaining the source of truth. That
is a reversible optimisation; the reverse, discovering the columns and the log
disagree, is not.

## Consequences

- Every insert, update and delete on an audited table produces a row, in the same
  transaction. Bulk imports therefore produce bulk audit rows; the import path
  should set a reason so those rows are identifiable as one operation.
- The log grows without bound. Retention is not solved here and belongs with the
  GDPR work, which has to decide it anyway — an audit row naming a person is
  personal data. **This consequence no longer holds — see [Resolved since](#resolved-since).**
- `session.info` is only stamped by the authenticated dependencies. A script
  writing through `async_session_factory` directly records `actor_id = NULL`;
  `app/scripts/` are expected to set a reason instead.
- The listener reads attribute history, which requires the attributes to be
  loaded. A bulk `UPDATE ... WHERE` issued as a Core statement bypasses the ORM
  and is therefore **not** audited. Two such statements exist today, both in
  `calendar_service` for clearing a previous default; they are converted to ORM
  updates so the change is visible.
- Tests construct services with hand-built session doubles that never flush, so
  the listener does not fire there. Its behaviour is tested directly against the
  change-collecting function instead.

---

## Resolved since

**This section is appended, not edited.** An ADR records a decision at the moment it was taken; the
consequences above were true then, and rewriting them would erase the record. What follows says which
of them no longer hold, so a reader does not act on a resolved concern.

- **"The log grows without bound. Retention is not solved here."** It is now. Retention is a setting
  (`organization_settings.audit_retention_months`), defaults to **24 months**, and is applied by a
  recurring maintenance job. `0` means unlimited — a deliberate choice rather than a state reached by
  omission. Existing installations receive 24 months on upgrade rather than "unlimited", because
  silently carrying the unbounded state forward would have made the setting decorative.

  One caveat that belongs with it: without the maintenance job running, **nothing is deleted**
  whatever the setting says. The maintenance run log is the evidence that the period is applied.
