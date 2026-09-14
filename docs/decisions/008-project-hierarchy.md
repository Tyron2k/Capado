# ADR-008: Optional Project Folders and Derived Progress

## Status

Accepted. Supersedes an earlier version of this ADR that made `Project`
self-referencing; see *Rejected: a parent project* below for why that was wrong.

## Context

The unit that actually gets scheduled is the individual item, not the order
containing it. In the deployment this was designed against an order covers a series of
items worked through in sequence, each with its own dates, work packages and delivery
date — the operator's own tracking sheet is ordered by delivery date for that reason.

Before this ADR a project was a flat, standalone thing. There was nowhere to record
that a set of projects belongs together, no way to say what order they run in, and no
way to hold the identifier the plant knows them by.

The grouping level is not the same everywhere. One customer groups by order, another
by customer or by year, a third not at all. Whatever is built must therefore be
optional, and its depth must be data rather than schema.

Progress had the same gap: there was no way to record that a work package was
finished, so no way to answer "how far is this item".

## Decision

### A folder is its own entity, and it is optional

`ProjectFolder` groups projects. `projects.folder_id` is nullable and NULL by
default, so a deployment that never creates a folder behaves exactly as it did
before. Folders may nest, because grouping by customer *and* by order is an ordinary
wish and the guard that makes nesting safe is the same either way. Depth is not
capped: a limit chosen now would be a guess.

A folder holds a name, a parent and a position. It has no dates, no work packages and
no assignments — it is a grouping, not a planning object.

### Rejected: a parent project

The first version of this ADR made `Project` self-referencing: an order was a project
with child projects. That is a smaller schema change and it was wrong, for three
reasons that only became clear once the delete path was written.

A container had to carry a **start date and end date**, because `Project` requires
them. For an order that is either a duplicate of the span its items already imply,
or a second figure free to contradict them.

Nothing prevented **work packages and assignments** being attached to the container.
Two people could then plan the same work at two levels, and no rule in the model said
which one counted.

Worst, **deleting had to be refused.** Removing a project with children would take
real planned units, their work packages and their assignments with it, so the only
safe behaviour was to make the user empty the container first. That is bad behaviour
dressed as a safety feature: the user asked to remove a grouping and was told to
dismantle their plan.

A folder has none of these problems. Deleting one unfiles its projects — `folder_id`
back to NULL — and moves its sub-folders up one level. Nothing is cascaded, and the
operation cannot destroy a plan, which is what makes it safe to offer at all.

### Sequence is an explicit ordinal

`projects.position` orders projects within a folder, and `project_folders.position`
orders folders among siblings. Both fall back to name as a tiebreaker so a listing
cannot reorder itself between two requests.

Deriving the order from start dates breaks the moment two units start on the same day,
and deriving it from delivery dates confuses intent with outcome. `position` is not a
dependency: it says what order things are meant to run in, not that one cannot begin
before another finishes.

### `external_ref` instead of a domain-specific number

A free identifier from whatever system the customer already uses. One operator fills it
with a unit number; elsewhere it is a serial number, a VIN or a batch id. A column named
after one industry's vocabulary would write that vocabulary into the schema.

Indexed but not unique: the same reference legitimately recurs when a unit is reworked
under a second order, or when two customers' numbering collides. Uniqueness is a
customer's policy, not a property of the field.

The item *type* needs no field. It selects a standard sequence of work packages,
which is what `WorkPackageTemplate` already is.

### Progress lives on the work package, and project status is derived

`WorkPackage.completed_at` — a timestamp, not a boolean, because "when did it finish"
is the question a delay analysis asks and a flag cannot answer it. Setting it back to
NULL reopens the package, which has to stay possible: a completion marked by mistake
is an ordinary correction, and the audit log records both the closing and the
reopening.

Project status is **derived**: the name of the furthest completed work package. A
status field on the project was rejected because the values a planner would write into
it *are* work package names, so storing them on the project would be a second copy of
the same truth, free to drift.

"Furthest" is by completion time, not by schedule. If two packages were closed out of
order, the status has to say what actually finished last rather than what the plan
expected to.

Completion ratio is counted per package and deliberately unweighted. Weighting would
need an effort field, and deriving progress from effort invites deriving duration from
it — the substitution ADR-005's requirement modes exist to prevent.

## Consequences

Folders are a feature that can be ignored entirely. That is the point, and it is also
the risk: an optional grouping with no user interface is indistinguishable from an
oversight, so the folder tree has to be reachable in the UI or the feature should not
exist.

The cycle guard runs on create and on move, before the write, because once a cycle is
in the table every reader has to defend against it. The walk terminates on a cycle
anyway, so corrupt data degrades a listing instead of hanging a request.

`ProjectFolderService.delete` reports how many projects it unfiled and how many
sub-folders it moved, so the caller can tell the user what happened rather than
leaving them to wonder where their projects went.

Costs could attach a budget to a folder — an order-level budget consumed by its items —
without a folder having to pretend to be a project. That was the original reason this ADR
had to land before the costing work, and the folder model serves it better than a parent
project would have: a budget on a container that also carried its own work packages would
have had to distinguish own consumption from its children's.

**Costing is now out of scope** (see `docs/reference/known-limitations.md`): Capado plans
capacity and is deliberately not a calculator. The reasoning above is kept because it is
still why the folder model has the shape it does, not because the budget work is next.

Lead time in working days is deliberately out of scope here and lands separately, in
ADR-009's neighbouring work. It needs its own decision about what happens when a
derived end date and an entered end date disagree.
