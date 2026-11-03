# Planning validation baseline

The fictional [combined reference cases](combined-planning.md) now drive both
service regressions and repeatable browser tasks. They establish correctness and
an executable workflow baseline. They do **not** establish observed human
usability or customer demand.

## Reproducible data and correctness

`backend/tests/planning_reference.py` supplies the existing shared dataset: a
three-day package, two qualified people and one exclusively booked machine with
an overnight operating window. Domain tests, migrated PostgreSQL tests and the
browser seed reuse it. Browser variants remove one personnel booking, add an
overlapping out-of-window machine booking, or lower a required qualification level.

The browser seed is test-only. It resets only the guarded, disposable
`capado_e2e_*` database owned by the browser harness. It adds no application reset
endpoint and uses no employee, customer or production data.

Run the established test harness with Docker, uv and the frontend dependencies
installed:

```sh
cd frontend
npm run test:e2e -- planning-readiness.spec.ts
```

The normal harness owns its database/API lifetime and resets the reference data
for every task. The local comparison below used an isolated Docker Compose stack
for PostgreSQL, FastAPI and Vite; no existing application database was modified.

Correctness checks are in `test_planning_readiness.py`,
`test_planning_readiness_postgres.py`, `test_combined_planning_postgres.py` and the
existing coverage/qualification regressions. They retain known blockers alongside
unknown evidence, compare current inputs with stale saved conflicts, and assert
that an assessment writes no data. A query-count regression verifies that adding
20 assigned people does not introduce per-resource database round trips.

## Two repeatable tasks

Start signed in as the fictional test administrator on Planning Overview, with
fresh scenario data. Exclude sign-in and fixture reset from task measurements.

1. **Complete staffing:** identify the one-person gap, preview the qualified
   unassigned person, confirm the assignment and verify covered personnel demand.
   The overall result must retain the machine-shift precision limit.
2. **Repair a machine booking:** identify the crane's overlap and operating-window
   violation, open its bookings, move the extra Monday 21:00–Tuesday 01:00 booking
   to Tuesday 02:00–06:00, and verify that both blockers clear.

For every attempt record completion, elapsed time, explicit interactions,
wrong-resource/period choices, and misunderstandings about the result. Count each
click, text fill and explicit key press as one interaction; do not count passive
assertions or waits. Keep failed attempts and their causes separate from completed
attempts. Automation-selector calibration failures are not human planning errors.

## Observed automated comparison: 3 November 2026

One completed Chromium run per task and presentation, on the same host and Compose
stack, using a 1440 × 1000 viewport. The before frontend is from main at `15b2beda`;
both presentations use the same backend working tree and shared dataset. This is
an interface-path comparison, not a historical full-stack benchmark. Timings
include browser/network waits and assertions; diagnostic screenshot capture is
excluded. Neither human reading nor decision time is represented.

| Task | Before interactions | After interactions | Before elapsed | After elapsed | Recorded planning errors |
|---|---:|---:|---:|---:|---|
| Complete staffing | 3 | 5 | 925 ms | 971 ms | None in these completed automated runs |
| Repair machine booking | 13 | 15 | 2,181 ms | 2,039 ms | None in these completed automated runs |

The package selector adds two interactions from the unfiltered overview. This
change does **not** demonstrate a faster workflow. It provides an explicit
package-scoped verdict, separate dimensions, current conflict causes and stated
limits. Whether that improves understanding remains to be tested with people.
Subsequent CI attachments contain fresh automated measurements; compare timings
only under equivalent conditions rather than treating these samples as targets.

The browser tests also cover an insufficient qualification, desktop light/dark
presentation, and 390 × 844 layout without page-wide horizontal overflow.

## Planner observation protocol — not yet performed

For issue #135, invite two independent planners where possible. Obtain permission
for the session; collect no personnel names, customer data, production plans or
credentials. A person may stop at any time. Use only the fictional scenarios above.

Ask each person to attempt the two tasks without coaching. Afterwards ask:

- What does the personnel result establish?
- Can this view confirm attendance during the machine's night shift?
- What would you do when a check fails or is too old?
- Which blocker mattered most, and was the next action clear?

Record anonymized participant identifiers, environment/version, task completion,
time, interaction/error count, quoted or paraphrased misunderstanding, and observed
strengths. Separate observations from proposed remedies. Rank the three most
consequential problems by evidence and report the participant/sample limits.

**Current status:** no external planner sessions or human before/after measurements
have been performed. Internal automated execution must not be relabelled as that
validation. Issues #135 and the evidence-led conflict workflow analysis #144 remain
open; the existing reference cases and procedure make those sessions repeatable.
