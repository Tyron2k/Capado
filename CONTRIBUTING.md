# Contributing

Thanks for your interest in contributing to Capado!

## Getting Started

1. Fork the repository
2. Clone your fork and create a branch: `git checkout -b feat/my-feature`
3. Install pre-commit hooks: `pre-commit install`
4. Start the dev environment: `docker compose up`

## Development

- **Backend:** `cd backend && uv sync` — Python 3.12, FastAPI
- **Frontend:** `cd frontend && npm ci` — TypeScript, React, Mantine

## Before Submitting

- Run `pre-commit run --all-files` and fix any issues
- Add tests for new features or bug fixes
- Update documentation (docstrings, help pages if user-facing)
- Update `docs/changelog.md` for user-visible changes
- Add i18n strings to both `de.json` and `en.json`

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

## Licensing of contributions

By submitting a contribution you agree that it is licensed under the **GPL-3.0**, the same terms as
the rest of the project. You keep your copyright — nothing is assigned and nothing is signed.

That is the whole agreement, and it is deliberately the whole agreement. Capado is not sold and has
no commercial edition, so there is no reason to ask contributors for the broader rights a
contributor licence agreement would need. The Linux kernel and most GNU projects work exactly this
way.

One consequence, stated plainly rather than discovered later: because the copyright stays spread
across contributors, the project **cannot** be relicensed later without asking every one of them.
That door is closed on purpose — the licence is the answer, not a starting position.

If your employer has rights to intellectual property you create, make sure contributing is
permitted before you do. Employment contracts assigning work-related IP are common and broadly
worded, and that is your side of the fence, not something this project can check.

**Reporting a bug or proposing a design needs no agreement at all.** Open an issue — a well-argued
problem is a real contribution, and none of the above concerns it.

## Code of Conduct

Be respectful and constructive. We're all here to build something useful.
