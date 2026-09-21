# Known limitations and deliberate omissions

Things that are missing, imperfect, or deliberately absent, with what each one costs and
what it would take to change. Written so the next person does not rediscover them, and so
a deliberate omission is not mistaken for an oversight.

## Scope: this is not a costing tool

Rates, budgets and cost roll-ups are **out of scope**, by decision. The tool plans
capacity; it does not calculate money.

The design existed and was rejected for now, not abandoned as unworkable: a dated
cost-centre rate on `ResourceGroup`, money as integer cents, cost as
`min(demand, available) × rate` so you pay for what was consumed rather than what was
demanded, and a budget on a folder. ADR-008 and ADR-009 still refer to that reasoning,
because it is why the folder model and the no-per-person-rate boundary are shaped as they
are.

One consequence is load-bearing beyond the feature itself: with no costing there is **no
per-person monetary rate anywhere in the system**, which is part of why Capado is not
salary-adjacent (ADR-009, and the works-council document).

## Two booking models in one table

`assignments` carries `start_date`/`end_date` **and** `start_at`/`end_at`, and which pair
is populated depends on `resource_type`. Personal assignments use dates plus
`allocation_percent`; infrastructure assignments use timestamps and leave both date columns
and the percentage NULL.

Confirmed against a real deployment: all 85 assignments there are infrastructure, with
`start_date` and `allocation_percent` NULL throughout.

The code branches correctly — verified — but the shape invites exactly the class of bug it
already produced: two of the live 500s fixed in this release came from reading a column
that is NULL for one resource type. Anything touching `assignments` has to branch on
`resource_type` first, and forgetting to is silent rather than loud.

Fixing it means splitting the table or introducing a proper sum type, which is a migration
across every consumer. Not worth it today; worth knowing before adding a third booking
shape.

## mypy: five error codes disabled

`attr-defined`, `arg-type`, `call-overload`, `union-attr` and `operator` are switched off
in `pyproject.toml`. SQLModel annotates columns as their Python type, so every
`Column == value` comparison looks like a type error.

Measured rather than assumed: 246 findings become 35 with those five off. Of 131
`attr-defined`, 124 were SQL-operator noise and **7 were real** — which is why the count
is recorded here instead of the codes being quietly dropped.

**The way out is not what this document used to claim.** It named "migrating to SQLAlchemy 2.0
`Mapped[]` annotations" as the path. That is wrong: this project uses **SQLModel**, which does not
use `Mapped[]` at all — it derives columns from plain Python annotations. Getting `Mapped[]` would
mean replacing SQLModel with bare SQLAlchemy across 17 model files, 237 field definitions and every
query in the codebase. A rearchitecture with no functional benefit, sold by this document as a
mechanical upgrade.

What was done instead, at a fraction of the cost: **`backend/scripts/check_attr_defined.py`**. The
noise turned out to be a closed set of 24 SQLAlchemy column operators (`in_`, `label`, `asc`, `is_`,
`desc`, …) — 150 of 163 findings. The script runs mypy with `attr-defined` enabled, filters exactly
those names, and fails on anything else. It replaces the plain `mypy` call in CI rather than running
beside it, so it costs no extra minutes.

Measured when it was introduced: after fixing 13 loosely-typed spots (a bare `type`, the `SQLModel`
base used where a concrete model was meant, and one `object` in freshly written code), the filtered
report is empty. Verified against a real regression by reintroducing one of the three bugs above —
the script catches it and exits 1.

The residual gap: a name that is BOTH a genuine mistake and one of the 24 operator names would still
slip through. Nothing in this codebase defines an attribute called `in_` or `asc`, and adding one to
the operator set is the one thing the script's own docstring forbids.

### What this actually costs, measured on one feature

Building the digest (August 2026) hit the blind spot twice in one afternoon, in code that
passed `ruff`, `mypy` and `tsc`:

