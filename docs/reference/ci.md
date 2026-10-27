# Continuous integration and automation

What runs when, and why the arrangement is shaped the way it is. This lived in the README until it
crowded out what the README is for; it is maintainer detail, not a first impression.

## Pull request checks

The full checks in `.github/workflows/ci.yml` run on **pull requests and manual validation**. The fast lint gate
runs first; Python type checks, frontend build and tests, backend tests on Python 3.12 and
3.15, dependency audits and a real PostgreSQL migration smoke test follow. Dockerfiles are checked
with hadolint and the production container configuration is scanned for misconfigurations.

PostgreSQL test services use the official images mirrored at
`ghcr.io/tyron2k/capado/ci-postgres:18` and `:18-alpine`, authenticated with the job's
read-only package token. Browser tests use the same mirror in CI; local browser runs
default to Docker's official `postgres:18` and accept `CAPADO_E2E_POSTGRES_IMAGE` as an override.
Production Compose images and developer data volumes are unaffected.

The existing lint job also checks the generated HTTP contract with `npm run api:check`. Its offline
exporter uses locked backend dependencies without application startup; no extra CI job is needed.
It runs the offline release/edge regression suite in `.github/scripts/tests`, actionlint
through prek, and zizmor over workflows **and composite actions**. The two setup composites share
uv and Node/npm configuration and lockfile caches; each caller still chooses its environment
and checks. Python setup remains explicit so Renovate can discover interpreter versions and keep
the Python 3.12 minimum exclusion working. The audit job reads the npm lockfile without installing frontend dependencies.

The frontend job installs dependencies once and runs `npm run build` (TypeScript build mode and
Vite) before the coverage tests. CI skips the local `vite-build` pre-commit hook, avoiding a second
build in the lint gate and a separate TypeScript job. The hook remains available locally.

The final **CI passed** job runs even when an earlier job fails. It requires every CI dependency to
succeed, including both backend and CodeQL matrix entries; failure, cancellation or an unexpected
skip fails the gate. The `main` ruleset requires this single Actions check, with the branch up to
date, plus CodeQL merge protection. Add any new required CI job to this gate's `needs` list.

The frontend job also runs the browser regression suite against real PostgreSQL and FastAPI,
using synthetic data. PRs do not build production container images. Build and exercise the production targets
locally on the feature branch for larger application or deployment changes. Routine Renovate
minor/patch updates rely on the PR checks; image builds and scans follow after merge.

That is worth being precise about, because it decides where a mistake surfaces. A commit that reaches
`main` any other way than through a checked pull request is unverified until a full manual run passes.
The active `main` ruleset requires a PR, an up-to-date branch, **CI passed** from GitHub Actions,
linear history and CodeQL protection; ordinary direct pushes, force pushes and deletion are blocked.
Repository administrators retain an **always** bypass. Use the required PR route even with that role.

Pushes and the weekly schedule run **CodeQL only**. A green workflow result on `main` therefore
does not prove that the full test suite ran on that commit. PR checks validate the proposed merged
tree; squash/rebase publication produces a different commit SHA.
CI concurrency includes the event type so a CodeQL-only push cannot cancel a manual full candidate
validation on the same ref. Python coverage stays at 57%; frontend lines/functions/branches stay at
62%/53%/55%. All eight dependencies remain required by **CI passed**.

## Exact release-candidate validation

Run the existing CI manually on the intended branch or tag before publishing a release:

```bash
gh workflow run ci.yml --ref main
gh run list --workflow ci.yml --event workflow_dispatch --branch main --limit 1
gh run watch <run-id> --exit-status
gh run view <run-id> --json headSha,conclusion
```

Use that successful run's **headSha**, not a later `main`, as the release target. The manual event
runs all existing jobs and the same strict **CI passed** gate, including Python 3.12/3.15,
PostgreSQL migrations, browser tests, locked dependency audits and CodeQL. The PR-only dependency
diff review has no comparison on a manual run; the Python and npm vulnerability audits still run.
There is no new test pipeline and no full test rerun on every `main` push.

`release.yml` refuses image publication unless that exact source SHA has a successful manual
CI run and a successful **CI passed** job. The source must be in `main` history. The workflow
resolves the release tag once and passes its immutable SHA to the image builder, so moving a tag
cannot change the tested source between validation and build. It reuses the successful run,
rather than paying for the same suite a second time during publication. Run history must remain
available; a deleted validation requires another manual run. A failed gate can be rerun after
validation succeeds, without republishing the GitHub release.

