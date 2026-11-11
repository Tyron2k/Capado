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

## Release-candidate internal check — 11 November 2026

The existing browser tasks ran successfully in the
[full v0.2.0 candidate CI](https://github.com/Tyron2k/Capado/actions/runs/42998887777)
on source `aaeef47bb95bea85ade1f533d7c819119631957c`. The measurements below reuse its
`browser-test-report` attachments; no extra benchmark pipeline was introduced.
These are single automated runs on a GitHub runner, with the default 1280 × 720
desktop viewport and the same synthetic scenarios and counting rules above.

| Task | Interactions | Automated elapsed | Result |
|---|---:|---:|---|
| Complete staffing | 5 | 1,735 ms | Personnel covered; machine-shift precision limit retained |
| Repair machine booking manually | 15 | 2,665 ms | Overlap and operating-window violations cleared |

The remaining qualification, overnight-window and typed equipment-replacement
browser scenarios also pass. This is correctness and path evidence, not reading
time, human decision time or an independent usability result. Runner and viewport
conditions differ from the 3 November local sample, so the elapsed values do not
establish an improvement or regression between versions.

**Internal hypothesis for #144:** the manual machine correction is the longer of
these two paths. Compare it with the already available ranked proposal and its
remaining-conflict preview before adding another reassignment interaction. This
sample does not establish that resource reassignment is the user's main bottleneck
or that new bulk-edit functionality would help. Keep #145/#146 evidence-led.

## Planner observation protocol — not yet performed

The [first combined plan walkthrough](../how-to/first-combined-plan.md) now provides
a downloadable example ZIP from the same reference fixture. Its committed import
regression checks the initial gap/conflicts and both documented repairs. An internal
production-target Docker Compose check also exercised fresh setup, authenticated
ZIP import, the two repairs, export and rejection of reimport into a populated target.
That check used HTTP/API requests, not a new browser test or an independent operator.
It establishes reproducibility of the data flow, not a measured usability improvement.

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

## Record a session

Use one record per attempt and keep failed attempts. The same record supports the
[installation walkthrough](../how-to/first-combined-plan.md) and planning tasks.
Use fictional data and an anonymous participant identifier; include no credentials,
personnel records or customer plans.

| Field | Record |
|---|---|
| Date and evidence type | Internal automation, internal human trial, or independent participant |
| Application | Version shown in the UI; source SHA or paired image digests when available |
| Environment | Browser, viewport, display time zone, role and fresh/existing installation |
| Attempt | Anonymous identifier; task and starting scenario; any coaching or deviations |
| Startup/import | Setup completed? Original complete ZIP used? Import counts and full area/row/field error |
| Planning result | Staffing gap, machine conflicts, qualification result and displayed precision limit |
| Completion | Completed, failed, or stopped; elapsed time; interaction and error counts |
| Understanding | What the participant believed the result established; uncertainty and confusing steps |
| Finding | Confirmed observation, its impact, reproduction and a separately labelled improvement hypothesis |
| Follow-up | Smallest correction or missing evidence; issue/PR link; repeat result |

An internally completed checklist does not establish independent onboarding or a
human usability benefit. If only internal checks are available, keep that limit
explicit and leave the independent acceptance outstanding. For a comparison, use
the same task, dataset, role and measurement rules; label comparisons of different
paths in one version separately from before/after changes between versions.
