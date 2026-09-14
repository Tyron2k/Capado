# Upgrading an existing installation

**Migrations run automatically when the backend container starts.** There is no manual gate —
`app/main.py` runs `alembic upgrade head` during startup. Starting the new image *is* the upgrade, so
everything in step 1 and 2 has to happen before that.

Capado is pre-1.0 and the schema still changes between releases. Read the release notes for the version
you are moving to before starting; anything version-specific lives there, and the sections below are
the procedure that applies every time.

## 1. Back up, without exception

Not every migration is reversible. Migration 013, for example, collapsed absence reasons to
`planned` / `unplanned` and **deleted the original cause** — its downgrade restores the wider enum but
fills in `vacation` / `other`, not the values that were there. Assume the release you are applying
contains something equivalent unless you have checked that it does not.

```bash
docker exec <db-container> pg_dump -U <user> -d <database> -Fc \
  > capado-$(date +%F-%H%M).dump
```

Verify the dump is readable and contains data sections, not just a schema:

```bash
docker exec -i <db-container> pg_restore -l < capado-<stamp>.dump | grep -c "TABLE DATA"
```

A count of zero means you have a schema-only dump and no backup.

## 2. Check where you are starting from

```sql
SELECT version_num FROM alembic_version;
```

This tells you how many migrations will run, and it is the number to quote if you need help. Note it
down before starting — after the upgrade it is gone, and reconstructing it from the schema is
guesswork.

## 3. Get the new images

A published release builds and pushes both images automatically, tagged with the full version plus the
shortened forms and `latest`. Pull the version you mean to run rather than `latest`:

```bash
# in .env
CAPADO_VERSION=0.2.0
```

```bash
docker compose -f docker-compose.prod.yml pull
```

If a pull fails with `error from registry: unauthorized`, the images' **package visibility** is the
likely cause rather than a missing image or a wrong tag — GHCR packages do not inherit repository
visibility. See [publishing a release](publishing-a-release.md).

### If you track `main` rather than releases

`build-images.yml` runs only when triggered, so `ghcr.io/.../backend:edge` can be older than `main` —
possibly by many commits.

```bash
gh workflow run "Build images"
gh run watch
```

Roughly 9–10 minutes for both images on both platforms (measured: backend 248s, frontend 306s). The
reason it is manual: it used to run on every push to `main`, and most of those images were never
pulled, which was the largest avoidable line on a metered Actions budget.

Confirm which commit you are about to deploy. Either pull the **SHA tag**, which the build pushes
alongside `:edge`:

```bash
docker pull ghcr.io/<owner>/capado/backend:edge-<sha>
```

or read the label off an image already on the host:

