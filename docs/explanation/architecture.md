# Architecture

## Overview

Capado is a three-tier application for production scheduling and capacity
planning:

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Compose                        │
├─────────────────┬─────────────────┬─────────────────────┤
│    frontend     │     backend     │         db          │
│  React + Vite   │    FastAPI      │   PostgreSQL 16     │
│     :3000       │     :3001       │       :5432         │
└─────────────────┴─────────────────┴─────────────────────┘
```

## Backend Layers

Requests flow through four layers:

```
HTTP Request
    │
    ▼
┌─────────────────────────────────────┐
│  Router (app/routers/)              │  HTTP concerns: parsing, status codes,
│  - Parse request                    │  response shapes, auth dependencies
│  - Call service                     │
│  - Return response                  │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Service (app/services/)            │  Business logic: validation, computation,
│  - Validate business rules          │  conflict detection, capacity math
│  - Orchestrate DB operations        │
│  - Trigger side effects             │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Model (app/models/)                │  SQLModel entities: define DB schema,
│  - Table definitions                │  relationships, constraints
│  - Relationships                    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Database (PostgreSQL)              │  asyncpg driver, Alembic migrations
└─────────────────────────────────────┘
```

**Schemas** (`app/schemas/`) define Pydantic request/response shapes separately
from models. This decouples the API contract from the database schema.

## Domain Model

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│   Project    │──1:N──│ WorkPackage   │──1:N──│  Assignment  │
└──────────────┘       └──────┬───────┘       └──────┬───────┘
                              │                      │
                              │ 1:N           resource_id (polymorphic)
                    ┌─────────▼──────────┐           │
                    │ WorkPackage        │    ┌──────┴──────────────────────┐
                    │ Requirement        │    │                             │
                    │ (skill + quantity) │    │                             │
                    └────────────────────┘    │                             │
                                    ┌────────▼─────────┐    ┌──────────────▼───────┐
                                    │ PersonalResource  │    │ InfrastructureResource│
                                    │ (group + skills)  │    │ (group + skills)      │
                                    └────────┬─────────┘    └──────────────┬───────┘
                                             │                             │
                                    ┌────────▼─────────────┐    ┌──────────────▼──────────────┐
                                    │ PersonalResourceSkill │    │ InfrastructureResourceSkill │
                                    │ (skill_attribute)     │    │ (skill_attribute)           │
                                    └───────────────────────┘    └─────────────────────────────┘
```

### Key Relationships

- **Project → WorkPackage** (1:N): A project contains multiple work packages.
- **WorkPackage → WorkPackageRequirement** (1:N): Skill requirements stored
  directly on the work package.
- **WorkPackage → Assignment** (1:N): A work package has resource assignments.
- **Assignment → Resource** (N:1): Each assignment points to one resource
  (polymorphic via `resource_id` + `resource_type`).
- **Resource → ResourceGroup** (N:1): Resources belong to named groups
  (hierarchy, replaces free-text department/location).
- **Resource → SkillAttribute** (M:N): Via join tables
  (`personal_resource_skills`, `infrastructure_resource_skills`).
- **Resource → Absence** (1:N): Periods of reduced availability.
- **Resource → Conflict** (1:N): Detected capacity overloads.

### Assignment Shapes

One `assignments` table serves two shapes:

| Shape | Fields | How a conflict arises |
|-------|--------|-----------------------|
| Personal | `start_date`, `end_date`, `allocation_percent` | Demanded **minutes** exceed available minutes on a day |
| Infrastructure | `start_at`, `end_at` (timestamps) | Interval overlap, or a booking outside every availability window. Always 100% exclusive |

## Conflict detection

Conflicts are recalculated per resource whenever an assignment is created, updated or deleted, by
`ConflictService.refresh_conflicts()`.

**This document deliberately does not restate the algorithm.** It is described in
[conflict detection](conflict-detection.md), and the capacity it depends on in
[capacity model](capacity-model.md). A second prose copy here is how this section came to describe a
model that had been replaced: it claimed conflicts arose when `allocation_percent` summed past a fixed
100%, that absences were collected as demand intervals, and that the sweep evaluated one value per span.
All three were true of the pre-working-time model and none of them since — capacity varies *inside* a
span, which is why the current sweep walks each span day by day.

What belongs here is the shape rather than the rule: `ConflictService` owns detection for both
assignment shapes, resolves capacity exclusively through `WorkingTimeService`, and writes `Conflict`
rows with a `cause` discriminator plus `ConflictAssignment` join entries. `ConflictSuggestionService`
proposes resolutions and resolves capacity through the same service, so a suggestion cannot propose a
value the plan then rejects.

