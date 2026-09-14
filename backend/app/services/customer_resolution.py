"""Which customer a project belongs to, given the folder it sits in.

Pure, so the inheritance rule is testable and stated in exactly one place. Every consumer that
needs "who is this for" goes through :func:`resolve_customer_id` rather than reading either column
directly — a caller reading ``project.customer_id`` alone silently loses every project that inherits
from its folder, which is the normal case.

The rule, and what each half refuses:

**A project's own customer wins.** Set explicitly, it is a correction the operator made on purpose,
and letting the folder override it would make the field unusable.

**Otherwise the folder's customer applies, walking UP the tree.** A sub-folder that names no
customer belongs to whatever its parent does, because that is what nesting means here: a job
splits into stages, and the stages are for the same customer as the job.

**Nothing is invented.** A project in no folder, or in a tree where nobody names a customer, has no
customer — not a placeholder and not the first customer in the table. "Unknown" and "none" are the
same answer here and both are legitimate; guessing would put a name on a report that nobody entered.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class FolderNode:
    """One folder's customer link and its parent, which is all the walk needs."""

    folder_id: UUID
    parent_id: UUID | None
    customer_id: UUID | None


def resolve_customer_id(
    project_customer_id: UUID | None,
    folder_id: UUID | None,
    folders: dict[UUID, FolderNode],
) -> UUID | None:
    """The effective customer of one project.

    ``folders`` maps folder id to node, so the walk needs no queries.

    Cycle-safe: the folder service prevents cycles on write, but a walk that trusts that and is
    wrong loops forever inside a request. Visited ids are tracked, which costs nothing and turns a
    corrupted tree into a missing customer rather than a hung worker.
    """
    if project_customer_id is not None:
        return project_customer_id

    seen: set[UUID] = set()
    current = folder_id
    while current is not None and current not in seen:
        seen.add(current)
        node = folders.get(current)
        if node is None:
            # A folder id with no node is a dangling reference, not a reason to guess.
            return None
        if node.customer_id is not None:
            return node.customer_id
        current = node.parent_id
    return None


def inherited_from_folder(
    project_customer_id: UUID | None,
    folder_id: UUID | None,
    folders: dict[UUID, FolderNode],
) -> bool:
    """Whether the effective customer came from a folder rather than the project.

    Worth surfacing in the UI: a customer shown on a project that was never typed there is
    information the operator needs before they "correct" it and accidentally pin it.
    """
    if project_customer_id is not None:
        return False
    return resolve_customer_id(None, folder_id, folders) is not None