- `violation.shortfall_working_days` — the field is `working_days_short`. A plain typo on a
  frozen dataclass, exactly what `attr-defined` exists to catch. Reached runtime and was
  caught only by a unit test that happened to exercise that branch.
- `work_package.committed_date` — the field is `committed_delivery_date`, and it is on
  `Project`, not `WorkPackage`. So the mistake was not just a name: an entire loop had the
  wrong shape, iterating work packages for a value that only exists per project. mypy
  reported the file clean.

Both were found by writing tests and by grepping the models by hand. Neither would have
existed with `attr-defined` on. The lesson recorded here for the next person: **on this
codebase a clean mypy run is not evidence that an attribute exists** — check the model.

## The SMTP password is stored in plaintext

`organization_settings.smtp_password` holds the relay password as written. This is a decision,
not an oversight, and the alternatives were weighed:

- **Encrypt with a key from the environment.** The key then lives beside the database in the
  same compose file, so anybody who can read the database can read the key. It buys obfuscation
  rather than secrecy while adding key rotation as a new operational problem.
- **Environment variable only.** Genuinely better for secrecy, and rejected because the
  requirement was UI configuration: a field that can only be set by editing a compose file and
  restarting is not that.

The reasoning: an SMTP relay password is a low-value credential next to the planning data already
in this database. Anybody who can read `organization_settings` can already read every person,
project, and assignment. Protecting the password against database exfiltration while leaving the
planning data unprotected would be theatre.

What IS defended against is the realistic leak: the API never returns the password. The read
schema exposes `smtp_password_set` as a boolean, and the settings page leaves the field blank
rather than prefilling a dummy — an operator editing around a `••••••` placeholder sends the
placeholder. Omitting the field on save keeps the stored value; an explicit empty string clears
it, which is a separate button.

If this becomes unacceptable, the path is a secrets backend (the environment variable override,
or a mounted file), not encryption-at-rest with a co-located key.

## Migrations 001–003 are excluded from lint

`.pre-commit-config.yaml` excludes `backend/alembic/versions/` globally. Those three
migrations carry 21 ruff findings and are left alone on purpose: they have been applied to
every existing database, and reformatting an applied migration produces a diff that cannot
be verified against anything.

New migrations are linted manually before commit. If the exclusion is ever narrowed to
just 001–003, that manual step goes away.

## Full container builds do not run on every pull request

Pull requests lint both Dockerfiles and scan the production container configuration, but they do not
perform the full emulated `linux/amd64` + `linux/arm64` build. That build costs about 9.3 minutes per
run (backend 216s, frontend 339s — measured), with the emulated ARM layer accounting for most of the
time and historical hangs.

Instead, `build-images.yml` runs a cheap decision job every night. It publishes a new `:edge` pair
when `main` changed since the last successful publication, or when the images are seven days old and
need moving base-image security fixes. It can also be forced manually. Candidates are scanned by
digest before tags move, so a failed build or HIGH/CRITICAL vulnerability leaves the previous good
`:edge` in place.

The remaining limitation is timing: a Docker build regression can merge and is discovered by the
next nightly build rather than by the pull request. `edge-<sha>` and the OCI revision label make the
last published commit explicit. A published release uses the same build-and-scan workflow and will
not promote release tags when either image fails.

## Free-text fields defeat the enum work

`Absence.note` (500 chars) and `AuditLog.reason` accept anything. Migration 013 removed the
`sick` absence reason precisely because it was health data, and a note reading
"Krankmeldung liegt vor" puts it straight back — observed in testing against real-shaped
data.

No technical fix exists for free text. The mitigation is purpose limitation stated to
users, which is what the works-council document commits to. Removing the fields entirely
was rejected: traceability of planning decisions is their purpose, and "Vertretung durch
Kollegin" is exactly what a planner needs to record.

## Baseline entries have no volume cap

A freeze writes one row per project, work package and assignment — thousands per baseline
on a real plan. Retention exists but defaults to **disabled**, because a baseline is a
deliberate record rather than a by-product (ADR-007).

