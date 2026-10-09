# Adding a Feature

## Workflow

1. **Create a spec** in `.kiro/specs/<feature-name>/`
   - `requirements.md` — EARS-format acceptance criteria
   - `design.md` — data model changes, API design, component structure
   - `tasks.md` — ordered implementation tasks

2. **Branch** from `main`: `feat/<feature-name>`

3. **Implement** following the task list:
   - Backend: model → schema → service → router → tests
   - Frontend: generate API types → API client → feature components → tests

4. **Document** as you go (docstrings, OpenAPI descriptions).

5. **Verify** — run `prek run -a` and full test suite.

6. **PR** — conventional commit messages, link to spec.

## Two gates that fail a pull request, and are easy to miss

Both are enforced by tests, so forgetting them shows up as a red build rather than as review feedback.

**A new endpoint or table needs a documentation row before the suite passes.**
`backend/tests/test_docs_coverage.py` asks the running app for its OpenAPI schema and SQLAlchemy
metadata, then checks that every endpoint appears in [api.md](../reference/api.md) and every table in
[data-model.md](../reference/data-model.md). Note what it does **not** check: that the row is *true*.
It gates presence only, so a wrong description passes — and a frontend route is not covered at all.

**A new user-visible string needs both locale files.** `frontend/src/i18n/dictionaries.test.ts`
enforces key parity between `de.json` and `en.json` and checks placeholder syntax. Adding a key to one
file alone fails the suite. German is the authoritative wording; English follows it.

What neither gate covers: the in-app help under `frontend/src/features/help/content/{de,en}/` has **no**
gate. It is the surface that has drifted furthest in the past, precisely because nothing fails when it
goes stale. Its content lives in TypeScript template literals, so a backtick in prose must be escaped
as `` \` ``.

## Where to put things

| What | Where |
|------|-------|
| DB entity | `backend/app/models/` |
| Request/response shape | `backend/app/schemas/` |
| Business logic | `backend/app/services/` |
| HTTP endpoint | `backend/app/routers/` |
| Frontend page/feature | `frontend/src/features/<name>/` |
| Shared component | `frontend/src/components/` |
| API client function | `frontend/src/api/` |
| TypeScript types | `frontend/src/types/` |

## Conventions to check before writing UI code

- [Layout components](../reference/layout-components.md) — pages must use the
  shared `PageLayout` / `PageTabs` / `DataTable` primitives.
- [Date handling](../reference/date-handling.md) — required reading for any
  screen with date inputs or day arithmetic.

## Generate the API contract

The backend Pydantic schemas own HTTP request/response shapes. From `frontend/`, run:

```bash
npm run api:generate
npm run api:check
```

Install the locked frontend dependencies with `npm ci` and have `uv` available. The command exports
OpenAPI from the real FastAPI app in an empty working directory with a fixed test environment. It
never loads operator `.env` files or inherited credentials, opens a database connection, enters the
application lifespan, runs migrations or starts maintenance. No running backend is needed.

Commit `src/api/generated/schema.d.ts` with schema changes. Do not edit or format this file by hand;
the pinned generator's built-in drift check runs in the existing lint job. All JSON API domains use
generated component/operation aliases. Request bodies and query parameters use `ApiBody`/`ApiQuery`;
responses use `ApiResponse` or generated component aliases. Keep hand-written types for UI projections
only, rather than copying transport fields. Axios authentication and TanStack Query
invalidation remain in the existing clients. Complete collection clients unwrap
`{items,total}` and load every page before exposing the list, so local table filters cover the full set.
Dates stay ISO strings; nullable fields and omitted update keys have different meanings.

The generator currently advertises a TypeScript 5 peer although the application uses TypeScript 6.
A narrow npm override uses the application's compiler for this tool only. Its output was compared
byte-for-byte with the same pinned generator under TypeScript 5.9.3; the generated application builds
under TypeScript 6. Remove the override when the generator's peer range supports the application.

## Stateful master-data tables

`ProjectsTable` and `ResourcesTable` own sorting, filters, visibility and selection; `ProjectsPanel` keeps CRUD, folders,
permissions and query invalidation. Mantine supplies the accessible controls and presentation;
TanStack Table supplies table state. Selection is limited to the filtered folder scope: filtering out
or deleting a row removes its selection, and changing folders clears selection. Selected-only display
and clear selection are the supported selection actions; no mass mutation is advertised.

Projects, personnel and infrastructure now share the concrete TanStack feature configuration and
small `ColumnPicker`/`SortHeader` controls. Each feature owns its columns, permissions and actions;
there is no generic CRUD grid. Resources offer group/site filters, conflict-only display and search
across name, group and site. Group filters use IDs, preserving different groups with the same name.
Resource selection is pruned when rows are filtered/deleted and resets when switching resource type.
Selected-only display and clear selection remain the supported selection actions.

Column visibility and horizontal scrolling accommodate long names. Keep simple tables, Gantt and
the skill matrix as they are. Extend shared controls only when another real use case needs them.

The larger UI change was checked on a local running feature branch with a disposable PostgreSQL
installation and synthetic projects, then built for production locally. This does not add browser jobs
to CI. Cover the selection/filter semantics with component tests and still inspect the actual UI.
