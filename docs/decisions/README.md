# Decision records

Nine ADRs, numbered 001 through 009 without a gap. They are cited — from other documents and,
more often, from the code they constrain. That is the test applied: an ADR stays when something
depends on being able to point at it.

The numbering was closed up in a cleanup. Three early records had already been retired, which
left holes at 001, 002 and 008; the rest were renumbered so the sequence runs straight. What the
retired records said is not lost, and is worth keeping visible:

- **"async everywhere"** — now visible in every module of the backend, so a record repeating it
  would be a second copy that can only drift.
- **the page consolidation and the extraction of layout components** — the consolidation is in the
  route table of [architecture.md](../explanation/architecture.md), the layout components have their
  own [reference page](../reference/layout-components.md).

An ADR whose content is fully documented where a reader actually looks does not earn a second home
here. Those were removed on exactly that ground before the renumbering; the numbering simply stopped
advertising their absence.

## Why there are only nine

The decisions that became ADRs were genuinely architectural and cross-cutting: hours as the capacity
base, single-tenant with sites, no actual time recording. Those shape everything built afterwards,
they were argued before the code existed, and they needed somewhere to live that was not a single
module.

The decisions taken since are narrower. They belong to one service each, and they were written into
that service's module docstring at the moment the code was written — not as a summary, but as the
reasoning: what the rule is, which alternatives were rejected, and what the rule refuses.
`services/planning_freeze.py` explains why both the before and after state of a change are checked
and states the consequence plainly. `services/digest.py` explains why suppression, not detection, is
the hard part. `services/dependencies.py` explains why there is one relationship type and why a
violation warns instead of blocking.

Those are ADRs in everything but filename, and they sit next to the code they constrain, where
somebody about to change that code will actually read them.

## Why they are not being back-filled

An ADR records a decision at the moment it was made, with the alternatives that were live then.
Writing further ADRs now would mean reconstructing deliberations from their outcome —
inventing a tidy process that did not happen in that form, and dressing up hindsight as foresight.
A reader cannot tell the difference, which makes a back-filled ADR worse than no ADR: it looks like
evidence.

## Where to look instead

- `docs/explanation/architecture.md` maps every feature area to the file its rules live in.
- `docs/explanation/capacity-model.md` and `conflict-detection.md` cover the two subjects most worth
  understanding before changing anything.
- The module docstring of the service you are about to touch. If it does not explain itself, that is
  a defect worth fixing in the same change.

## For new decisions

A decision that is cross-cutting — one that constrains code outside the module making it — gets an
ADR, numbered from 010. A decision that lives inside one service goes in that service's docstring.
The test is not importance; it is reach.