Every job sets `timeout-minutes`. GitHub otherwise lets a hung job run for six hours, delaying useful
feedback and occupying runner capacity.

## Edge images are built when needed

The same workflow refreshes the PostgreSQL test mirror weekly, independently of edge
publication. Skopeo copies the official Docker Hub images with all platforms and
preserves their digests; the workflow checks AMD64/ARM64 availability and verifies the
destination manifest digest. It does not rebuild or execute upstream images. GHCR writes
are limited to that job and its temporary login is removed afterwards.

Before the first CI use, bootstrap the mirror from the trusted implementation branch:

```bash
gh workflow run build-images.yml --ref <trusted-branch> -f test-images-only=true
```

This manual mode copies only test images and does not publish Capado images. Scheduled
copies run from the default branch; a failed copy is reported as a workflow failure.
On first publication, make the `ci-postgres` package public in GitHub's package settings
so forks can read it too. Repository workflows still authenticate with `GITHUB_TOKEN`;
no additional registry secret is required. Verify the bootstrap before changing CI consumers.

`.github/workflows/build-images.yml` starts every night at 01:30 UTC. Its first job reads the
Actions API with GitHub CLI pagination and evaluates publication receipts with `jq` directly in
the workflow. The expensive multi-platform build runs when `main` has moved since the last successful
publication or when that publication is at least seven days old. The latter refreshes moving base
images even when Capado itself did not change.
Both scheduled and manual edge runs require `main`. The decision joins paginated successful runs
with paginated `publication-edge` artifacts, instead of querying jobs or matching their display
names. Only a completed successful publication with a non-expired receipt counts; skipped builds,
failed promotions and unrelated artifacts do not. Receipt creation time handles reruns correctly.
API failures stop the decision rather than pretending that publication succeeded. When no receipt
is retained (including the first run after this migration), a fresh build is required.

```bash
gh workflow run build-images.yml --ref main -f force=true
```

Backend and frontend candidates are pushed by digest, not by a public tag. Both runtime
architectures of both images must pass Trivy's fixable HIGH/CRITICAL gate before promotion.
Each run stores CycloneDX SBOMs and the images retain BuildKit SBOM/provenance attestations.
A failed build or scan leaves public tags untouched. `edge-<sha>` retains its **first** approved
digest; security refreshes of the same source update only `edge`. Production OS package layers
are rebuilt without cache, while builder/dependency caches are shared by component under the publication lock. This keeps
main edge caches available to release-tag builds through GitHub's default-branch cache access.

Published releases use the same reusable build-and-scan workflow. Stable releases move the exact,
major/minor, major and `latest` tags; prereleases only receive exact and SHA tags. All edge and
release publications share a repository-wide lock with cancellation disabled. Release aliases
advance only to a greater SemVer; queued edge runs recheck the current main SHA before writing.
The shared publisher uses `queue: max`: up to 100 publications can wait while one runs.
GitHub cancels additional runs when that queue is full. Rerun a canceled publication when necessary;
waiting order does not guarantee dispatch order, and version checks still prevent a downgrade. See
[publishing a release](../how-to/publishing-a-release.md).

To exercise publication policy locally without registry access:

```bash
python3 -m unittest discover -s .github/scripts/tests -v
```

## The project site

`.github/workflows/docs.yml` builds the MkDocs site and deploys it to GitHub Pages. It is **path
filtered** on `docs/**`, `.github/mkdocs.yml` and its own requirements file, so a push that only
touches application code does not rebuild a site that did not change.
PR builds and manual runs on other branches cannot upload a deployment artifact or deploy.
Only `refs/heads/main` can deploy, and only the deployment job receives Pages/OIDC write access.
PR concurrency is separate so a preview cannot displace a production deployment.

The build runs `mkdocs build -f .github/mkdocs.yml --strict`, which turns a broken internal link into
a failed build. The config lives under `.github/` rather than the repo root, so the `-f` flag is
required — both locally and in CI — and `mkdocs.yml`'s `docs_dir`/`site_dir` point one level up. One
gap to know about: MkDocs reports a page that is **excluded** from the site — via `exclude_docs` — as
`INFO`, not as a warning. `--strict` therefore does **not** catch a pattern that accidentally excludes
a page other pages link to. Read the build output when changing `exclude_docs`.

## Code scanning

CI calls `codeql.yml` to analyze Python and JavaScript/TypeScript on every pull request. On relevant
pushes to `main` and weekly, CI runs **only CodeQL**; lint, builds, tests, audits and the final PR
gate are skipped. This keeps the main baseline and PR scans under the same analysis identity, which
GitHub uses when comparing findings. It uses CodeQL's `security-extended` queries and waits for GitHub
to process the results before completing. GitHub auto-merge waits for the final CI gate, including
both analyses, rather than racing a separate scan workflow.