```bash
docker image inspect ghcr.io/<owner>/capado/backend:edge \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

The label was added in August 2026. **An image built before that returns an empty string**, which
looks like a missing image rather than a missing label — if that happens, use the SHA tag instead of
concluding the image is absent.

## 4. Deploy backend and frontend together

The two are versioned as a pair and a release may change the contract between them. Migration 013 is
the illustration: it reduced the absence reason to a two-value enum, so an old frontend sent
`reason: "vacation"` and the new backend answered 422 — absence management broke for exactly as long
as the two were apart.

```bash
docker compose -f docker-compose.prod.yml up -d
```

One command covers it, because Compose recreates both from the images you just pulled.

If the stack is managed by a tool that holds its own registry account (Komodo, Portainer, Watchtower),
trigger the deploy **through that tool**. Running `docker compose pull` by hand on the host uses the
host's Docker credentials, which are a different thing and may not exist.

## 5. Verify it came up

```bash
docker compose -f docker-compose.prod.yml ps
```

Both services should report `healthy`, not merely `running` — the healthchecks call the app rather
than the process table. Then confirm the schema moved:

```sql
SELECT version_num FROM alembic_version;
```

A backend that is `running` but never becomes `healthy` usually failed inside a migration. Its logs
say which one:

```bash
docker compose -f docker-compose.prod.yml logs backend | grep -i alembic
```

## 6. Rolling back

`alembic downgrade <revision>` runs and is tested, but it is not a time machine:

- deleted absence causes do not come back (see step 1)
- audit entries and baselines deleted by a pruning run do not come back
- availability windows that wrap past midnight are dropped, because the older schema cannot
  represent them
- folders are dropped; the projects that were in them survive, unfiled

If any of that matters, restore the dump instead of downgrading.

---

# One-time steps when you adopt a feature

These are not per-upgrade. Each applies once, the first time an installation gains the feature, and
each has a failure mode that looks like working software.

## Assign week profiles

Every resource falls back to the default profile — a five-day, eight-hour week. Nothing is wrong with
that as a default, but **anyone who does not work that pattern has overstated capacity** until a
profile is assigned. Resources → person → the week-profile drawer. Bindings are dated, so a contract
change is a new binding from its start date rather than an edit of the old one.

## Fill in lead times where you have them

`WorkPackageTemplate.lead_time_working_days` drives the lateness warning in the project overview.
Without it the warning stays silent — it does not guess. If your templates already state a duration in
working days, entering it there applies to every work package created from the template afterwards.

## Verify audit-log pruning is running

The application prunes by itself; there is no external timer to set up. The scheduler is **on by
default** and runs after the configured hour (Settings → hour for maintenance jobs, default 02:00 **in
the server's clock, normally UTC**).

What to check after the first night — Settings shows the last runs directly under the retention
fields, or via the API:

```bash
curl -H "Authorization: Bearer $TOKEN" https://<host>/api/maintenance/runs
```

A `succeeded` row with `items_affected` is the evidence that the retention period is applied. **An
empty run log means nothing has been deleted** — the period is then an intention, not a state, and the
settings page says so rather than looking healthy.

The manual script still exists and is the right tool for a first, deliberate run against years of
history, because it can count before deleting:

```bash
python -m app.scripts.prune_audit_log --dry-run   # count first
python -m app.scripts.prune_audit_log
```

Note on catch-up: the scheduler deletes in batches and loops up to 50 batches per run. On an instance
with a very large backlog the first automatic run may not finish the whole backlog; the run detail says
so explicitly instead of reporting a clean sweep. A missed day (container down) is made up **once** on
return, not once per missed day.

The period itself is editable under Settings → Data protection; 0 disables pruning.

The same job applies **baseline** retention, which defaults to **0 — keep everything**. That default is
deliberately the opposite of the audit log's: an audit entry accumulates as a side effect of working,
while a baseline is a state somebody deliberately froze because it mattered. Set a period only if you
have a deletion obligation covering the people named in those snapshots. The baseline marked as the
reference is never deleted, however old it is.

## Define operating hours only where you mean to restrict

Infrastructure resources with **no** availability windows count as available around the clock. Adding
the first window to a resource is therefore a restriction, not documentation. Bookings outside every
window become their own kind of conflict.

---

# Upgrading from a revision older than the first public release

Relevant only to installations predating the first public release. The mechanical test is the schema
revision, not a version number: **if `alembic_version` reads 003 or lower**, there is one check whose
window closes with the upgrade.

## Part-time absences

Run this **before** upgrading. Migration 004 removes the `part_time` absence reason and converts those
rows to `other`; migration 013 then makes them `unplanned`. After that they are **indistinguishable
from genuine other absences**.

```sql
SELECT reason, count(*) FROM absences GROUP BY reason ORDER BY reason;
```

If `part_time` appears, capture the rows first:

```sql
SELECT a.id, r.name, a.start_date, a.end_date, a.allocation_percent, a.note
FROM absences a JOIN personal_resources r ON r.id = a.resource_id
WHERE a.reason = 'part_time';
```

Those rows keep reducing capacity after the upgrade. Part-time now belongs in a `WorkWeekProfile`
instead (ADR-004), so once you assign a part-time profile to such a person **the reduction is counted
twice** — once by the shorter day in the profile and once by the surviving absence. Delete the captured
rows after the profiles are in place.

## Verified against

The migration chain has been run against **PostgreSQL 18**, forwards, back to 003 and forwards again,
with representative data present — including absences using every pre-004 reason, so the mapping is
exercised rather than assumed.
