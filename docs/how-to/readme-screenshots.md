# Refresh the README screenshots

Use the fully integrated UI on `main`, after its complete CI run passes. The
capture uses the existing development Docker Compose stack and Playwright
dependency. It runs a separate, disposable stack; it does not use your usual
development database, credentials or browser profile.

## Run

Start Docker and use a fresh checkout without `.env` files. Fetch `origin/main`
before running. The script refuses backend/frontend changes relative to that
source and reserves `127.0.0.1:43800` for its own frontend.

```sh
git fetch origin main
cd frontend
npm ci
npx playwright install chromium
cd ..
node docs/how-to/capture-readme.mjs
```

The script derives its temporary Compose configuration from `docker-compose.yml`.
Each run owns unique container/network names and a uniquely named database
volume. The database namespace is `capado_e2e_readme_*`; the fictional bootstrap
account is created only in that empty database. All planning data is then saved
through the real API, including a verified overbooking. The stack and its volumes
are removed on success or failure. If the process is forcibly killed, inspect
Docker's `capado-readme-*` projects and clean up only that interrupted demo stack.

## Data and capture

The fixture contains four projects (ongoing, completed and upcoming), eight work
packages, eight fictional people in three teams, three machines, two fictional
sites and a default 40-hour week. Twelve assignments produce different loads and
an intentional overlap. Atlas has a promised delivery before its planned finish.
None of these names identifies a real person or customer.

Dates are relative to the current week in Europe/Berlin. The browser's date is
held on that same planning day; timers still run. A future refresh naturally uses
a new week instead of showing obsolete dates. Compare DE/EN within one run.

Both languages use light mode, an expanded sidebar, comfortable table density,
the same `#327e78` company accent and a **1600 × 1000** viewport. This gives the
expanded project Gantt enough room for its day axis, weekends and current day.
The script waits for requests, charts and rows, hides transient tooltips and
captures the actual running application without API mocks or DOM substitutions.
The final output records the source SHA, planning day and fixture counts.

It replaces only these existing PNG files in `docs/assets/screenshots/`:

- `dashboard-de.png` and `dashboard-en.png`
- `gantt-projects-de.png` and `gantt-projects-en.png`
- `people-de.png` and `people-en.png`

Open **all six** images and check loading/errors, clipping, chart labels, Gantt
conflicts, language and confidential information. Keep README and documentation
landing-page captions consistent with what is actually visible. Run the strict
MkDocs build with the pinned `.github/docs-requirements.txt` dependencies, check
relative links and review PNG sizes before committing. This is a manual
documentation tool; the normal frontend test suite does not run it.
