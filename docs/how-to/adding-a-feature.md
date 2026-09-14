# Adding a Feature

## Workflow

1. **Create a spec** in `.kiro/specs/<feature-name>/`
   - `requirements.md` — EARS-format acceptance criteria
   - `design.md` — data model changes, API design, component structure
   - `tasks.md` — ordered implementation tasks

2. **Branch** from `main`: `feat/<feature-name>`

3. **Implement** following the task list:
   - Backend: model → schema → service → router → tests
   - Frontend: types → API client → feature components → tests

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