So a deployment that freezes weekly and never sets a period will accumulate indefinitely.
That is the intended trade, not an oversight, but it is a trade.

## Work packages may lie outside their project's date range

Reported as a **warning**, not rejected. A project's dates are a container, and a work
package that runs past them is usually a signal to move the project boundary rather than an
invalid entry. Existing rows in this state are surfaced only when someone edits them, so a
deployment can carry them silently for a long time.

## The plan is only as good as its lead times

`WorkPackageTemplate.lead_time_working_days` is optional and empty by default. Until it is
filled, the lateness warning stays silent — it does not guess a duration.

This is correct behaviour and a practical trap: a deployment can look healthy purely
because nothing has told it how long anything takes.

## Availability windows are inert until defined

An infrastructure resource with no windows counts as available around the clock, which
keeps every pre-ADR-005 plan valid. The consequence is that the whole window-violation
mechanism does nothing on a fresh deployment: a booking at 03:00 on a Sunday is accepted
until somebody defines operating hours.

## Imports have no size limit

None of the five importers enforces a maximum upload size, a row cap or a time limit. The file is read
into memory in full (`content = await file.read()`) and parsed there.

What keeps this tolerable rather than a denial-of-service vector is that all five endpoints are
admin-only, and the parse runs in a thread pool rather than on the event loop, so a slow file does not
block other requests. What it costs is a hard ceiling nobody has measured: a sufficiently large
workbook exhausts the container's memory, and the failure mode is the backend being killed rather than
the request being rejected.

The fix is a size check in the router plus a row cap in the parser, which is a small change nobody has
needed yet. It should happen before Capado is reachable by anybody less trusted than an administrator
— note that "admin-only" is a weaker guarantee than it sounds if an admin token ever leaks.

See [import and export](import-export.md) for the formats themselves.

## Local passwords cannot be reset by their owner

A user who forgets their **local** password cannot recover it themselves. Two of the three doors are
closed:

- **No forgot-password flow.** There is no reset endpoint and no reset mail. SMTP serves the digest
  only.
- **Setup is a one-time door.** `POST /api/auth/setup` answers 403 as soon as any user exists, so it
  cannot mint a replacement admin.

**An administrator can reset it.** `PUT /api/users/{id}` accepts a `password` field and sets
`must_change_password`, so the value the admin chose is a handover credential the user replaces at
next login. That closes the ordinary case — somebody forgot their password and asks — without a mail
server. The audit log records that the field changed; the hash itself is redacted.

What remains is the case where **nobody with admin rights can log in**.

### OIDC is the recovery path for a locked-out administrator

An OIDC login **links to an existing account by email address and keeps that account's role**
(`routers/oidc.py`, `_find_or_create_user`). An administrator who has forgotten their local password
gets back in through SSO, as an administrator, provided all of:

1. OIDC is configured and the provider is reachable.
2. The email the provider asserts equals the email on the Capado account.
3. The provider asserts `email_verified: true`, unless `OIDC_REQUIRE_VERIFIED_EMAIL=false`.
4. That account is still active.

`/api/auth/login` is never disabled, so the local password stays a parallel door either way — which
means the setup admin's password is typically used once at install and never again. That is precisely
the password that is forgotten a year later.

### Where it still ends in the database

- **No OIDC configured.** A single-admin deployment that loses that password has no way in but
  writing a bcrypt hash into the `users` table by hand.
- **Email mismatch.** No link happens. If auto-creation is enabled the SSO login instead produces a
  **viewer** (`role=UserRole.viewer`), which cannot repair anything.
- **Provider unreachable.** Only the local password remains, and it is the forgotten one.

On any deployment you would be locked out of: create a second admin account, or make sure the admin's
email matches what your IdP asserts.

