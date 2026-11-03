# Combined planning: guarantees and reference cases

Capado records qualified personnel commitments by date and percentage, and
exclusive infrastructure bookings by timestamp. The existing APIs return separate
requirement, qualification, capacity and conflict results. This page defines how
to interpret them together and gives reproducible synthetic reference cases.

The detailed rules remain with the [capacity model](capacity-model.md),
[conflict detection](conflict-detection.md), [requirement data model](../reference/data-model.md)
and their existing domain services.

## What each result establishes

| Result | What it establishes | Limit |
|---|---|---|
| Personnel requirement coverage | Minimum daily headcount or effort-FTE from qualifying bookings on workdays of the standard profile | Individual calendars, part-time capacity and absences are additional checks |
| Infrastructure requirement coverage | Qualified booked resources matching the requested capability | Does not establish continuous or simultaneous equipment coverage across the package |
| Qualification mismatch | An assignment fails every applicable package requirement | Satisfying one requirement does not fill the other requirements |
| Personal capacity | Calendar minutes, available minutes after absences, and normative demand | A site holiday can suppress demand and a stored over-allocation conflict while reducing available supply to zero |
| Stored infrastructure conflict | A timestamp overlap or a booking outside operating windows, with involved assignment IDs | Stored conflict dates summarize the problem; the assignment timestamps carry its minute precision |

Personnel dates are inclusive. Infrastructure occupancy is half-open: a booking
ending at 02:00 permits another starting at 02:00. Overnight windows belong to
the weekday on which they start. A machine with no windows is deliberately
available 24/7; this default is established behavior, not missing configuration.

Headcount counts distinct people reaching the allocation threshold **on each
required day**. Effort-FTE sums allocations active on that day. Distinct people
on separate days cannot fill a simultaneous crew; a person appearing in several
bookings is still one body. Divisible effort may sum across bookings, while
resource over-allocation remains an independent conflict.

Qualification validity and minimum level must cover the full assignment span.
An unassessed level cannot meet a required minimum. Open validity bounds do not
restrict the qualification. Suggestions must qualify for the complete package
period; they do not promise freedom from every capacity or equipment constraint.

## Vocabulary for presenting combined results

These terms describe evidence and its scope; they are not a new API status enum.
The existing Planning Overview can use them when combining the current results.

| Term | Meaning | Presentation requirement |
|---|---|---|
| **Covered** | The particular requirement is met under its recorded mode, dates and qualification rules | State which requirement and precision were checked; do not turn this into an unconditional execution guarantee |
| **Missing requirements** | Qualified booking coverage is below demand on a required day, or a requested infrastructure capability is not covered | Identify the deficient requirement and quantity; distinguish missing calendar configuration from a proven staffing deficit |
| **Conflicting** | Applicable capacity, occupancy or operating-window checks report a violation | Show the cause, resource and involved bookings; distinguish current checks from last-known stored results |
| **Not fully assessable** | A necessary result is absent, failed, stale, or cannot be derived at the requested precision | State the missing evidence, including minute-level personnel presence when only dates and percentages exist |

Known deficits and conflicts must remain visible even if other checks are
incomplete. Coverage and a capacity conflict can both be true: the resources are
booked and qualified, but those commitments do not fit their availability.

A completely green set of available checks establishes their individual
contracts. It does not prove that two date-booked people are present during a
specific machine shift. Personnel bookings have no start/end clock times from
which that claim could be derived. Missing minute-level evidence must not be
silently presented as confirmed simultaneous presence.

## Freshness and read-after-write behavior

Requirement coverage and qualification mismatch read current inputs. Conflict
rows are derived data reconciled after a committed write or by a scheduled full
check. Those steps have separate transaction boundaries.

Between input commit and successful reconciliation, live booking results can
differ from stored conflicts. If derived persistence fails, the saved input stays
saved and the previous complete conflict result survives rollback. The failure
is logged and a subsequent successful check repairs the stored result.

`/api/conflicts/check-status` reports the latest scheduled-run status, the last
successful full check, scheduler activation and staleness. Its nominal interval
is 15 minutes, with a further interval allowed for scheduling jitter. A recent
full-run timestamp does not certify every later edit or post-commit refresh.
Stored rows without sufficiently current evidence are last-known results, not
proof that the latest inputs are conflict-free. A never-run or failed necessary
check cannot be presented as a successful check.

## Shared synthetic dataset

