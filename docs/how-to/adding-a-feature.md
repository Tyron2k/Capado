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
`backend/tests/test_docs_coverage.py` asks the running app for its OpenAPI schema and SQLModel
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
the pinned generator's built-in drift check runs in the existing lint job. Project, folder, work-package,
requirement, dependency, overview and schedule aliases use it. Other domains still have handwritten
contracts and should move one complete feature at a time. Axios authentication and TanStack Query
invalidation remain in the existing clients. Paginated project and work-package clients unwrap
`{items,total}` and load every page before exposing the list, so local table filters cover the full set.
Dates stay ISO strings; nullable fields and omitted update keys have different meanings.

The generator currently advertises a TypeScript 5 peer although the application uses TypeScript 6.
A narrow npm override uses the application's compiler for this tool only. Its output was compared
byte-for-byte with the same pinned generator under TypeScript 5.9.3; the generated application builds
under TypeScript 6. Remove the override when the generator's peer range supports the application.

## Project table pilot

`ProjectsTable` owns sorting, filters, visibility and selection; `ProjectsPanel` keeps CRUD, folders,
permissions and query invalidation. Mantine supplies the accessible controls and presentation;
TanStack Table supplies table state. Selection is limited to the filtered folder scope: filtering out
or deleting a row removes its selection, and changing folders clears selection. Selected-only display
and clear selection are the supported selection actions; no mass mutation is advertised.

For this pilot, column visibility and horizontal scrolling provide room for long project names.
Column resizing would add handles, persistent sizing state and touch/keyboard interactions without
solving a demonstrated need in this compact overview, so it is deferred. Personnel and infrastructure
lists are plausible next candidates if the same sorting/filtering need arises. Keep simple tables,
Gantt and the skill matrix as they are; extract a shared grid only after a second real use case.

The larger UI change was checked on a local running feature branch with a disposable PostgreSQL
installation and synthetic projects, then built for production locally. This does not add browser jobs
to CI. Cover the selection/filter semantics with component tests and still inspect the actual UI.