The `main` ruleset requires CodeQL results and blocks code-scanning errors and HIGH/CRITICAL security
alerts. PRs have no path filter because a required scan must report results even for configuration-only
changes. The repository is public, so the results appear in GitHub code scanning without a separate
paid Advanced Security license.

## Renovate updates dependencies

`.github/workflows/renovate.yml` runs the open-source Renovate container on GitHub Actions at
01:23 UTC every day (02:23 in Berlin in winter, 03:23 in summer). It also supports a manual
run on `main`, with a read-only full dry run selected by default. Pushes to `main` first
check for an outdated, same-repository Renovate PR with auto-merge enabled. Only if one
exists does the workflow mint the app token and run Renovate again. The check uses Git
ancestry rather than GitHub's eventually computed mergeability status. PR code is never
checked out or executed by this writing workflow.
Both the action and the Renovate version are pinned; the GitHub Actions manager also tracks
the `renovate-version` input, keeping the bot itself up to date.
Release Drafter's writing job also requires `main`; PR note previews use a read-only token and
never execute PR code. Renovate's app token remains restricted to this repository, and its
minor/patch auto-merge rules still depend on the complete CI and CodeQL gates.

`renovate.json` enables npm, Python/uv, GitHub Actions, Dockerfiles/Compose, pip requirements
and pre-commit. All minor/patch updates and existing hash refreshes share
`renovate/all-minor-patch` across ecosystems. This includes both Ruff pins and supported non-major
security fixes. Security updates retain Renovate's priority behavior and can ignore normal
PR limits. Major updates are separated and stay manual; TypeScript major updates retain the
existing exclusion until the lint tooling supports them. Docker tags retain their existing
precision and are not converted into digest pins. The routine group also refreshes both
lockfiles completely, within the dependency constraints, before its commit. Renovate's
native `postUpgradeTasks` runs `uv lock --project backend --upgrade` and
`npm --prefix frontend update --package-lock-only --ignore-scripts` once per branch.
The self-hosted command allowlist accepts only these exact commands; file filters include
only `backend/uv.lock` and `frontend/package-lock.json`. No npm lifecycle scripts, custom
repository helper, or separate global JSON configuration are needed.

Renovate cannot natively group its `lockFileMaintenance` update type with normal updates.
Instead, priority and a one-new-PR-per-hour budget choose the routine group first and the
native lock-only fallback second. Both remain eligible daily, without a narrow time window.
An existing routine PR disables the parallel fallback for that run. An existing fallback
is finished before another automatic branch is created. A day without direct updates can
therefore still get a lock-only PR. Existing branches can be rebased regardless of the
creation limit. No extra PR or CI run is created for an unchanged lockfile.

Global concurrent creation is not capped, so open manual reviews do not block routine work.
Manual major and Python-runtime updates use a concurrent cap of two (counting other
regular Renovate PRs), with no hourly creation limit. Automatic updates are exempt from
that concurrent cap. Manual updates are sorted after the automatic group and fallback.
GitHub vulnerability alerts retain their separate budget and priority. These exceptions
can create additional review/security PRs; this policy does not promise one PR of any kind.

`statusCheckWhen.artifactError: always` makes Renovate publish `renovate/artifacts` on
updated heads. The existing **CI passed** gate requires that status to be successful for
Renovate-authored PRs, in addition to every existing CI job. A failed, pending, absent or
unreadable artifact status blocks merging. This prevents platform-native auto-merge from
accepting a partial lockfile refresh even if ordinary frozen installs happen to succeed.
Other contributors do not need a Renovate status. Use Renovate's rebase checkbox and a
manual non-dry run for a requested retry; editing/rebasing bot branches independently can
leave them without fresh artifact proof. CI keeps installing with `--frozen`, and audits
remain blocking. A fix outside allowed dependency constraints needs constraint review.

Python interpreter minor/major upgrades are an exception: Docker images and Actions Python
versions share a separate `Python runtime` PR with auto-merge disabled. Keep the minimum
test version at 3.12 and update the other matrix entry to match the production Dockerfile.
Before merging a runtime upgrade, build the backend and frontend production targets locally
for both `linux/amd64` and `linux/arm64`, check native dependency imports, and exercise an
isolated production Compose stack with disposable data. Also build the backend `dev` target
and install its locked development dependencies, since a new interpreter can require native
compilation there too. Record the results in the PR. Routine dependency updates retain the
shared group and existing CI budget.