All cases use fictional data persisted in a newly migrated disposable PostgreSQL
database. The database fixture uses a different session timezone from the local
planning clock, exercising the stored-UTC/local-planning boundary.

- Package: Monday 5 January 2099 through Wednesday 7 January 2099.
- Standard profile: 480 minutes Monday–Friday; weekends free.
- People A and B: assessed handling qualification level 3, valid throughout the
  package; booked at 100% on all three days.
- Personnel demand: two people, headcount mode, threshold 100%, minimum level 3.
- Machine: one qualified crane, minimum capability level 2; booked Monday 22:00
  through Tuesday 02:00 in the local planning zone.
- Operating window: Monday 22:00 through Tuesday 06:00, or no windows for the
  explicit unrestricted-default variant.

Each case starts from this dataset and applies only its listed changes. All
percentages refer to a normative 480-minute day.

| Case | Input changes | Expected results |
|---|---|---|
| C1: Available checks pass | None; also repeat with no machine windows | Both requirements covered, no qualification mismatches, no stored conflicts; each person's Monday supply/demand is 100%. Night-shift personnel presence remains unproven |
| C2: Qualifications fail | A has level 2; crane qualification expired before Monday | Personnel coverage 1/gap 1; infrastructure coverage 0/gap 1; those two bookings mismatch. No capacity conflict is invented for a qualification problem |
| C3: Individual supply does not fit | A has 240 Monday minutes; B is absent Tuesday | Requirements still have qualified commitments. Stored personal conflicts show A at 100% demand/50% supply on Monday and B at 100%/0% on Tuesday |
| C4: Site is closed | Site calendar grants zero minutes Wednesday | Personnel supply and calendar-gated demand are zero Wednesday; qualified commitment coverage remains met and no over-allocation is stored. A combined presentation must expose the supply loss and the limit of these separate checks |
| C5: Headcount differs from FTE | A and B each booked at 50% | A two-person headcount requirement with a 100% threshold has coverage 0/gap 2. Changing demand to one effort-FTE gives coverage 1 and no gap. Crane checks remain unchanged |
| C6: Machine conflict and repair | Add Monday 21:00–Tuesday 01:00 on the same crane | Overlap spans Monday 22:00–Tuesday 01:00; the extra booking is outside the window on Monday. Coverage/qualifications still pass. Moving it to Tuesday 02:00–06:00 removes both conflicts after reconciliation |
| C7: Derived refresh fails | Commit the C6 repair, then fail saving replacement conflicts | The new booking times remain committed; prior conflicts remain complete; failure is observable in logs. A later successful refresh clears old rows and links |
| C8: Disjoint and repeated people | A only Monday, B Tuesday/Wednesday; add a 50% A booking over all three days | Before the extra booking daily coverage is 1. Afterwards headcount remains 1; effort-FTE becomes 1.5. A is over-allocated on Monday. Repeated paperwork does not clone A, and crane checks remain unchanged |

C4 is an explicit limit of the current decomposition. Requirement coverage checks
qualified commitments against the standard profile, not site-aware production
output. The absence of a stored over-allocation on a holiday is not a positive
claim about delivered work or end-to-end feasibility. This reference work records
the distinction without changing the agreed business rules or introducing another
calculation engine.

## Executable evidence

`backend/tests/test_combined_planning_postgres.py` implements these cases through
`get_unmet_requirements`, `detect_mismatches`, `CapacityService`,
`ConflictService.calculate_periods`, `refresh_resources` and
`refresh_after_commit`. It compares preview and persisted causes, dates, amounts
and assignment links, and verifies stable identities for unchanged results.

Run with the existing backend test setup and a disposable PostgreSQL test server
in `TEST_POSTGRES_URL`, whose test account may create databases:

```sh
cd backend
uv run pytest -n 2 tests/test_combined_planning_postgres.py
```

The imported migration fixture creates and drops its own uniquely named
databases. The cases require the qualification and temporal coverage corrections
from PRs #157 and #158. Related regressions remain in
`test_requirement_coverage_audit.py`, `test_temporal_requirement_coverage.py` and
`test_requirement_coverage_postgres.py`; existing infrastructure window tests
separately exercise daylight-saving boundaries.


The [work-package assessment](../how-to/assessing-work-packages.md) presents these
scoped checks in Planning Overview. The [validation baseline](planning-validation.md)
records repeatable browser tasks and separates automated evidence from planner
observations.
