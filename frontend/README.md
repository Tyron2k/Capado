# Capado frontend

React 19 + TypeScript + Vite, with [Mantine](https://mantine.dev/) for components. Talks to the
FastAPI backend over `/api/`.

For the project as a whole see the [root README](../README.md); for how the pieces fit together see
[architecture.md](../docs/explanation/architecture.md), which has a section on the frontend.

## Commands

```bash
npm ci
npm run dev                  # dev server on :3000
npx vitest run               # tests
npx tsc -b                   # type check — note -b, not --noEmit
npx eslint src               # lint
```

`tsc -b` rather than `tsc --noEmit`: the `--noEmit` form can report clean from a stale
`.tsbuildinfo`, which means a type error survives the check that exists to catch it.

## Layout

```
src/
├── api/            Axios clients, one module per resource
├── components/     Shared components and the app layout
├── features/       One directory per feature area — panels, tabs, drawers
│   └── help/       The in-app help under /help, content in de/ and en/
├── i18n/           de.json and en.json
├── hooks/          Shared hooks
└── types/          Shared response and domain types
```

Component conventions — spacing, the panel and drawer patterns, when a tab rather than a page — are in
[layout-components.md](../docs/reference/layout-components.md).

## Two things that bite

**Both locale files change together.** `src/i18n/dictionaries.test.ts` checks key parity and
single-brace placeholders between `de.json` and `en.json`, so adding a key to one without the other
fails the suite. German is authoritative when the two disagree — see
[CONTRIBUTING.md](../CONTRIBUTING.md#languages).

**Dates are plain dates.** Personnel assignments carry dates, infrastructure bookings carry datetimes,
and mixing the two produces off-by-one errors that only appear in certain timezones. The rules are in
[date-handling.md](../docs/reference/date-handling.md).