Keep Dependabot **security updates** enabled alongside Renovate for targeted transitive fixes
in `uv.lock` and `package-lock.json`; see the
[documented Renovate limitation](known-limitations.md#renovate-transitive-security-fixes).
Dependabot handles those alert-driven fixes; Renovate handles routine version updates.

CI's Python 3.12 entry remains fixed to test the minimum supported version. Pre-commit revisions
use SHA pins with `# frozen: <tag>` comments, letting Renovate recognize their actual versions
and preserve the pins instead of treating hexadecimal hashes as version numbers.

Renovate queues GitHub's squash auto-merge. The existing strict branch rules still require
**CI passed**, an up-to-date branch and CodeQL. The app receives no administrator bypass.
A `main` push resumes Renovate only for stale auto-merge PRs, allowing a merge/rebase/CI
sequence without waiting for the next nightly scan or running the full bot every hour.
The existing concurrency group serializes these runs. Forks, other authors, drafts and
manual-review PRs do not trigger a writing run. API errors fail the selector visibly.
Use the manual workflow for recovery. Ordinary contributor PRs remain maintainer-reviewed.

### One-time bot setup

The bot uses a **private GitHub App owned by the repository owner**, reusable across their repositories.
There is no Mend-hosted app or Mend repository grant. Create the app under
[GitHub developer settings](https://github.com/settings/apps/new), for example named `Tyron2k Renovate`, with the owner's profile URL
as its homepage, no callback URL, and webhooks disabled. Only this account may install the app.
Grant the [permissions documented by Renovate](https://docs.renovatebot.com/modules/platform/github/#running-as-a-github-app):

| Repository permission | Access |
| --- | --- |
| Checks, commit statuses, contents, issues, pull requests | Read and write |
| Workflows | Write |
| Administration, Dependabot alerts, metadata | Read |

No organization permission is needed for this personal-account repository. If transferred to
an organization and using team features, also check Renovate's documented Members permission.
Keep the dependency graph, Dependabot **alerts** and Dependabot **security updates** enabled.
The app needs alert access to prioritize supported vulnerability fixes; removing the Dependabot
version update configuration does not disable alerts or security updates.

Install the app on the owner's account with **All repositories** to make it available to
current and future repositories. This grants access; it does not start Renovate in those
repositories. Capado's workflow still requests a token restricted to Capado and processes
only Capado. For a repository in another account or organization, the app also needs an
installation there; a private app is restricted to the account that owns it.

Generate its private key and set these
[repository Actions secrets](https://github.com/Tyron2k/Capado/settings/secrets/actions):

- `RENOVATE_APP_CLIENT_ID`: the app's Client ID from its settings page.
- `RENOVATE_APP_PRIVATE_KEY`: the complete generated PEM private key.

The workflow checks these names before starting, creates an installation token limited to the
current repository, and revokes it when the job finishes. Use the app token rather than
`GITHUB_TOKEN`: app-created PRs start CI automatically and app merges trigger the normal
Release Drafter push workflow. The workflow's `RENOVATE_*` environment variables require
repository config, disable discovery/onboarding and enable GitHub-signed API commits.
The repository's update rules remain in `renovate.json`.

For a future run across multiple repositories, prefer a central bot workflow with the app
private key stored only in that runner repository. A copy of the app key can mint tokens for
any repository in the installation, even when a particular job requests a narrower token.
The central runner must explicitly target the desired repositories and their account's
installation; this Capado migration does not enable a multi-repository run.

In repository Actions settings, allow `renovatebot/github-action@*` if third-party actions
are restricted to a selected list. Keep the requirement to pin actions to a full commit SHA
enabled; the workflow already pins this action.

After merging the migration and configuring the app, first preview the planned updates:

```bash
gh workflow run renovate.yml --ref main -f dry_run=true
```

Confirm that extraction finds both lockfile ecosystems, both Ruff pins and the expected update
group. Keep **Dependabot security updates** enabled for the transitive fixes described above.
Then start the first writing run:

```bash
gh workflow run renovate.yml --ref main -f dry_run=false
```

Close any remaining Dependabot PR only after Renovate has produced an equivalent replacement
or the update is already on `main`. The nightly schedule uses writing mode automatically.

## Inactive discussions

The weekly stale workflow only **labels** inactive issues and PRs. It never closes them
automatically. Security, pinned, bug, enhancement and dependency labels, assigned discussions,
milestones and draft PRs are exempt. A maintainer decides when an important open item is resolved.
Manual stale runs require `main`; write permissions are limited to the stale job.