## Capacity Computation

```
available = 100% (every day, every resource)
assigned  = sum of active allocation_percent for that day, as minutes
            against a normative 480-minute day; zero on non-working days
available = week profile for the weekday, overridden by a site holiday row,
            reduced by absences
utilization = assigned / available
conflict  = assigned > available
```

A configurable work schedule was previously declared unnecessary on the grounds
that date-range allocation needs no hourly granularity. That was wrong: treating
every calendar day as a full working day overstates a five-day week by roughly
28%, so plans the system called feasible were not. Working time now comes from
`WorkWeekProfile` plus the site calendar — see
[ADR-004](../decisions/004-hours-as-capacity-base.md).

## Authentication & Authorization

```
┌──────────────────────────────────────────────────────────┐
│  Authentication is always required                       │
│  → Bearer JWT on every endpoint except /api/health       │
│  → Access token 15 min, refresh token 7 days, rotated    │
│    — DEFAULTS, overridable per deployment via            │
│    ACCESS_TOKEN_EXPIRE_MINUTES / REFRESH_TOKEN_EXPIRE_DAYS│
│  → Role-based: admin > editor > viewer                   │
│  → Scope-based: editors restricted to their groups       │
│    (scope_group_ids) or projects (scope_project_ids)     │
│  → Rate limit on login/setup: 10 requests per 60 s per   │
│    client, also a default                                │
└──────────────────────────────────────────────────────────┘

First-time setup: POST /api/auth/setup creates the initial admin user
when no users exist in the database.
```

### Roles and Responsibility

- **Admin**: Full access to everything.
- **Editor**: Write access scoped to specific groups (`scope_group_ids`)
  or projects (`scope_project_ids`). Editors with project scopes are
  effectively project managers; editors with group scopes are group managers.
- **Viewer**: Read-only access.

There are no explicit "project manager" or "department manager" roles —
responsibility is derived from User scopes. Users with editor scope do not
need to exist as resource entries.

## Frontend Architecture

```
src/
├── api/            Axios client + per-domain API functions
├── context/        React contexts (Settings, Auth)
├── features/       Feature folders (self-contained screens)
│   ├── admin/
│   ├── auth/
│   ├── conflicts/  (shared components used by planning/ConflictsSection)
│   ├── dashboard/
│   ├── gantt/
│   ├── help/
│   ├── me/          (self-service: what a person may read about themselves)
│   ├── planning/
│   ├── projects/
│   ├── resources/
│   └── settings/
├── components/     Shared UI components (layout, forms)
│   └── layout/     PageLayout, PageTabs, DataTable, SectionHeader, FilterBar
├── hooks/          Custom React hooks
├── types/          Shared TypeScript interfaces
├── i18n/           Internationalization (de/en)
└── router.tsx      Route definitions
```

### Page Structure

Routes and what each one carries:

| Route | Content |
|-------|---------|
| `/` | Dashboard: utilization charts + project KPI table |
| `/people` | Tabs: Employees (grouped table) · Administration |
| `/infrastructure` | Tabs: Resources (grouped table) · Administration |
| `/projects` | Tabs: Projects (CRUD + work packages) · Administration (Templates + Import/Export) |
| `/planning` | Tabs: Overview (unmet requirements + conflicts) · Assignments (CRUD) |
| `/gantt` | Gantt timeline, three perspectives — see below |
| `/my-plan` | Self-service: what the signed-in person may read about themselves. Requires the account to be linked to a scheduled person (`users.resource_id`); an unlinked account gets an explanatory screen, NOT an empty plan |
| `/working-time` | Calendars, week profiles, operating windows, holidays |
| `/baselines` | Plan snapshots and comparison |
| `/audit` | Change log (retained 24 months) |
| `/settings` | Organization settings, admin-only |
| `/help` | This documentation, in-app |
| `/conflicts`, `/project-overview`, `/templates` | Redirects to the pages that absorbed them (ADR-002) |

### The three Gantt perspectives

They answer different questions and are not interchangeable:

| Perspective | Rows | Answers |
|-------------|------|---------|
| Project | every project, expandable to its work packages | where are the gaps across the whole portfolio |
| Personnel / Infrastructure, grouped **by project** | work packages of the selected group | when does this project run |
| Personnel / Infrastructure, grouped **by resource** | one row per resource, occupancy across all projects | what is on this track/booth, and when is it free |

