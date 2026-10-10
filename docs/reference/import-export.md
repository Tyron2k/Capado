# Import and export

The five existing page exports now produce complete, versioned **area CSVs**. Five additional areas
cover working time, the skill catalogue, absences, administration and history. The all-data ZIP
bundles **exactly these ten CSVs**, from one consistent snapshot, plus a manifest. It has no separate
migration-only CSV format or serializer. The same validator and writer handle both individual areas
and the full bundle. All routes are under `/api/`.

## Implementation ownership

Each module in `backend/app/services/import_export/` owns one complete CSV area: its explicit field
allowlists, export selection, import validation and write policies. The existing personnel,
infrastructure, project, template and assignment modules retain their legacy Excel/flat import paths.
Working time, skills, absences, administration and history have their own modules as well.

- `csv_format.py` handles versioned headers, cell encodings, parsing and file limits. Domain schemas
  explicitly identify JSON/binary fields and validation defaults.
- `csv_storage.py` supplies database reads, ID-based writes, hierarchy ordering, foreign-key checks
  and the shared import context. It neither changes domain fields nor commits transactions.
- `csv_transfer.py` coordinates the registered domain functions, the ZIP manifest, a consistent export
  snapshot and one import transaction. `__init__.py` explicitly registers domains in dependency order.

Imports prepare administrator/history identities, build the planned destination state and run all
domain validators before writing. Individual CSVs use the same domain importer as ZIP members.
Only the coordinator commits; even a failure in the last domain rolls back earlier writes. Conflict
recalculation runs after commit and reports its own failure separately from the completed import.

Standalone imports lock/read their own tables and the reference/dependent tables explicitly needed
for validation. Booking, absence, qualification, availability, calendar-exception and historical
detail rows are matched by supplied IDs. Unrelated audit history and technical tables are not loaded
or locked. Existing destination rows do not count toward upload limits. Changes to referenced skill
attributes still validate existing external requirements before writing.

Conflict refresh is scoped to supplied resources and old/new booking, absence and calendar-binding
targets. Changes to a shared default calendar or the planning time zone refresh all booked/conflicted
resources; catalogue, project, template and history imports need no capacity-conflict refresh.

**All imports are admin-only.** Administration/history exports and the full ZIP also require an
administrator. The other area exports and the existing Excel reports require a login.

| Area | Existing export/import | Additional/shared route | UI |
|------|------------------------|-------------------------|----|
| Personnel | `/personnel/export?format=csv`, `/personnel/import` | `/data/personnel/export`, `/data/personnel/import` | People → Administration |
| Infrastructure | `/infrastructure/export?format=csv`, `/infrastructure/import` | `/data/infrastructure/export`, `/data/infrastructure/import` | Infrastructure → Administration |
| Projects | `/projects/export?format=csv`, `/projects/import` | `/data/projects/export`, `/data/projects/import` | Projects → Administration |
| Templates | `/templates/export?format=csv`, `/templates/import` | `/data/templates/export`, `/data/templates/import` | Projects → Administration |
| Assignments | `/assignments/export`, `/assignments/import` | `/data/assignments/export`, `/data/assignments/import` | Planning → Administration |
| Working time | — | `/data/working-time/export`, `/data/working-time/import` | Working time |
| Skills | — | `/data/skills/export`, `/data/skills/import` | Resource Administration → Skills |
| Absences | — | `/data/absences/export`, `/data/absences/import` | Planning → Administration |
| Administration | — | `/data/administration/export`, `/data/administration/import` | User management |
| History | — | `/data/history/export`, `/data/history/import` | Baselines |
| All areas | `/migration/export`, `/migration/import` | CSV ZIP | Settings → Import / Export |

Exports use GET; imports use POST. Settings also offers every individual area for a complete manual
workflow. Personnel/infrastructure retain their matrix and editable flat Excel formats. Projects and
templates retain Excel reports. **Excel has its original, narrower scope; complete data is in CSV.**
Old flat CSVs and editable Excel files remain importable on the five original routes.

## Complete area CSVs

