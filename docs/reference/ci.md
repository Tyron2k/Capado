# Continuous integration and automation

What runs when, and why the arrangement is shaped the way it is. This lived in the README until it
crowded out what the README is for; it is maintainer detail, not a first impression.

## Pull request checks

`.github/workflows/ci.yml` runs on **pull requests only** — not on pushes to `main`. The fast lint
gate runs first; TypeScript and Python type checks, frontend tests, backend tests on Python 3.12 and
3.14, dependency audits and a real PostgreSQL migration smoke test follow. Dockerfiles are checked
with hadolint and the production container configuration is scanned for misconfigurations.

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

`codeql.yml` analyzes Python and JavaScript/TypeScript on relevant pull requests and pushes, plus a
weekly scheduled run. It uses CodeQL's `security-extended` queries. The repository is public, so the
results appear in GitHub code scanning without a separate paid Advanced Security license.

## Dependabot merges itself

Dependabot checks every configured ecosystem daily at staggered times. Minor and patch updates are
grouped per ecosystem. `.github/workflows/dependabot-automerge.yml` reacts only after CI succeeded,
verifies that the tested commit is still the pull request head, then enables squash auto-merge with
GitHub's expected-head guard.

Major updates, updates without trustworthy Dependabot metadata and ordinary pull requests remain for
manual review. Branch rules require every CI gate but do not require a human approval, which avoids
making the only maintainer approve their own routine changes. Dependabot has no administrator bypass;
auto-merge is still governed by the same required checks as any other pull request.