The project perspective has no single-project picker: a gap is only visible with every project on one
axis. The by-resource grouping is a pure client-side re-fold of the same response as by-project — see
`frontend/src/features/gantt/groupByResource.ts` — so the two cannot contradict each other.

Bar colour carries exactly one meaning: **red is a conflict**. Work packages deliberately have no
per-item colours, because that would overwrite the only signal the chart gives. Row banding and a
hover highlight take the job colour was asked for (keeping your place while reading sideways).

### State Management

Two kinds of state, and the distinction is load-bearing:

**Server state** — anything the backend owns — lives in TanStack Query, keyed by
`src/api/queryClient.ts`. No screen keeps its own copy, so a mutation declares what
it made untrue by invalidating keys rather than by remembering to call a reload
function. That convention is the point: the keys are `[domain, kind, …parameters]`,
coarse to fine, every level a valid invalidation prefix, and parameters always in the
key so two filter combinations cannot share one entry.

Invalidation is deliberately COARSE. `['sites']` rather than `['sites','list']`:
over-invalidating costs a request, under-invalidating shows a value that is no longer
true. Several couplings fall out of the key shape rather than being remembered —
deleting a project folder unfiles the projects inside it, and both live under
`['projects', …]`, so one prefix covers them.

A **failed** mutation invalidates nothing. A refetch after a rejected write pulls
unchanged data, and its success reads as if the write had succeeded.

There is no global `onError`. Errors are reported per screen so the message names
what failed, and a few reads report nothing at all on purpose: an optional filter
that degrades to empty says more than a notification behind a form the user is still
filling in.

#### What a write declares untrue

The interesting decisions are the asymmetries, not the mechanism:

- **An assignment** invalidates `assignments`, `conflicts`, `planning`, `digest`,
  `resources` and `gantt` — but **not** `capacity`. An assignment *consumes* capacity;
  it does not change how much there is. The relationship runs one way.
- **Project master data** (name, folder, customer, reference) invalidates `projects`
  and stops. A **work package** invalidates the whole plan: its dates are what
  assignments hang off and what the critical path is computed from. A project's name
  is a label; a work package's end date is a commitment.
- **The skill catalogue** is the one piece of master data that reaches into the plan.
  A requirement points at a skill and a qualification points at a skill, so deleting an
  attribute changes no assignment yet can turn a covered requirement into an uncovered
  one. It therefore invalidates `digest`, where a customer write does not.
- **A baseline** is the one read that must *not* go stale on a plan change: it is a
  snapshot, and keeping it fixed is its purpose. The diff beside it is the exact
  opposite — it compares a frozen baseline against the live plan — so one screen holds
  one value that must never change and one that must.
- **A user account** invalidates `admin` alone. Capado plans people as resources, and
  those are a separate entity from the accounts that log in, because most of the
  workforce has no login at all.

#### Client state

Anything only the browser knows stays in React state and Context:

- `SettingsContext` holds both kinds, kept apart on purpose: **branding** is a query
  on `settings.tenant()`, shared with the settings page so a saved logo reaches the
  header without either side calling the other; **preferences** (colour scheme,
  locale) are `localStorage` and have no server copy to be stale against. The branding
  query WAITS for the session (`enabled`), because `GET /api/settings` requires
  authentication by design — firing it earlier guarantees a 401 and provokes a second,
  concurrent token refresh that replays a just-rotated refresh token. Branding cannot
  load without a session, so waiting costs nothing: the defaults render either way.
- `AuthContext`: token storage (memory), refresh logic, user profile, auto-refresh
  scheduling. A session is not a cacheable value — the token is consumed by the
  request interceptor on every call, and "stale" does not mean anything for it.
- Form values, open/closed panels, the row being edited: `useState` in the component
  that owns them. A form seeded from a server read keeps both: the query is the
  source, and an effect seeds the fields once per answer, because replacing them on
  every revalidation would overwrite what somebody is typing.

**Commands** — signing in, first-run setup, changing a password, downloading a report
— are mutations with no invalidation. There is no cached value they make untrue; they
use `useMutation` for the pending flag it owns, not for a cache.

**No Redux**, and no global store for server data either — the cache is the store.

What the layer deliberately does not cover, and why one grep was not enough to prove
it finished, is in [known limitations](../reference/known-limitations.md).

### API Client

`src/api/client.ts` is a shared Axios instance with:
- Request interceptor: attaches Bearer token from AuthContext.
- Response interceptor: on 401, attempts token refresh and retries the
  original request. Queues concurrent requests during refresh.