Each file starts with `Capado CSV;2;<area>`, followed by a header with `Record Type` and the union of
that area's explicit allowlisted fields. Every data row belongs to exactly one record type and fills
only that type's columns. This preserves empty groups/folders, unused catalogue entries and records
without children without duplicating them in a flattened join. IDs and foreign keys identify objects;
duplicate display names are safe. The columns/schema are shared by standalone downloads and ZIP members.

Individual imports validate **the whole file** before committing. They insert new IDs and update
existing IDs; records omitted from the file remain unchanged. Editing an assignment with the same ID
updates that booking; distinct IDs remain separate only when their complete booking identities differ. External references
must exist in the destination. A missing dependency, invalid field/reference/graph or a constraint
failure rejects the entire area with zero rows written. Public user fields can be updated without
replacing existing credentials. Imported organization settings disable email and maintenance.

For manual imports into an empty installation, use this order:

1. `working-time.csv`, then `skills.csv`.
2. `personnel.csv` and `infrastructure.csv` (groups, qualifications and resource-specific working time).
3. `projects.csv` and `templates.csv` (customers, hierarchies, metadata and full requirements).
4. `assignments.csv` and `absences.csv`.
5. `administration.csv`, then `history.csv`.

Skip any area you do not need, provided its referenced records already exist. History includes public
email reference columns for authors/actors so separately importing administration and then history
also maps the source administrator to the destination bootstrap account. Historic user entity IDs
follow that mapping. The ZIP validates all references together, requires an empty target and restores
every area in **one transaction**, without manual ordering. Individual imports are separate transactions;
if a later file fails, earlier successful area imports remain in place.

## Legacy editing files

The following sections describe **old flat CSVs and Excel**, not the new complete area CSVs. They
remain supported for name-based editing, with their original scope and partial-row error semantics.

### How legacy editing files are read

The extension is **required**, not guessed: only `.xlsx` and `.csv` are accepted, and anything else is
rejected with a message naming the two. This changed — the parser used to try Excel and fall back to
CSV for unrecognised names, so a `.pdf` failed three layers down as "could not read the header", a
complaint about the content of a file that was never the right kind.

A file named `.xlsx` that is not a workbook (an old `.xls` renamed, most often) is rejected as such
rather than retried as CSV, and a `.csv` that is not UTF-8 is rejected with the "Save as CSV UTF-8"
instruction rather than a decoding traceback.

#### The resource file shape is checked before any legacy row is read

Row 0 must be the header and must **start with `Name` and `Group`, in that order**. Matching ignores
case and surrounding whitespace, because Excel adds trailing spaces and people retype headers.

Order is enforced rather than detected: columns are read positionally, so a file with the two swapped
would import every group name as a resource name — silently, and as a bulk write. It is refused.

Three verdicts:

| Verdict | What it means | What the message says |
|---------|---------------|-----------------------|
| flat | The re-importable shape | nothing, the import proceeds |
| matrix | The skill-matrix **export**, whose header is on row 1 | use the flat Excel or CSV export instead |
| unknown | Neither | which columns row 0 must start with |

The matrix case exists because the old message — "Header must have at least: Name, Group" — was true,
useless, and pointed the reader at their own edits rather than at the file they picked. The skill
matrix fails for structural reasons no amount of editing can fix.

CSV is decoded as **UTF-8 with an optional byte-order mark** (`utf-8-sig`), which is what Excel writes
when you "Save as CSV UTF-8" — so a file exported from Excel and re-imported round-trips without the
first column header acquiring an invisible prefix.

The **delimiter is a semicolon** (`;`), matching what a German Excel installation produces by default.

Excel files are read from the **first worksheet**; a workbook with several sheets ignores the rest.

Dates are **ISO, `YYYY-MM-DD`**. Infrastructure assignments also accept ISO timestamps
with an explicit UTC offset; new exports use UTC timestamps and retain seconds and microseconds.

## Columns

### Personnel and infrastructure

```
Name;Group;Skill;Attribute;Site
```

