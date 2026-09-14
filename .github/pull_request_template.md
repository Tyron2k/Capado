## Summary

<!-- Brief description of what this PR does -->

## Changes

-

## Type

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor
- [ ] Documentation
- [ ] CI / Infrastructure
- [ ] Dependencies

## Checklist

- [ ] Pre-commit hooks pass (`prek run -a`)
- [ ] Tests added/updated for changes
- [ ] Docstrings updated where the reasoning changed
- [ ] i18n: new strings added to both `de.json` and `en.json`
- [ ] Commit messages follow Conventional Commits format

**Does this change what a user sees or how the app behaves?** If yes, name the help article you
updated — or say why none applies. Write an answer rather than ticking a box:

> _replace this line with the article slug, or "none, because …"_

A tick was not enough: five statements in the shipped help survived the releases that made them false,
including one that told users to model part-time as an absence and so produced wrong capacity numbers.
`tests/test_docs_coverage.py` catches a MISSING endpoint or table, never a false sentence — that part
only a reader catches, which is what this question is for.
