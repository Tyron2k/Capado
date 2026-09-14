# ADR-003: Single-Tenant Deployment, Sites as the Organizational Scope

## Status

Accepted

## Context

Capado is developed as an open source tool under GPL-3.0 and is deployed by
each operator itself via `docker compose`. The deployment unit is therefore
one company, not one hosting platform serving many.

Two things in the codebase suggest otherwise and had to be resolved before
Phase 1 (work calendars), because a calendar has to hang off *something*:

- The single-row branding table is named `tenant_settings`. It holds only
  `company_name`, `company_subtitle`, `logo_*` and `primary_color` — it is a
  branding singleton, not a tenancy mechanism. The name implies a
  multi-tenant design that does not exist and is not planned.
- `docs/reference/glossary.md` defines **Site / Betriebsstätte** as the
  "top-level organizational/physical location", but no such entity exists in
  the data model. Multi-plant operators currently have only `ResourceGroup`
  with a maximum depth of 2.

These are different needs that are easily conflated: serving several
*unrelated companies* from one instance (tenancy) versus one company running
several *plants* (scoping).

## Decision

**One deployment serves exactly one organization. No `tenant_id` anywhere.**

Isolation between companies is achieved by separate deployments — own
database, own containers. This is stronger isolation than a tenancy column,
because it does not depend on application code remembering to filter.

**Introduce `Site` as the top organizational level inside that one
organization**, above `ResourceGroup`. A site is a plant or physical
location. The site calendar hangs off a site, because public
holidays differ per location (in Germany, per federal state) and therefore
change the capacity arithmetic, not just a label. Resource pools scope by
site; reports exist per site and consolidated.

Access scoping for sites, when it is built, extends the existing pattern on `User`
(`scope_group_ids`, `scope_project_ids`) rather than introducing a second
mechanism. **See [Resolved since](#resolved-since) for what of this landed and what did not.**

**Rename `tenant_settings` to `organization_settings`** so the schema stops
implying a tenancy model the project has rejected.

## Consequences

- No query needs a tenancy filter, so the worst failure mode of multi-tenancy
  — one forgotten `WHERE tenant_id = ?` leaking data between two customer
  companies — cannot occur.
- Global uniqueness constraints stay as they are. `skills.name` in particular
  remains globally unique instead of unique-per-tenant.
- Every future feature avoids the recurring tenancy tax: no scope parameter
  threaded through each service, no tenancy dimension in each test, no
  tenant backfill in each migration.
- Multi-plant operators are served by `Site`, which is the need they actually
  have.
- A hosted offering, should one ever be wanted, is one container stack per
  customer. That stays compatible with everything built here, so this
  decision is reversible in the only direction that matters.
- A service provider planning capacity for several client companies runs one
  deployment per client. Their skill catalogues and calendars differ per
  client anyway, so they share nothing worth sharing.
- The rename touches the model, an Alembic migration, `settings_service`, and
  the frontend `SettingsContext`. It is done now because the cost grows with
  every contributor who reads "tenant" and builds assumptions on it.

---

## Resolved since

Appended rather than edited, for the reason given in ADR-006's note of the same name. Verified against
the code rather than assumed.

**Landed as decided.** `tenant_id` appears nowhere. `tenant_settings` is gone, replaced by
`organization_settings`. `Site` exists as a table. `skills.name` is still globally unique. Both
resource types carry a nullable `site_id`.

**Landed under a different name.** The decision text said "the `WorkCalendar` from Phase 1 hangs off a
site". No class of that name was ever built. The mechanism is `Holiday.site_id`, with a
`(site_id, day)` uniqueness constraint — so holidays are genuinely per-site and the capacity reasoning
above holds, but a reader grepping for `WorkCalendar` finds nothing.

**Sites are fully manageable.** `GET/POST/PUT/DELETE /api/sites` live in the calendar router, with
`SiteCreate`/`SiteUpdate`/`SiteResponse` and a `listSites()` client. Resources carry a nullable
`site_id`, settable on create and update, with a site picker on the resource form that hides itself
when the installation has no sites. NULL means "at no site" and is not an error — a single-plant
operator files nothing at one.

**Did NOT land: site-level access scoping.** `User` has `scope_group_ids` and `scope_project_ids` and
no site equivalent — no `scope_site_ids` on the model, in the schemas, in any migration, in
`permissions.py`, or in the frontend. An editor therefore **cannot** be restricted to a site. The
sentence above was written in the present tense and read as a statement of fact; it was an intention.
Group scope is the closest available substitute, and it is not the same thing: groups are not
partitioned by site.

**On the relationship between sites and group nesting.** They are orthogonal and neither replaces the
other. `site_id` on the resource says WHERE it is. `ResourceGroup.parent_id` exists for a different
job entirely — `WorkingTimeService` walks it to inherit a work-profile binding from a parent group —
and is not a way to express location. Putting the plant into the group tree would duplicate every
trade per site and give two sources for one fact.