`Name` and `Group` are required; `Skill`, `Attribute` and `Site` are optional. One row per skill
assignment, so a person with three skills is three rows repeating name, group and site.

**Missing skills and attributes are created.** That is convenient and it is the reason the import is
admin-only: a typo in the `Skill` column does not fail, it silently adds a skill to the global
catalogue that everybody then sees.

**A missing site is NOT created — the row is rejected.** This is the one column that deliberately
breaks the pattern above, and the reason is what a site owns: the holiday calendar. Creating
`Werk Amendorf` from a missing letter would produce a plant with **no holidays**, and every resource
landing there would silently lose the calendar its capacity arithmetic runs on. A redundant skill is
untidy; a resource under an empty holiday calendar is a plan that is wrong without saying so. The
error names the unknown value and lists the sites that do exist, so a typo is visible next to the
real name. Create the site under Working time first, then re-import.

The `Site` column is located **by its header**, not by position, and both `Site` and
`Betriebsstätte` are accepted (plus the ASCII `Betriebsstaette`, because a CSV round-trip through a
mis-encoded editor loses the umlaut). Two consequences:

- **A file without a `Site` column leaves the site untouched.** Every file exported before the column
  existed re-imports exactly as before rather than unfiling every resource in it.
- **A `Site` column with an empty cell REMOVES the site.** Without that, the Excel round-trip could
  add a site but never take one away.

Personnel and infrastructure offer **three** export formats, and the difference matters:

| `format=` | Shape | Re-importable |
|-----------|-------|---------------|
| `xlsx` | Skill matrix: name and group, then one column per skill attribute, header spanning two rows, group separator rows | **no** |
| `xlsx-flat` | The flat list as a workbook | yes |
| `csv` | Complete versioned area CSV, including inactive resources, hierarchies, full qualifications and resource-specific working time | yes, atomically |

The matrix is meant for reading and for filling in on paper, not for machines — its header is on the
second row, so the importer cannot read it. Anything other than these three values is rejected with
400; an unknown value used to fall through to the matrix silently, which handed back a file that looked
right and could not be imported.

`xlsx-flat` exists because "editable in Excel" and "re-importable" were previously mutually exclusive
for these two entity types.

### Projects

```
Project;Project Start;Project End;Work Package;WP Start;WP End;Skill;Attribute;Quantity
```

`Project`, `Project Start` and `Project End` are required. One row per work package requirement, so
project and work package repeat down the rows.

### Templates

```
Template;Description;Skill;Attribute;Quantity
```

Templates are matched **by name** and created or updated. Unlike the personnel import, **skills and
attributes must already exist** here — a template row naming an unknown skill is an error, not an
invitation to create one.

### Assignments

```
Project;Work Package;Resource;Start;End;Allocation;Resource Type;Resource Group
```

Columns are located by their header, ignoring case and surrounding whitespace. Duplicate headers
are rejected. Extended legacy editing files append `Resource Type` (`personal` or `infrastructure`) and `Resource Group`
to distinguish repeated resource names. Both values must be filled when their column is present.
Even with those columns, more than one match is an error; the importer never selects the first match.

Six-column legacy files without type/group remain accepted when the resource name is unique.
Legacy five-column files also omit `Work Package`. Automatic resolution requires exactly one
overlapping work package; if none overlap, it requires exactly one work package in the project.
Ambiguous project or work-package names are errors too. Use unique names before migrating; the
legacy project CSV cannot distinguish equally named projects in different folders.

Personal `Start`/`End` remain dates and `Allocation` retains fractional values, e.g. `33.5`.
Allocation must be finite, greater than zero and no more than 100; a blank cell defaults to 100.
Infrastructure `Start`/`End` in extended legacy files may be precise timestamps, e.g.
`2026-10-25T00:15:23.123456+00:00`. Offset-free timestamps are rejected, because the repeated hour at
the end of daylight saving time cannot be resolved safely. Infrastructure is always exclusively
allocated; its exported allocation is 100.

