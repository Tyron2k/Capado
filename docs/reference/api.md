# API Reference

**The endpoint list is not here. It is generated.**

- Interactive: `http://localhost:3001/docs` (Swagger UI)
- Machine-readable: `http://localhost:3001/openapi.json`

FastAPI produces both from the route decorators, so every path, method, request body, response model
and status code is derived from the code that serves it. A hand-written second copy could only be one
of two things: identical, or wrong.

It used to be here, and it was wrong. This file listed the absence request body as
`"reason": "vacation|sick|maintenance|training|other"` long after those values had been removed —
`sick` is health data under Art. 9 GDPR and the reason was reduced to `planned`/`unplanned`. An API
consumer following that example would have been told to send a value the API rejects. The generated
schema cannot make that mistake, because it reads the enum.

`backend/tests/test_docs_coverage.py` now enforces that every endpoint carries a `summary`, so the
generated documentation is complete rather than merely present.

**What is in this file instead:** the things a schema cannot say. Conventions that hold across
endpoints, semantics you cannot infer from a type, and the handful of decisions where the *reason*
matters more than the shape.

---

## Conventions

**Base URL** `http://localhost:3001/api`. Every path below is written without that prefix.

**Errors** have the shape `{ "detail": "..." }`. Some carry an `X-Error-Code` header naming the case
machine-readably, so a client can branch on the case rather than on prose — see
[Error cases](#error-cases).

**Pagination** on list endpoints is `limit` and `offset`, defaulting to 100 with a maximum of 500. Two
exceptions: `GET /users` defaults to 50 with a maximum of 200, and the audit log caps at 200 per page
deliberately — an unbounded query over the change log would be an analysis tool, which
[ADR-006](../decisions/006-audit-trail.md) rules out.

Every list endpoint has a total ordering. That is not cosmetic: paginating without one lets Postgres
return the same row on two pages and skip another, so a client walking pages could miss records.

**Dates** are ISO `YYYY-MM-DD`; assignment timestamps require an ISO 8601 UTC
offset (`Z` or `+HH:MM`) and are returned as UTC instants. A local timestamp
without an offset is rejected, including in assignment previews. See
[date handling](date-handling.md) for the reasoning and the traps.

Infrastructure conflict suggestions that move bookings include both `new_start_at`
and `new_end_at` as concrete UTC instants. Apply those exact values; `shift_days`
is descriptive for infrastructure, not an instruction for client-side arithmetic.
Personal assignments remain calendar dates and use `shift_days` as before.

**Authentication** is a bearer access token in `Authorization`. The refresh token is an httpOnly
cookie rather than a response field ([ADR-002](../decisions/002-refresh-token-cookie.md)), so a
client never handles it and cannot store it somewhere reachable by script.

---

## Semantics you cannot read off a type

### Assignments have two shapes, and the difference is not cosmetic

A **personal** assignment carries `start_date`, `end_date` and `allocation_percent` — a share of a
normative day.

An **infrastructure** assignment carries `start_at` and `end_at` as timestamps and no
`allocation_percent` at all. Infrastructure is always exclusive: a paint booth is either yours for
that window or it is not. Sending an allocation for one is not "100% by default", it is meaningless.

`allocation_percent` is measured against a **normative** 480-minute day, never against the individual
resource's capacity. This is deliberate and it is a safeguard: were it relative, assigning a part-time
person twice their hours would read as "100% utilised". Against the norm it reads as **overbooked**,
so the overload is visible in the plan before it arrives on the floor.

### `includeMismatch=false` is a performance switch with a consequence

It skips the skill-mismatch computation, saving two to three queries per request. The consequence is
that `skill_mismatch` then returns `false` for every row — not "no mismatch found", but "not checked".
A caller that treats the field as an answer will report unqualified assignments as fine.

### A work package outside its project's dates is a warning, not an error

`POST` and `PUT` return the situation in a `warnings` entry and **save the work package anyway**. Real
plans have packages that overrun their project, and refusing the write would make the tool argue with
reality. `400` is reserved for an empty name or `end_date < start_date`; `404` for a missing package or
parent project.

### Self-service takes no resource id, on purpose

`GET /me/plan` reads the resource from the caller's own account (`users.resource_id`). There is no path
parameter, because a route that accepts an id is a route that has to authorise it — and the safest
authorisation is a parameter that does not exist.

An account with no link answers **409** with `X-Error-Code: no_linked_resource`, not an empty plan.
"Nothing is scheduled for you" and "nobody has recorded who you are" are different answers, and
returning the first for the second would have a person conclude they have no work.

The view is read-only. Requesting leave and confirming an assignment are separate workflows with their
own consequences and are deliberately absent.

An administrator sets the link with `PUT /users/{id}`: `resource_id` to set, `clear_resource_id` to
remove. **Omitting `resource_id` leaves an existing link alone** — otherwise renaming somebody would
silently unlink them from their own plan. Claiming a resource another account already holds answers
`409` with `X-Error-Code: resource_already_linked`.

### Availability windows invert the usual default

A resource with **no** windows counts as available around the clock. Adding the first window is
therefore a *restriction*, not a permission
([ADR-005](../decisions/005-infrastructure-availability-windows.md)). Nobody expects the first entry in
a list to reduce what is allowed, so it is worth stating twice.

### Holiday minutes are a number, not a flag

`working_minutes` is `0` for a public holiday or shutdown, below the profile for a half day, and above
zero on a normally free day for a designated working Saturday. A boolean would have made the third case
impossible to express.

### Week profiles: two deletes that refuse

A profile still bound to a resource cannot be deleted, and the default profile cannot be deleted at
all. Bindings are **dated**, so a contract change is a new binding starting on its own date — never an
edit of the old one, which would rewrite history.

### Customers are unique case-insensitively

That is the entire point of the entity. It replaced a free-text column in which "Acme" and "Acme GmbH"
were two customers and nothing could state they were one.

A project's customer is inherited from the nearest folder up the tree that names one
([ADR-008](../decisions/008-project-hierarchy.md)). A project's own customer wins when set, and nothing
is invented when no folder names one.

### Baselines: the diff is the deliverable

The snapshot exists so the comparison can be made ([ADR-007](../decisions/007-plan-baselines.md)). The
baseline marked as the reference is never pruned by retention.

### The audit log returns `changes` as JSON

Which means a date arrives back as a **string**, not as a date
([ADR-006](../decisions/006-audit-trail.md)). Secrets are redacted: a password change is recorded as an
event, with the value replaced — the key stays so the event remains visible.

### Maintenance is the evidence, not the mechanism

Retention periods are settings; the maintenance job is what applies them. An **empty run log means
nothing has been deleted**, so a configured period without a run is an intention rather than a state.
This is the endpoint to check when asked whether retention is actually happening.

### Reports call the same computation as the screen

The utilization report invokes the computation behind the dashboard charts, so a number in the file and
the same number on screen cannot disagree. A report that contradicts the dashboard is worse than no
report, because somebody then has to decide which one is lying. Capped at 104 weeks, because
utilization is computed per resource per week and an open range would run for minutes.

### Team week shows every assignment, not the largest

One row per person, one column per day. Days with no calendar time are marked rather than left blank,
so "not working" and "nothing planned" stay distinguishable.

### Settings are server-side; two things are not

Branding, the display time zone, retention, the planning freeze, the maintenance hour, SMTP and the digest thresholds live in
`organization_settings` and are organisation-wide. **Colour scheme and language are not there** — those
are browser-local preferences, set from the header, and no administrator can set them for somebody else.

### The digest drops rather than queues

Findings beyond the horizon (90 days by default) are not reported at all. Within it they rank by
proximity rather than by kind, and collapse to one per subject — the hard part of a digest is
suppression, not detection.

### OIDC has no user interface

It is configured entirely through `OIDC_*` environment variables; see `.env.example`.
`OIDC_AUTO_CREATE_USERS` decides whether an unknown but successfully authenticated subject gets an
account or is refused. `OIDC_REQUIRE_VERIFIED_EMAIL` decides whether the provider must vouch for the
address before it is used to link or create — see
[known limitations](known-limitations.md) for why one common provider makes that setting load-bearing.

### Exports are not all re-importable

`GET` exports of personnel and infrastructure take `format=xlsx` (a skill matrix — a **report**, whose
header spans two rows and which the importer cannot read), `format=xlsx-flat` or `format=csv`. Only the
latter two round-trip. Anything else answers `400`. The full rules are in
[import and export](import-export.md).

### Sites

Exactly one site carries `is_default`. `region_code` is a hint for the holiday seed script and is
**never read at runtime** — a value there does not make holidays appear.

---

### Deactivating a person is not the same call as erasing one

`DELETE /resources/personal/{id}` **deactivates**: the row stays, the person disappears from
planning and can be reactivated. A group-scoped editor may do it.

`DELETE /resources/personal/{id}/erase` **erases**: the person, their qualifications, work-time
profiles, absences, assignments, detected conflicts and the audit entries about them are deleted.
Irreversible, **admin only**, and a separate route rather than a flag on the first one — a boolean
would let the irreversible operation be reached by a typo in a query string.

It answers with per-table counts rather than 204, because the operator honouring an Art. 17 GDPR
request needs something to file. Two things are deliberately not touched: **baselines**, which freeze
assignments rather than people and therefore hold a resource identifier and no name, and **one audit
entry** recording that an erasure happened, with no personal content.

## Error cases

| Status | Meaning |
|--------|---------|
| 400 | Business rule violation (e.g. invalid date range, unknown export format) |
| 401 | Not authenticated, or token expired |
| 403 | Insufficient permissions or out of scope |
| 404 | Entity not found |
| 409 | Conflict: duplicate, FK-blocked deletion, or a state that must be resolved first |
| 422 | Input validation failed |
| 429 | Rate limited (auth endpoints) |
| 500 | Unexpected server error |

Some responses add an `X-Error-Code` header so a client can distinguish cases that share a status:

| `X-Error-Code` | Status | Case |
|----------------|--------|------|
| `no_linked_resource` | 409 | The caller's account is not linked to a scheduled person |
| `resource_already_linked` | 409 | Another account already holds that resource |
| `insufficient_role` | 403 | The role is wrong, as opposed to the scope being wrong |

---

## Who may write what

All **read** endpoints are open to any authenticated user. Writes:

| Entity | Admin | Editor | Viewer |
|--------|-------|--------|--------|
| Personal resources and assignments | ✅ | ✅ within group scope | ❌ |
| Infrastructure resources and assignments | ✅ | ✅ within group scope | ❌ |
| Projects and work packages | ✅ | ✅ within project scope | ❌ |
| Personal / infrastructure skill assignments | ✅ | ✅ within group scope | ❌ |
| Skills, attributes and templates | ✅ | ❌ | ❌ |
| Bulk imports | ✅ | ❌ | ❌ |
| User management | ✅ | ❌ | ❌ |

The last three are **admin-only**, and the reason is worth keeping because it is not obvious:

Skills, attributes and templates are a **global catalogue**. They are not owned by a group, so no group
scope could authorise a change to them, and renaming one silently changes what every stored import file
resolves to.

Bulk imports cannot be scope-checked at all. The uploaded file may name resources in any group, so
there is no single `group_id` that could authorise it — the scope is only knowable after parsing, at
which point the check is decoration. The personnel and infrastructure importers additionally
auto-create missing skills, which is a global-catalogue write.
