"""Folder tree navigation and the guard that keeps it a tree.

Folders group projects and may nest, so the same three problems appear that any
self-referencing table has: walking to the root, keeping the order stable, and
refusing a move that would make a folder its own ancestor. All three are pure
functions over already-loaded rows, so the cycle guard is provable rather than
asserted and no database is needed to test it.

A cycle here would be corrupt data rather than a user error, but it must still be
impossible to create: once one exists, every reader has to defend against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class FolderNode:
    """The tree fields of one folder, independent of the ORM."""

    id: UUID
    parent_id: UUID | None
    position: int
    name: str


def ancestors(node_id: UUID, by_id: dict[UUID, FolderNode]) -> list[UUID]:
    """Ids from the given folder up to its root, nearest first.

    Terminates on a cycle instead of looping: bad data must not hang a request. The
    offending link is simply not followed further.
    """
    chain: list[UUID] = []
    seen: set[UUID] = {node_id}
    current = by_id.get(node_id)
    while current is not None and current.parent_id is not None:
        if current.parent_id in seen:
            break
        seen.add(current.parent_id)
        chain.append(current.parent_id)
        current = by_id.get(current.parent_id)
    return chain


def would_create_cycle(
    node_id: UUID, new_parent_id: UUID | None, by_id: dict[UUID, FolderNode]
) -> bool:
    """Whether moving a folder would put it inside its own subtree.

    Checked before the write rather than repaired afterwards.
    """
    if new_parent_id is None:
        return False
    if new_parent_id == node_id:
        return True
    return node_id in ancestors(new_parent_id, by_id)


def children_of(parent_id: UUID | None, nodes: list[FolderNode]) -> list[FolderNode]:
    """Direct children in their intended sequence.

    Ordered by position, then name as a tiebreaker so the result is stable — a
    listing that reorders between two requests cannot be read by a human.
    """
    return sorted(
        (n for n in nodes if n.parent_id == parent_id),
        key=lambda n: (n.position, n.name),
    )


def roots(nodes: list[FolderNode]) -> list[FolderNode]:
    """Top-level folders, in sequence."""
    return children_of(None, nodes)


def descendants(node_id: UUID, nodes: list[FolderNode]) -> list[UUID]:
    """Every folder below the given one, at any depth.

    Needed when a folder is deleted or when a listing should include everything
    filed further down. Breadth-first with a visited set, so a cycle in corrupt data
    ends the walk rather than continuing forever.
    """
    by_parent: dict[UUID | None, list[FolderNode]] = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    found: list[UUID] = []
    seen: set[UUID] = {node_id}
    queue: list[UUID] = [node_id]
    while queue:
        current = queue.pop(0)
        for child in by_parent.get(current, []):
            if child.id in seen:
                continue
            seen.add(child.id)
            found.append(child.id)
            queue.append(child.id)
    return found
