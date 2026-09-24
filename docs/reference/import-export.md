# Import and export

Five pairs, all under `/api/import-export/`. Every import accepts `.xlsx` or `.csv` — and **only**
those two. Personnel and infrastructure offer three export formats, projects and templates two,
assignments CSV only.

**All imports are admin-only.** The uploaded file may name resources in any group, so no single scope
could authorise it, and the personnel and infrastructure importers create missing skills as a side
effect — a global-catalogue write. Exports need only a login.

| Entity | Export | Import | Where in the UI |
|--------|--------|--------|-----------------|
| Personnel | `GET /personnel/export?format=xlsx\|xlsx-flat\|csv` | `POST /personnel/import` | People / Infrastructure → admin panel |
| Infrastructure | `GET /infrastructure/export?format=xlsx\|xlsx-flat\|csv` | `POST /infrastructure/import` | People / Infrastructure → admin panel |
| Projects | `GET /projects/export` | `POST /projects/import` | Projects → admin panel |
| Templates | `GET /templates/export` | `POST /templates/import` | Projects → admin panel |
| Assignments | `GET /assignments/export` (CSV) | `POST /assignments/import` | Planning → admin panel |

The UI entry points are `resources/ImportExportBar.tsx` reached from the resources admin panel,
`ProjectAdminPanel.tsx`, and `PlanningAdminPanel.tsx`.

## How a file is read

The extension is **required**, not guessed: only `.xlsx` and `.csv` are accepted, and anything else is
rejected with a message naming the two. This changed — the parser used to try Excel and fall back to
CSV for unrecognised names, so a `.pdf` failed three layers down as "could not read the header", a
complaint about the content of a file that was never the right kind.

A file named `.xlsx` that is not a workbook (an old `.xls` renamed, most often) is rejected as such
rather than retried as CSV, and a `.csv` that is not UTF-8 is rejected with the "Save as CSV UTF-8"
instruction rather than a decoding traceback.

### The shape is checked before any row is read

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

Dates are **ISO, `YYYY-MM-DD`**, on the way in and on the way out. No other format is attempted.

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
| `csv` | The same flat list as CSV | yes |

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
Project;Work Package;Resource;Start;End;Allocation
```

Two column counts are accepted and the importer decides by looking at the header:

- **Six columns** as above.
- **Five columns** — `Project;Resource;Start;End;Allocation` — where the work package is resolved
  automatically as the **first** work package in the project whose date range overlaps the
  assignment. Convenient for a project with one work package; ambiguous the moment two overlap, and
  the importer does not warn about the ambiguity.

`Resource` is looked up among infrastructure first and then among people, and the kind of assignment
created follows from where the name was found. A name that exists as both is therefore resolved as
infrastructure.

## How references are resolved

Everything is matched **by name, case-insensitively** — projects, work packages, resources,
templates, skills. No file contains an internal identifier, which is what makes the format editable
in Excel.

The consequence is worth stating plainly: **renaming something in Capado invalidates every stored
import file that names it.** This is why renaming a skill is restricted to administrators.

## Duplicates, errors, and what actually gets written

A duplicate assignment — **same resource and same work package** — is skipped rather than updated or
rejected. Personnel, infrastructure and template rows are matched by name and **updated** where they
already exist.

A bad row does not abort the import. Each is checked and, when it fails, counted and described in the
response:

```json
{ "created": 12, "updated": 3, "skipped": 2, "errors": ["Row 7: Project 'Foo' not found."] }
```

Errors name the row number, which is the row in the file including the header — so `Row 7` is the
seventh line, not the seventh record.

**The whole import is one transaction.** Every accepted row is committed together at the end, so a
request that fails midway writes nothing. There is no partial import to clean up, and equally no way
to import the first half of a large file and continue later.

Rows that are skipped are **not** written and are not retried. Fix the file and re-run: names already
present will be updated rather than duplicated.

## Conflicts are not recalculated

An import writes assignments directly, which bypasses the conflict detection that normally runs on
write. After a bulk load, recalculate:

```bash
python -m app.scripts.refresh_conflicts
```

Without it the plan reports no conflicts because none were computed — which looks exactly like a plan
that has none.

## Limits

All five imports reject uploads over **20 MiB** or **10,000 rows including the header** with HTTP 413,
before any data is written. Uploads are read only up to 20 MiB plus one byte. There is no separate
time limit or cap on an Excel file's decompressed contents — see [known limitations](known-limitations.md).

Parsing runs in a thread pool rather than on the event loop, so a slow file does not block other
requests.