Date-only infrastructure values in older files still become 06:00 on the start day and 18:00 on the
end day in the planning zone. **Old exports have already lost the original times.** Updating Capado
cannot recover them; export again from the source installation after upgrading.

## How references are resolved

Legacy references are matched **by name, case-insensitively** — projects, work packages, resources,
templates, skills. Assignment files additionally qualify resources by type and group when supplied.
Legacy files contain no internal identifier; these imports generate new IDs. Complete area CSVs use IDs instead.

The consequence is worth stating plainly: **renaming something in Capado invalidates every stored
import file that names it.** This is why renaming a skill is restricted to administrators.

## Duplicates, errors, and what actually gets written

A duplicate assignment — **same resource type, resource, work package, full interval and
allocation** — is skipped. Separate bookings of the same resource/work package are retained.

The API and preview use this same full booking identity. PostgreSQL unique indexes
also reject identical bookings from concurrent requests; different periods or
allocations remain independent bookings. In versioned CSVs, IDs identify updates:
two different IDs cannot represent an identical booking, and the import rolls
back with a row error if the planned result contains one.
Equivalent UTC instants with different offsets count as the same interval. Re-importing an unchanged
file creates no additional assignments; editing an interval or allocation creates a separate booking,
it does not replace the previous one. Exactly identical rows are collapsed, including within a file.
Personnel, infrastructure and template rows are matched by name and **updated** where they already
exist.

A bad row does not abort the import. Each is checked and, when it fails, counted and described in the
response:

```json
{ "created": 12, "updated": 3, "skipped": 2, "errors": ["Row 7: Project 'Foo' not found."] }
```

Errors name the row number, which is the row in the file including the header — so `Row 7` is the
seventh line, not the seventh record.

**Accepted rows are committed together at the end.** Row errors do not roll back other accepted
rows. Assignment validation completes before adding a row. The project/template importers can create
their parent record before reporting an invalid requirement, so always review the error list and the
resulting data before treating a migration as complete.

Rows that are skipped are **not** written and are not retried. Fix the file and re-run: names already
present will be updated rather than duplicated.

## Conflict checks

Resource and assignment imports refresh conflicts for affected resources after committing the data.
The response reports `conflicts_found`. If the check fails, `conflict_check_failed` is true and the
imported data remains saved. Resolve that failure before relying on the conflict view.

## Complete migration to an empty installation

Use **Settings → Import / Export** on both installations. The complete export is `capado-csv.zip`,
containing UTF-8, semicolon-delimited CSV files and `manifest.csv`. It contains no database SQL.
`GET /api/migration/export` and `POST /api/migration/import` both require an administrator.

1. Upgrade source and destination to the same release supporting the complete migration format.
2. Export the CSV package from the source. Keep the original installation available for comparison.
3. Set up and sign in with the destination's bootstrap administrator. Do not create sites, profiles,
   resources, projects or additional accounts there first.
4. Upload the **unchanged ZIP** under Settings → Import / Export. Do not unpack/import its files
   individually. The importer restores the catalogue, hierarchies and relationships in dependency order.
5. Check the result and conflict check, then compare capacity, eligibility, requirement coverage and
   baseline drift with the source. Reset imported users' passwords or configure/relink their OIDC login.
6. Configure the mail credential and explicitly enable mail/maintenance when ready. Both switches
   start disabled to prevent sending digests or pruning imported history during verification.

The destination must contain no planning/master data. Its one active bootstrap administrator,
organization settings and setup audit entries are allowed. Existing planning data or additional
accounts cause rejection, with **nothing overwritten**. Source settings replace the target's settings.
The bootstrap account/password/session/identity binding remains usable. If the same email occurs in
source users, that source account must be an active administrator: it maps to the bootstrap ID, along
with baseline authors and audit actors. Otherwise the bootstrap account remains as an additional admin.