## Database Migrations

Alembic runs automatically on backend startup (`alembic upgrade head`).
Migrations create schema only — no seed data. Each revision has a
reversible `downgrade()`.

## Seed Data

Seeding is external to the application. Migrations create schema only, so a fresh
deployment starts empty and the setup page creates the first admin account.

After a bulk load that inserts assignments directly, run
`uv run python -m app.scripts.refresh_conflicts` to recalculate conflicts for all
resources: direct inserts bypass the write-path conflict detection, so without it
the plan looks conflict-free when it is not.

## Feature areas and where their rules live

This file is a map, not a copy. Each area below names where its rules are actually
written, because a second prose copy of a rule is a copy that goes stale — which is
exactly what happened to the in-app help, where a page describing the pre-week-profile
capacity model survived the rework that replaced it.

Decisions taken after ADR-009 are recorded in the module docstring of the service that
implements them rather than as separate ADRs. Those docstrings state the rule *and* what
it refuses, which is the part that stops somebody removing it later. See
`docs/decisions/README.md` for why the ADR numbering stops where it does.

| Area | Rules live in | The trap |
|------|---------------|----------|
| Working time | `services/working_time_service.py` | Demand is gated on *calendar* minutes, not available ones — so a holiday produces no conflict, a vacation day does |
| Calendar config | `services/calendar_service.py` | The default week profile cannot be deleted; a bound one cannot either |
| Dependencies | `services/dependencies.py` | Finish-to-start only, lag in working days. A violation warns; only a cycle is refused |
| Float / critical path | `services/critical_path.py` | Duration prefers the lead time over entered dates, and the backward pass measures against the customer commitment |
| Qualifications | `services/qualification.py` | Validity is checked against the *work*, not against today, and must cover the whole assignment |
| Action list | `services/digest.py` | Suppression is the hard part: 90-day horizon, severity from proximity, one finding per subject |
| Planning freeze | `services/planning_freeze.py`, `services/freeze_enforcement.py` | Both the before and after state count, so an assignment straddling the boundary cannot be edited at all |
| Baselines | `services/baseline_service.py` | The diff is the deliverable, not the snapshot |
| Team week | `services/team_week.py` | A day shows every assignment, and days with no calendar time are marked rather than blank |
| Customers | `services/customer_resolution.py` | Resolution walks *up* the folder tree, and invents nothing when nobody names a customer |
| Reports | `services/reports/` | Utilization calls the same computation the dashboard charts use, so the two cannot disagree |

The global catalogue — skills, their attributes and work package templates — is
admin-only, enforced through `EntityType.global_definition`. Renaming a skill breaks no
data (everything references it by UUID) but silently redefines every requirement pointing
at it, which is why the restriction exists.

## Key Design Decisions

1. **Dual assignment shapes** — One table, two field sets. Simpler than
   two tables with shared logic.
2. **Percentage-based authoring, minute-based arithmetic** —
   `allocation_percent` (1–100%) is what users enter; it means a share of a
   normative 480-minute day. Capacity is computed in integer minutes, because
   summing floats across long ranges drifts into phantom conflicts.
3. **Conflict detection on write** — Immediate feedback, no background jobs.
4. **Working time is required** — Capacity comes from `WorkWeekProfile`
   corrected by the site `holidays` table and reduced by absences.
   `WorkingTimeService` is the single source, shared by the capacity and
   conflict paths so they cannot contradict each other. An assignment places
   demand only on days the calendar grants time, which is what keeps a weekend
   from flagging every multi-week assignment.
5. **Soft-delete for resources** — Preserves historical assignments and
   conflict records.
6. **Scope-based RBAC** — Editors see everything but can only write within
   their configured groups or projects.
7. **ResourceGroups replace free-text** — Named containers with hierarchy
   instead of free-text department/location fields.
8. **Direct requirements on work packages** — Templates are convenience
   only; requirements live on the work package itself.
9. **Unified conflict handler** — Both personal and infrastructure
   conflict detection live in the same `ConflictService`. The
   `refresh_conflicts()` method uses a boundary sweep to find spans in which
   the active assignment set is constant, then walks each span day by day
   because capacity varies inside it (weekend, holiday, absence). Personal
   compares demanded against available minutes; infrastructure counts
   overlapping bookings (each 100% exclusive). A sweep-line helper
   (`_emit_infrastructure_period`) groups overlapping infrastructure intervals
   into conflict periods.
