# Contributing

Thanks for your interest in contributing to Capado!

## Getting Started

1. Fork the repository
2. Clone your fork and create a branch: `git checkout -b feat/my-feature`
3. Follow [local setup](docs/how-to/local-setup.md), including the local environment variables.
4. Install the project's hook runner: `uv tool install prek`, then `prek install`.
5. Start the dev environment: `docker compose up --build`.

## Development

- **Backend:** `cd backend && uv sync` — Python 3.12 or newer, FastAPI; CI checks
  Python 3.12 and 3.15 and the current runtime image uses 3.15.
- **Frontend:** `cd frontend && npm ci` — TypeScript, React, Mantine

## Before Submitting

- Run `prek run -a` and fix any issues
- Add tests for new features or bug fixes
- Update documentation (docstrings, help pages if user-facing)
- Describe user-visible changes in the pull request title and description; Release Drafter
  generates the release notes from merged pull requests (see below)
- Add i18n strings to both `de.json` and `en.json`

## Product and change boundaries

Capado is a self-hosted, GPL-3.0-or-later planner for qualified people and equipment.
The existing [combined-planning model](docs/explanation/combined-planning.md),
[capacity rules](docs/explanation/capacity-model.md),
[conflict detection](docs/explanation/conflict-detection.md) and
[architecture decisions](docs/decisions/README.md) are the starting point for a change.
Time recording, automatic scheduling and costing are outside the committed product scope.
An open discussion or roadmap idea is not a promise to implement it.

Open an issue before a substantial behavior, schema or architecture change: describe the
problem, a concrete example, the intended outcome and constraints. Small fixes with a clear
reproducer can go directly into a focused PR. Reuse the existing services and contracts;
explain a new abstraction through the problem it solves. Code correctness, an executable
workflow and an observed usability benefit are different claims and need different evidence.

## Issue triage and maintenance

Use the existing [bug](.github/ISSUE_TEMPLATE/bug_report.yml) and
[feature](.github/ISSUE_TEMPLATE/feature_request.yml) forms. Record the motivation,
actual and expected result, reproducible steps, version/environment, relevant constraints
and acceptance criteria. Use a descriptive Conventional Commit-style issue title, such
as `fix(planning): explain an overlapping machine booking`. Mark unknown information as
unknown. For imports, preserve the
reported area, row and field and use a synthetic sample with its headers. Never publish
credentials or real employee/customer records. Follow [SECURITY.md](SECURITY.md) for
vulnerabilities instead of opening a public disclosure issue.

For each report, check the current implementation and related issues, reproduce it where
possible, and separate confirmed behavior from hypotheses. Use the existing labels such
as `bug`, `enhancement` and `documentation`; no new priority-label or epic hierarchy is needed.
Link duplicates to their original report. Close a fixed issue with the merged PR and its
verification; a request for missing evidence or an automatic stale notice is not proof that
a problem has been fixed.

Record a dependency only when it actually prevents completion. For example, an import-feedback
change needs a reproducible failed import; a measured workflow improvement needs the same
before/after task. Independent documentation or UI fixes do not need to wait for a hosting
decision or an unrelated refactoring. When a prerequisite is missing, state exactly what
evidence is needed and continue independent work.

Dependency automation and release handling are described below and in the
[CI reference](docs/reference/ci.md). Keep major upgrades reviewable, retain the required
checks, and use the [release procedure](docs/how-to/publishing-a-release.md) rather than
publishing unvalidated images. Maintainers may decline unsupported scope with a linked rationale
rather than an implied promise. Revisit deferred suggestions when new evidence appears;
do not add a framework or recurring maintenance burden just to keep a ticket moving.

## Languages

The project is bilingual, and which language applies depends on who reads the text — not on who
writes it.

**German** for everything a user or an operating company reads:

- the application UI and the in-app help under `/help` (`frontend/src/i18n/*.json` and
  `frontend/src/features/help/content/`)
- compliance documents (`docs/compliance/`)
- `README.md`

**English** for everything inside the code and around its development:

- identifiers, comments, docstrings, test names, log messages
- commit messages, pull request titles and descriptions, issue discussion
- developer documentation under `docs/` — how-to, reference, explanation, ADRs

The reason for the split is that the two audiences never overlap. A works council reading about
personal data should not need English; a contributor reading `working_time_service.py` should not need
German to follow the reasoning, and mixed-language identifiers (`get_Wochenprofil`) are worse than
either language chosen consistently.

Two consequences worth knowing:

**The in-app help is edited in both languages in the same change.** `de.json` and `en.json` are
checked for key parity by `src/i18n/dictionaries.test.ts`, so touching one without the other fails the
test suite. The German is authoritative when the two disagree.

**`README.en.md` is a translation.** Update `README.md` first; the English file follows.

## Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(conflicts): add severity filter
fix(gantt): correct weekend rendering
docs: update API reference
chore(deps): bump fastapi to 0.116.0
```

## Pull Requests

- Keep PRs focused on a single concern
- Fill out the PR template
- Ensure CI passes before requesting review

### Dependency updates and release notes

Self-hosted Renovate runs nightly through GitHub Actions. Minor/patch updates and
existing hash refreshes share one PR across ecosystems and use GitHub squash
auto-merge after required checks succeed. Major updates remain for review;
TypeScript major updates stay disabled until the lint tooling supports them.
See [CI and bot setup](docs/reference/ci.md#renovate-updates-dependencies) for
credentials, dry runs, security updates and weekly lockfile maintenance.

Release Drafter generates the release notes on [GitHub Releases](https://github.com/Tyron2k/Capado/releases)
from merged PRs, grouped by their Conventional Commit titles with labels as a fallback.
Maintain the PR title and description instead of a separate manual changelog file.

Renovate uses the project's own GitHub App token, so its merges trigger the regular
`push` workflow and refresh the release draft.
Use **Run workflow** on **Release Drafter** to refresh a stale draft manually.

Keep merged commits on `main` intact. Rewording or rebasing them after merge
changes their identities and can break GitHub's association with their PRs,
causing those PRs to disappear from generated release notes.

## Licensing of contributions

By submitting a contribution you agree that it is licensed under **GPL-3.0-or-later**:
GPL version 3 or, at the recipient's option, any later version, as for the rest of the project. You keep your copyright — nothing is assigned and nothing is signed.

That is the whole agreement, and it is deliberately the whole agreement. Capado is not sold and has
no commercial edition, so there is no reason to ask contributors for the broader rights a
contributor licence agreement would need. The Linux kernel and most GNU projects work exactly this
way.

The licence already permits recipients to choose a later GPL version. Licensing contributions
under unrelated terms would require permission from the relevant copyright holders; this agreement
does not grant that additional permission.

If your employer has rights to intellectual property you create, make sure contributing is
permitted before you do. Employment contracts assigning work-related IP are common and broadly
worded, and that is your side of the fence, not something this project can check.

**Reporting a bug or proposing a design needs no agreement at all.** Open an issue — a well-argued
problem is a real contribution, and none of the above concerns it.

## Code of Conduct

Be respectful and constructive. We're all here to build something useful.
