# Upgrading an existing installation

**Migrations run automatically when the backend container starts.** There is no manual gate —
`app/main.py` runs `alembic upgrade head` during startup. Starting the new image *is* the upgrade, so
everything in step 1 and 2 has to happen before that.

Capado is pre-1.0 and the schema still changes between releases. Read the release notes for the version
you are moving to before starting; anything version-specific lives there, and the sections below are
the procedure that applies every time.

## PostgreSQL 16 to 18

The Compose defaults now use PostgreSQL 18. This is a **database engine upgrade**, separate from
Capado's Alembic migrations. Changing the image tag does not upgrade a PostgreSQL 16 data directory.
PostgreSQL 18 also changes its default data directory to `/var/lib/postgresql/18/docker`; both
Compose files therefore mount the volume at `/var/lib/postgresql`.
[Official image documentation](https://hub.docker.com/_/postgres).

For a fresh installation, use an empty volume and the normal setup procedure. For an existing
installation, choose one of the following paths before deploying the new Compose file:

- **Keep PostgreSQL 16 temporarily:** retain `image: postgres:16-alpine` and the volume mount at
  `/var/lib/postgresql/data`. Capado continues to work with this combination while you prepare
  the database migration. Save this Compose file and the original project name for rollback.
- **Move application data through CSV:** export the full CSV ZIP from the old installation, then
  import it into a fresh PostgreSQL 18 installation as described below.
- **Preserve the complete database with `pg_upgrade`:** follow PostgreSQL's
  [major-version upgrade procedure](https://www.postgresql.org/docs/18/pgupgrade.html), rehearsed
  on a copy of the volume. This requires both server versions and an explicit data-directory
  migration; the normal Capado Compose startup does not perform it.

### CSV migration to a fresh PostgreSQL 18 database

1. Use a Capado version with the full CSV ZIP exporter on the source and destination. If your
   source only offers the legacy five-file exports, update its application first while keeping
   PostgreSQL 16 and its existing volume mount. Then sign in as an administrator and export the
   **full CSV ZIP** in Settings → Import / Export. Stop writes before the final export so later
   changes are not lost. Keep the original volume and archive until the new installation is verified.
2. Save the PostgreSQL 16 Compose file and its application image version. Stop and remove the
   old containers with `docker compose -f docker-compose.prod.yml down`. **Do not use
   `down -v`**, which deletes the database volume. Both installations use the same explicit
   container names, so the old containers must be removed before starting the new project.
3. Start the new PostgreSQL 18 stack with a **different, empty volume**. For production Compose,
   use a new project name consistently for every command; this generates a separate managed
   database volume while preserving the old one:

   ```bash
   docker compose -p capado-pg18 -f docker-compose.prod.yml up -d
   ```

   If you already set `COMPOSE_PROJECT_NAME`, note its old value for rollback. Reuse the
   configured database credentials and application secrets from your existing deployment.

   For development, the external volume name is independent of the Compose project. Create a
   fresh volume and set `CAPADO_DEV_DATABASE_VOLUME=capado_postgres18_data` in the development
   environment before starting:

   ```bash
   docker volume create capado_postgres18_data
   ```

4. Create the first administrator in the new installation, using the same email as an exported
   administrator. Import the full ZIP into this otherwise empty installation. The importer
   validates the complete archive before writing; resolve any reported validation errors before
   retrying. It maps the bootstrap account to its exported identity and restores the domain data
   and history in one transaction.
5. Verify projects, resources, assignments, working-time calendars, skills, baselines and user
   scopes. CSV intentionally excludes passwords, active sessions, OIDC subject links and the SMTP
   password. Reset imported users' local passwords or reconfigure OIDC, and configure SMTP and
   the scheduler explicitly before enabling them. See the
   [CSV contract and exclusions](../reference/import-export.md).

For rollback, stop and remove the new project's containers without deleting its volume. Start
the saved PostgreSQL 16 Compose file with the **original project name and application version**;
it still references the untouched original volume. Changes made in PostgreSQL 18 after cutover
are not automatically copied back.

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

For the UTC migration (revision `002`), pre-existing infrastructure booking times
are interpreted as `Europe/Berlin` local clock readings. If an installation used
a different local zone, set `CAPADO_LEGACY_BOOKING_TIME_ZONE` on the backend
*before its first start with the new image*. The migration refuses bookings in
the skipped or repeated hour of a daylight-saving change and lists their IDs;
resolve those timestamps deliberately before retrying. Existing technical
timestamps, such as audit and creation times, are interpreted as UTC.

The same conversion applies to known timestamp fields in baseline snapshots
and audit `from`/`to` values. It changes their representation, not the recorded
plan or decision; date-only fields remain unchanged. Ambiguous historical values
also stop the upgrade, identifying the table and row. Resolve these from reliable
source records (historical JSON can carry an explicit offset), never guess which
occurrence was intended. All changes run in one PostgreSQL transaction: any error
rolls back both schema and data, including previously converted history.

The legacy-source override controls interpretation of old values only, not future
planning rules. Those continue to use `Europe/Berlin`; the global setting controls
display/input. Test the upgrade on a restored backup before deploying.

Regression tests run migrations against real PostgreSQL with a non-UTC session
zone, baseline comparisons, audit history, and rollback cases. Locally, set
`TEST_POSTGRES_URL` to a **test server** with CREATE DATABASE permission and run
`uv run pytest tests/test_utc_migration_postgres.py`. Each test creates and drops
its own disposable database; the supplied database is not migrated.

### Booking uniqueness

Revision `003` adds uniqueness guards for **identical bookings**, including
resource type, resource, work package, complete period and personal allocation.
Different bookings of the same resource/work package remain allowed. The migration
stops and lists the assignment IDs if it finds identical legacy rows. It does not
delete bookings, conflict links, audit history or baseline entries. Review those
rows on a restored backup, correct the intended bookings explicitly, then retry.

Read-only checks before upgrading:

```sql
SELECT resource_id, work_package_id, start_date, end_date, allocation_percent,
       array_agg(id ORDER BY id) AS assignment_ids
FROM assignments WHERE resource_type = 'personal'
GROUP BY resource_id, work_package_id, start_date, end_date, allocation_percent
HAVING count(*) > 1;

SELECT resource_id, work_package_id, start_at, end_at,
       array_agg(id ORDER BY id) AS assignment_ids
FROM assignments WHERE resource_type = 'infrastructure'
GROUP BY resource_id, work_package_id, start_at, end_at
HAVING count(*) > 1;
```

### Calendar integrity

Revision `004` ensures at most one default site and work-week profile, an active
default site, and non-overlapping bindings for each resource or group. Date ranges
are inclusive; an omitted end remains open. A resource binding may coexist with
its group's binding because individual overrides retain priority.

The migration stops with row IDs on multiple defaults, inactive default sites,
invalid binding targets/periods or overlapping bindings. No row is selected or
deleted automatically. Check and resolve these on a restored backup before retrying:

```sql
SELECT id, name FROM sites WHERE is_default;
SELECT id, name FROM work_week_profiles WHERE is_default;
SELECT id FROM sites WHERE is_default AND NOT is_active;
SELECT id FROM resource_work_profiles
WHERE (resource_id IS NULL) = (group_id IS NULL) OR valid_until < valid_from;
SELECT a.id, b.id FROM resource_work_profiles a
JOIN resource_work_profiles b ON a.id < b.id
  AND (a.resource_id = b.resource_id OR a.group_id = b.group_id)
  AND daterange(a.valid_from, a.valid_until, '[]') &&
      daterange(b.valid_from, b.valid_until, '[]');
```

The binding guards use PostgreSQL's [range exclusion constraints](https://www.postgresql.org/docs/current/rangetypes.html#RANGETYPES-CONSTRAINT)
with [btree_gist](https://www.postgresql.org/docs/current/btree-gist.html). The migration
installs that trusted extension if necessary; the migration account needs CREATE
on this database, or an operator must install it beforehand. It does not need
superuser privileges for this trusted extension. The standard Compose deployment
runs migrations as the PostgreSQL bootstrap/database owner. For a restricted
external migration role, grant database CREATE during the upgrade or have the
operator preinstall `btree_gist`; table ownership alone is insufficient. A denied
extension installation rolls back revision 004, leaving revision 003 and all
existing data intact. Downgrading leaves
the extension installed because other applications may also use it.

A fresh installation may initially lack a default. Once selected, supported HTTP
and CSV writes require replacing it with another default instead of clearing it.
Default swaps are atomic and HTTP changes are audited; CSV row order does not
matter. PostgreSQL guards also protect imports and concurrent writes.

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

`build-images.yml` checks every night whether `main` moved since the last successful publication. It
also rebuilds unchanged sources after seven days so moving base-image security fixes reach `:edge`.
If neither condition applies, the nightly run stops after the cheap decision job.

To publish immediately instead of waiting for the next night:

```bash
gh workflow run "Build images" -f force=true
gh run watch
```

Roughly 9–10 minutes for both images on both platforms (measured: backend 248s, frontend 306s).
Candidates are pushed by digest, scanned, and only promoted to public tags after both backend and
frontend pass. A failed build or scan therefore leaves the previous `:edge` tag in place.

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

Migration `002` intentionally cannot be downgraded: once booking instants and
their configured display zone have changed, converting back would lose their
meaning. Restore the pre-upgrade database dump and previous images instead.
Other migrations may also be lossy:

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