There is no CLI script for this. An earlier `app/scripts/create_admin.py` softened it and was removed,
because the setup
endpoint covers first-time creation both interactively and scripted, which is the case that actually
occurs. That removed a workaround, not a feature — the script skipped an address that already existed,
so it never reset a forgotten password either.

## OIDC account linking trusts the provider's email claim

The linking described above matches on `userinfo.email`. Whoever can make the identity provider assert
`admin@your-company.example` reaches the matching Capado account on first login, **with that account's
role** — which is what makes SSO recovery work, and what makes an unverified address dangerous.

**The provider has to vouch for the address.** `email_verified` is read from the
userinfo response and a login is refused when it is absent or false, with the reason logged. The gate
sits in front of **both** the linking and the auto-creation step, because putting it only in front of
creation would repeat the mistake below.

`OIDC_REQUIRE_VERIFIED_EMAIL=false` turns it off, for a provider that omits the claim entirely and
whose addresses you trust. Before setting it, check what your provider actually returns from its
userinfo endpoint — many send the claim and some do not.

### authentik returns `false`, on purpose

Verified against a live instance (authentik 2026.8): the discovery document lists `email_verified`
under `claims_supported`, and the built-in email scope mapping returns it as **false**. That is not a
misconfiguration — authentik's documentation states it "has no way to confirm whether a user's email
is verified", and that defaulting to true "could introduce unintended security risks". Enough
integrations hit this that authentik documents a custom mapping for each of them.

So an unmodified authentik has its logins refused by the gate above. That is the gate doing its job:
the provider is saying it cannot vouch for the address, which is exactly the condition being refused.
The question it hands back to the operator is whether the addresses are trustworthy for another
reason — typically that accounts are created by hand in a directory nobody else can register in.

Two ways to say yes, and they differ in reach:

- **`OIDC_REQUIRE_VERIFIED_EMAIL=false` in Capado.** The trust decision applies to Capado alone.
- **A custom scope mapping in authentik returning `email_verified: true`.** Every application
  connected to that provider now hears that the address is verified, including ones that decide
  account merging on it.

Prefer the first unless the second's reach is what you want.

**The obvious mitigation still does not mitigate this.** `OIDC_AUTO_CREATE_USERS=false` prevents *new*
users from being created; the linking step runs BEFORE that check, so an operator who reads that flag
as "nobody unexpected gets in" is wrong. That is why the verification gate is a separate setting rather
than folded into it.

Two things the gate does **not** cover:

- **An already-linked account** is matched by `external_id`, the provider's subject, and needs no email
  trust — so it is deliberately exempt. Refusing there would lock out every SSO user the moment a
  provider stopped sending the claim, which is a self-inflicted outage rather than a safeguard.
- **The claim is read from the userinfo endpoint**, not from the ID token. A provider that returns it
  only in the token is treated as not asserting it.

## Self-service is read-only, and the link is set by hand

`GET /api/me/plan` lets a person read their own assignments, absences and qualifications once an
administrator has linked their account to the scheduled person (`users.resource_id`). Two absences
somebody will look for as soon as they see that screen:

- **No calendar feed.** There is no ICS endpoint, so the plan cannot be subscribed to from Outlook or
  a phone. It is a page you visit.
- **No leave request.** A person cannot ask for absence and a manager cannot approve it here.
  Absences are entered by whoever plans them. That is not an oversight of convenience: an approval
  workflow around absence data is a co-determination question of its own, so it was deliberately
  separated from read access rather than bundled with it.

**The link is deliberately manual, one account at a time.** Nothing matches accounts to people by
name or email address: `personal_resources` has no email column, and matching on a name is the kind of
heuristic that silently connects the wrong Müller — to somebody else's plan, absences and
qualifications. The cost is that an operator links accounts by hand; the alternative was a guess with
personal data on the other side of it.

An account with no link behaves exactly as before, and answers 409 rather than an empty plan.

## Dates are localised on the display side only, and not everywhere

