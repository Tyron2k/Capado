# Local Development Setup

## Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)
- Git
- Node.js 20 or newer for frontend development outside Docker. CI builds on 24; the test toolchain
  (Vitest 5, jsdom 30) does not run on Node 18, which is past end of life
- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) for backend development outside Docker.
  `requires-python` in `backend/pyproject.toml` is the authority, and CI runs 3.12

## Quick start (Docker)

```bash
git clone <repo-url> capado && cd capado
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD
docker compose up -d
```

Services will be available at:
- Frontend: http://localhost:3000
- Backend: http://localhost:3001/docs
- Database: localhost:5432

The development frontend sends API requests to the same-origin `/api` path.
Vite proxies them to the backend, so login and the rest of the app use the
same URL scheme whether the frontend runs natively or in Docker. Do not set
`VITE_API_BASE_URL` to a bare backend URL such as `http://localhost:3001`:
that omits the backend's `/api` prefix and makes login return 404.

On first visit, you'll be redirected to the setup page to create the
initial admin account.

### Creating the first admin without a browser

The setup page posts to an endpoint you can call yourself, which is the path for a scripted
deployment that needs the account to exist before anyone opens a browser:

```bash
curl -X POST http://localhost:3001/api/auth/setup \
  -H 'Content-Type: application/json' \
  -d '{"name": "Admin", "email": "admin@example.com", "password": "at-least-8-chars"}'
```

It answers **403 once any user exists** — setup is a one-time door, not an admin-creation API. It is
also rate-limited like the login endpoint.

Once a user exists this door is closed. From then on an **administrator** creates accounts and can
reset a password through `PUT /api/users/{id}`; there is no self-service reset and no reset mail. What
that leaves open is the case where nobody with admin rights can log in — see
[known limitations](../reference/known-limitations.md#local-passwords-cannot-be-reset-by-their-owner).

## Backend (native)

```bash
cd backend
uv sync                   # install dependencies from lockfile

# Run against the docker database:
export DATABASE_URL=postgresql+asyncpg://capado_user:capado_secret@localhost:5432/capado
uv run uvicorn app.main:app --reload --port 3001
```

Tests:

```bash
cd backend
uv run pytest                                  # full suite
uv run pytest tests/test_docs_coverage.py      # one file
uv run pytest -k conflict                      # by name
```

Pytest is configured solely in `backend/pyproject.toml` under
`[tool.pytest.ini_options]`; the suite runs in parallel via pytest-xdist
(`-n auto`). Do not add a `backend/pytest.ini` — it would take precedence and
silently disable that configuration.

## Frontend (native)

```bash
cd frontend
npm install
npm run dev               # Vite dev server on :3000
npm run test              # Vitest single run
npm run lint              # ESLint
npm run build             # Type-check + production build
```

### Type checking

Use `npm run build` (or `npx tsc -b`) to type-check. The root `tsconfig.json` is
a solution file with `files: []`, so a bare `npx tsc --noEmit` silently checks
**nothing**. `tsc -b` builds three projects:

| Project | Scope |
|---------|-------|
| `tsconfig.app.json` | application sources (`src`, without tests) |
| `tsconfig.node.json` | Vite/tooling config |
| `tsconfig.test.json` | test files and `src/testUtils` (adds `vitest/globals`, `node`) |

Tests are type-checked too, so stale fixtures and outdated mocks fail the build
rather than drifting unnoticed.

## Pre-commit hooks

```bash
prek run -a    # runs all linters/formatters
```

Equivalent to `pre-commit run --all-files` but faster. Must pass before
every commit.
