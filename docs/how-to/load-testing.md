# Local API load test

Run the Task CLI from the repository root:

```bash
task test:load:smoke
task test:load
```

Requirements: [Task v3](https://taskfile.dev/docs/installation/), a running Docker
engine with Docker Compose v2, Git and Bash. Windows users can run the task in WSL.
k6 and Python run in containers; no host installation,
Grafana account, existing Capado installation or `.env` is required. The first run
downloads images and builds the current checkout's production backend. Later runs
reuse the build cache. Uncommitted changes are included and recorded in the report.

## What runs

The task creates a unique Compose project containing PostgreSQL, the production
backend (four workers), a one-shot fixture loader and k6. It migrates the empty
database before starting backend workers. The database lives in tmpfs, containers
publish no host ports, and the container network is internal. No existing Compose
project, database or volume is used. Normal completion, failure and Ctrl+C all
remove the task's containers/network and its temporary backend image tag; build
cache is retained. Results survive cleanup. An uncatchable host/container-engine
failure can leave the named project behind; its name is in the task output. Remove
only that project and `tests/load/results/.running` before retrying.

The fixture reuses the existing overview benchmark: 83 projects, 586 work packages,
30 people and 586 bookings, with a working-week calendar and synthetic conflicts.
IDs and dates are stable (January–March 2026); the project-overview API still uses
the application's actual planning day. Compare runs on the same planning day.
The loader rejects other database targets and nonempty project/user tables. It
does not truncate data. Its only user is a test viewer. Login happens once before
the measurements, and each endpoint's populated JSON response is checked first.

Each measured iteration makes exactly one authenticated request, rotating evenly:

- Dashboard for the fixture's January–March date range.
- Project overview containing all 83 projects.
- Personnel Gantt for the fixture's resource group, containing all 83 projects.

This is an API read-load test. It does not measure frontend rendering, reverse
proxy/TLS overhead, writes, concurrent logins or infrastructure-only data.

## Profiles and acceptance

`smoke` warms up at 5 requests/s for 3 seconds, allows up to 10 seconds to drain,
then measures 5 requests/s for 9 seconds. It checks wiring, auth, payloads, cleanup
and acceptance behavior. Its small sample is insufficient for a reliable p99.

`full` warms up at 5 requests/s for 15 seconds and allows 10 seconds to drain.
Measured traffic ramps from 5 to 20 requests/s over 20 seconds, holds 20 for 30
seconds, ramps to 50 over 20 seconds and holds 50 for 30 seconds. Rates are total
API requests/s, split across the three endpoints, not users/s or per-endpoint RPS.
There are at most 50 measurement workers. k6 reports dropped iterations when it
cannot start the scheduled traffic instead of building an unlimited queue.

The command exits unsuccessfully for any dropped measured iteration, any invalid
measured response, an HTTP error rate of at least 1%, too few requests (10 per
endpoint in smoke; 1,000 in full), or an exceeded per-endpoint latency budget.
Defaults are p95 below 1,000 ms and p99 below 2,000 ms. These are initial local
development budgets, not production SLOs. Establish a baseline before tightening:

```bash
LOAD_P95_MS=500 LOAD_P99_MS=1000 task test:load
```

Configuration errors, startup/fixture errors and k6 failures make the task fail.
Without the Task CLI, `bash tests/load/run.sh [full|smoke]` runs the same lifecycle.
Warmup/login/preflight requests are excluded from measured thresholds. No load
test is scheduled in GitHub Actions or added to regular PR checks.

## Reports and comparisons

`tests/load/results/` is ignored by Git and contains the latest run:

- `k6.log`: console report, achieved request counts/rates, dropped iterations,
  response checks and latency percentiles/thresholds per measured endpoint.
- `summary.json`: k6's native machine-readable summary, including thresholds.
- `environment.txt`: revision, working-tree changes, profile/budgets and Docker
  CPU/memory/architecture information.
- `containers.log`: backend, migration and database diagnostics.

The console's aggregate HTTP rate includes setup/warmup and drain periods. Use the
measured metric tags and scheduled stages to interpret the measurement; an offered
rate alone is never an acceptance criterion. Save the results elsewhere before the
next run to compare revisions. Keep Docker resources, hardware, fixture and budgets
constant, repeat suspicious results, and inspect CPU/memory pressure. The load
generator and app share hardware, so a failed offered-load target may reflect the
generator's resource limit too. This is not a production capacity guarantee.

For a slow overview, use the existing PostgreSQL/CPU benchmark described in
[Architecture](../explanation/architecture.md) to investigate the cause.