`formatDate` and `formatDateTime` take a `locale`, but it defaults to German, and only the
digest panel passes one. Every other screen renders `DD.MM.YYYY` whatever language the UI is
in. The helper is locale-capable; the app is not yet locale-consistent.

**The input side is why it stopped there.** `DateField` uses `DISPLAY_DATE_FORMAT` for typing
as well as display, and `parseDisplayDate` reads `DD.MM.YYYY`. Localising display alone would
show a date in one order and demand it typed in another — worse than being uniformly German,
because a user who copies what they see back into a form gets it rejected, or worse, accepted
as a different day.

Finishing it is therefore not a formatting change. It changes how people type dates, which
for the current audience means changing something that works, so it wants its own decision
rather than being carried along by a display fix.

Ordering is done by rearranging ISO parts textually, never through `Intl.DateTimeFormat`:
that needs a `Date`, and constructing one is the bug class `utils/date.ts` exists to prevent
(see [date handling](date-handling.md)). Any future locale has to be expressible as a
rearrangement of year, month and day, or it needs a different mechanism — a locale wanting
month NAMES would need them translated, and that is the point at which this approach stops
being enough.

## Small header text is below AA on a brand colour that passes the guard

`readableForeground` keeps the header readable by switching the foreground when white stops working,
and its threshold is 3.0 — WCAG AA for large text, which is what the header mostly is: a bold
`size="md"` company name and 20px icons.

The user's name next to it is `size="sm"` at weight 500, which is normal text and wants **4.5**.
Measured on a real installation whose brand colour is `#0d9488`, white scores **3.74**: above the bar
this guard applies, below the bar that label needs. So the guard answers correctly and one label in
the header is still short of AA.

Raising the threshold to 4.5 is the wrong fix. It would flip headers that read perfectly well to dark
text — including that one — and the flip is visible on every screen at once, in exchange for one small
label. The proportionate answers are local to the label: make it `size="md"` or weight 600, or move it
out of the brand-coloured bar. Both are decisions about the header's design rather than about contrast
arithmetic, which is why the guard was not stretched to cover them.

Nothing else in the application paints text on the brand colour, so this is the only place the gap
exists. It is also the only place measured: **the interface has had no contrast audit**, and the
figures above come from adding the guard, not from a pass over the product.

## The query layer does not cover session state or client state

Every server READ in the frontend goes through TanStack Query, and every WRITE through a mutation that
declares the affected keys untrue. Three things are deliberately outside that, and each is a category
difference rather than a screen nobody got to:

**The authentication session.** `AuthContext` holds the access token, the signed-in user, and the
restore-on-mount bootstrap in plain state. A session is not a cacheable server value: the token is
consumed by the request interceptor on every call, and "stale" is not a meaningful thing for it to be.
Caching it would also invert the dependency — the query client would need a token that the cache is
supposed to hold.

**User preferences.** Colour scheme and locale live in `localStorage` and are never sent anywhere. There
is no server copy for them to be stale against. They sit beside the branding in `SettingsContext`, which
*is* a query, and the two are kept apart on purpose.

**Commands.** Signing in, first-run setup and changing a password are `useMutation` without any
invalidation, because there is no cached value they make untrue — a login decides who is asking, it does
not change what the answer is. The report downloads are the same shape.

The measurement that answers "is anything left" is not a single grep, and one grep is what made an
earlier version of this section wrong. `grep -rl useQuery frontend/src/features` finds hand-rolled READS
in the feature tree; it does not find a file that only writes (`ConflictResolutionActions` tracked its
pending state as `setSaving` and was invisible), a file outside `features/` (`RequirementsEditor` held a
module-level cache), or a different spelling of the flag (`setIsLoading`). Searching for a hand-rolled
loading flag of any spelling across all of `frontend/src` is the question that finds those.

The order that has worked is by shared *insight* rather than by file size — the keys before the second
screen, the first mutation before the fifth read screen, everything that changes capacity in one batch —
because each batch's decisions are what the next one copies.