| CSV file | Preserved data |
|----------|----------------|
| `working-time.csv` | Complete sites, active/default flags, regions, weekly profiles and holiday/exception minutes |
| `skills.csv` | Complete skill/attribute catalogue for both resource types, including unused entries |
| `personnel.csv` | Active/inactive people, personal group hierarchies/empty groups, site links, qualification levels/validity and dated work-profile bindings |
| `infrastructure.csv` | Active/inactive infrastructure, its group hierarchy/empty groups, site links, qualification levels/validity, dated profile bindings and local-clock availability windows |
| `projects.csv` | Customers, folder trees, projects, work packages, ordering/references/priority/commitments, completion/lead times, full requirements and dependency lags |
| `templates.csv` | Templates, descriptions, lead times and full requirement modes/quantities/minimum allocation/minimum level |
| `assignments.csv` | Dates/UTC timestamps including microseconds, fractional allocations and distinct booking IDs |
| `absences.csv` | Absence dates, reasons, allocations, status and notes |
| `administration.csv` | User names/emails/roles/active state/scopes/personal-resource links, branding/logo, organization configuration; activation switches disabled on import |
| `history.csv` | Baselines/snapshots/current selection and audit history, including authors/actors |

The ten files cover 27 persisted planning/administrative/history tables. Resource groups and week-profile bindings are partitioned
by resource type between personnel and infrastructure, with each row exported once. Entity fields use
explicit allowlists; a coverage test requires every new model field/table to receive a migration or
exclusion decision. Original IDs and timestamps are retained. The source-admin-to-bootstrap mapping is
the one ID exception. Each successful standalone import adds an audit event; a full ZIP restore adds
one event for the transaction. Standalone downloads are verified byte-for-byte against ZIP members.

### Format and exclusions

The version-2 manifest records the format, version, filename, row count and SHA-256 for each CSV.
Version 2, every registered filename exactly once, matching columns, row counts and checksums are required.
Do not edit a ZIP package. Edit the standalone area CSV to make selective changes; preserve its
metadata/header/IDs and keep unused record-type cells empty. The ZIP checksums validate transfer integrity.

Dates use ISO form and timestamps include their UTC offset. `\N` means SQL NULL; a literal string
starting with a backslash has an extra leading backslash, so empty strings and literal `\N` values
remain distinguishable. List/dictionary cells (scopes, snapshots, audit changes) contain JSON; uploaded
logo bytes are base64 in their CSV cell. The archive is read directly and never extracted to disk.

Password hashes, SMTP passwords, OIDC identity bindings, password-change state and refresh/session
credentials are excluded. Imported accounts have no usable local password and require password reset;
the bootstrap account keeps its credentials. Historic credential values in audit changes are redacted.
Conflicts and their links are recalculated after import; maintenance-run state is installation-specific
and excluded. Deployment environment/secrets and browser preferences are also configured separately.
This scope is deliberately defined: a CSV migration does not copy live sessions or secret credentials.

### Legacy five-file exports

Old five-file exports contain only the original flattened data. They cannot recover omitted calendars,
qualifications, metadata or original infrastructure times. Re-export from an upgraded source to obtain
the complete area CSVs. New manual exports and the ZIP contain the same data; completeness no longer
depends on choosing the ZIP.

## Limits

Legacy flat CSV/Excel imports reject uploads over **20 MiB** or **10,000 rows including the header** with HTTP 413,
before any data is written. Uploads are read only up to 20 MiB plus one byte. There is no separate
time limit or cap on an Excel file's decompressed contents — see [known limitations](known-limitations.md).

Parsing runs in a thread pool rather than on the event loop, so a slow file does not block other
requests.

Complete area CSVs are limited to 100 MiB and 200,000 records per file, with fields bounded to 4 MiB
of UTF-8 data. The same limits apply during export: an oversized historical field is rejected with
its file, row and column instead of producing a download that cannot be imported. Typed values and
reference errors also retain their field and source row; related destination errors identify the record.
The same row/field codec is used for the ZIP. The complete CSV package has envelope limits: 50 MiB uploaded/compressed, 100 MiB expanded, and
200,000 entity rows in total. Logo data remains capped at 2 MiB. Decompression, manifest integrity and
row/field validation are bounded before restoration; parsing and archive construction run in a thread.
