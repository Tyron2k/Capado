# Continuous integration and automation

What runs when, and why the arrangement is shaped the way it is. This lived in the README until it
crowded out what the README is for; it is maintainer detail, not a first impression.

## Pull request checks

The full checks in `.github/workflows/ci.yml` run on **pull requests only**. The fast lint gate
runs first; Python type checks, frontend build and tests, backend tests on Python 3.12 and
3.14, dependency audits and a real PostgreSQL migration smoke test follow. Dockerfiles are checked
with hadolint and the production container configuration is scanned for misconfigurations.

The existing lint job also checks the generated HTTP contract with `npm run api:check`. Its offline
exporter uses locked backend dependencies without application startup; no extra CI job is needed.

The frontend job installs dependencies once and runs `npm run build` (TypeScript build mode and
Vite) before the coverage tests. CI skips the local `vite-build` pre-commit hook, avoiding a second
build in the lint gate and a separate TypeScript job. The hook remains available locally.

The final **CI passed** job runs even when an earlier job fails. It requires every CI dependency to
succeed, including both backend and CodeQL matrix entries; failure, cancellation or an unexpected
skip fails the gate. The `main` ruleset requires this single Actions check, with the branch up to
date, plus CodeQL merge protection. Add any new required CI job to this gate's `needs` list.

PRs do not build container images or run browser tests. Build and exercise the production targets
locally on the feature branch for larger application or deployment changes. Routine Renovate
minor/patch updates rely on the PR checks; image builds and scans follow after merge.

That is worth being precise about, because it decides where a mistake surfaces. A commit that reaches
`main` any other way than through a checked pull request is unverified, and nothing downstream re-checks
it.

Every job sets `timeout-minutes`. GitHub otherwise lets a hung job run for six hours, delaying useful
feedback and occupying runner capacity.

## Edge images are built when needed

`.github/workflows/build-images.yml` starts every night at 01:30 UTC. Its first job only consults the
Actions API. The expensive multi-platform build runs when `main` has moved since the last successful
publication or when that publication is at least seven days old. The latter refreshes moving base
images even when Capado itself did not change.

```bash
gh workflow run build-images.yml --ref main -f force=true
```

Backend and frontend candidates are pushed by digest, not by a public tag. Both must pass Trivy's
fixable HIGH/CRITICAL gate before the promotion job moves `:edge` and `edge-<sha>`. Each run also
stores a CycloneDX SBOM and build provenance. A failed build or scan therefore leaves the previous
good tags untouched.

Published releases use the same reusable build-and-scan workflow. Stable releases move the exact,
major/minor, major and `latest` tags; prereleases only receive exact and SHA tags. See
[publishing a release](../how-to/publishing-a-release.md).

## The project site

`.github/workflows/docs.yml` builds the MkDocs site and deploys it to GitHub Pages. It is **path
filtered** on `docs/**`, `.github/mkdocs.yml` and its own requirements file, so a push that only
touches application code does not rebuild a site that did not change.

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
run on `main`, with a read-only full dry run selected by default. It does not run on PR code.
Both the action and the Renovate version are pinned; the GitHub Actions manager also tracks
the `renovate-version` input, keeping the bot itself up to date.

`renovate.json` enables npm, Python/uv, GitHub Actions, Dockerfiles/Compose, pip requirements
and pre-commit. All minor/patch updates and existing hash refreshes share
`renovate/all-minor-patch` across ecosystems. This includes both Ruff pins and supported non-major
security fixes. Security updates retain Renovate's priority behavior and can ignore normal
PR limits. Major updates are separated and stay manual; TypeScript major updates retain the
existing exclusion until the lint tooling supports them. Docker tags retain their existing
precision and are not converted into digest pins. Weekly lockfile maintenance refreshes
indirect npm/Python dependencies in its own PR and can also auto-merge after checks pass.

Keep Dependabot **security updates** enabled alongside Renovate for targeted transitive fixes
in `uv.lock` and `package-lock.json`; see the
[documented Renovate limitation](known-limitations.md#renovate-transitive-security-fixes).
Dependabot handles those alert-driven fixes; Renovate handles routine version updates.

CI's Python 3.12 entry remains fixed to test the minimum supported version. Pre-commit revisions
use SHA pins with `# frozen: <tag>` comments, letting Renovate recognize their actual versions
and preserve the pins instead of treating hexadecimal hashes as version numbers.

Renovate queues GitHub's squash auto-merge. The existing strict branch rules still require
**CI passed**, an up-to-date branch and CodeQL. The app receives no administrator bypass.
Renovate updates branches that fall behind on its next run; with the daily schedule this may
take until the next night. Use a manual run if a merge should progress sooner. Ordinary
contributor PRs still require the maintainer's review.

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
