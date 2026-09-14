# Continuous integration and automation

What runs when, and why the arrangement is shaped the way it is. This lived in the README until it
crowded out what the README is for; it is maintainer detail, not a first impression.

## Pull request checks

`.github/workflows/ci.yml` runs on **pull requests only** — not on pushes to `main`: lint first, then
type check, backend tests and frontend tests in parallel.

That is worth being precise about, because it decides where a mistake surfaces. A commit that reaches
`main` any other way than through a checked pull request is unverified, and nothing downstream re-checks
it.

Every job sets `timeout-minutes`. GitHub otherwise lets a hung job run for six hours, which is enough
to spend a fifth of the monthly Actions budget in one go.

## The container build is manual

`.github/workflows/build-images.yml` is triggered **by hand** (`workflow_dispatch`). Nothing builds
images on a push, on a merge, or on a schedule.

```bash
gh workflow run build-images.yml --ref main -f platforms="linux/amd64,linux/arm64"
```

The reason is measured rather than assumed: the multi-platform build under QEMU took about 9.3 minutes
per run (backend 216 s, frontend 339 s), dominated by the emulated `linux/arm64` layer — which is also
the layer that has hung until GitHub's six-hour ceiling. On a day with eight merges and one deployment,
seven of the resulting `:edge` images were never pulled. On a metered Actions budget that was the
single largest avoidable line item.

**What this trades away, and it is the thing to remember: `:edge` does not follow `main`.** It points at
the last manual build and can be many commits behind. Before deploying, check which commit is in the
image — that is what the second tag, `edge-<sha>`, is for. See
[upgrading](../how-to/upgrading.md).

A broken Dockerfile therefore surfaces at the next manual build, not on the pull request. The fallout
is bounded, which is what makes the trade acceptable: a failed build leaves the previous good `:edge`
in place, so the result is a stale image rather than a broken deployment.

Releases are separate: `release.yml` builds from the `production` targets on a published release. The
step it cannot do for you is in [publishing a release](../how-to/publishing-a-release.md).

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

## Code scanning is present but off

`codeql.yml` exists and its analyze job is disabled with `if: false`. Code scanning needs GitHub
Advanced Security, which is Enterprise-only for private repositories, so every run reports `skipped`
and the workflow gates nothing.

It is kept deliberately. CodeQL becomes free the moment the repository is public, and flipping
`if: false` is then the entire change. Until that happens **there is no security scanning in CI** —
worth stating plainly rather than letting the workflow's presence imply coverage that does not exist.

## Dependabot merges itself

`.github/workflows/dependabot-automerge.yml` squash-merges Dependabot pull requests, triggered by CI
completing successfully (`workflow_run`). Major version bumps are excluded and stay open for manual
review.

The gate lives in the workflow rather than in branch protection because required status checks are
unavailable for private repositories on the Free plan. For the same reason the merge does not use
`--auto`: GitHub's auto-merge needs the "Allow auto-merge" repository setting and, without required
checks, would merge immediately anyway — which is the opposite of a gate.

Both constraints disappear when the repository becomes public. Moving the gate into branch protection
is then worth doing, because a workflow that merges its own pull requests is only as trustworthy as
its own trigger.
