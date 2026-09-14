"""Tests for :mod:`app.services.customer_resolution`.

Inheritance is where this goes wrong quietly. A consumer that reads ``project.customer_id`` directly
loses every project that inherits from its folder — which is the normal case, since the whole point
is typing the customer once per folder. So the rule lives in one function and the tests pin all three
halves of it: the project's own value wins, otherwise the walk goes UP the tree, and nothing is
invented when nobody named a customer.

No database. All ids are inline and fictional.
"""

from __future__ import annotations

from uuid import UUID

from app.services.customer_resolution import (
    FolderNode,
    inherited_from_folder,
    resolve_customer_id,
)

ACME = UUID("aaaaaaaa-0000-0000-0000-000000000001")
OTHER = UUID("aaaaaaaa-0000-0000-0000-000000000002")

ROOT = UUID("bbbbbbbb-0000-0000-0000-000000000001")
CHILD = UUID("bbbbbbbb-0000-0000-0000-000000000002")
GRANDCHILD = UUID("bbbbbbbb-0000-0000-0000-000000000003")
ORPHAN = UUID("bbbbbbbb-0000-0000-0000-000000000009")

# Root names ACME; the two levels below it name nobody.
TREE = {
    ROOT: FolderNode(folder_id=ROOT, parent_id=None, customer_id=ACME),
    CHILD: FolderNode(folder_id=CHILD, parent_id=ROOT, customer_id=None),
    GRANDCHILD: FolderNode(folder_id=GRANDCHILD, parent_id=CHILD, customer_id=None),
}


class TestResolve:
    def test_the_projects_own_customer_wins(self):
        """An explicit value is a correction the operator made on purpose. Letting the folder
        override it would make the field unusable."""
        assert resolve_customer_id(OTHER, ROOT, TREE) == OTHER

    def test_a_project_in_a_folder_inherits_it(self):
        assert resolve_customer_id(None, ROOT, TREE) == ACME

    def test_inheritance_walks_up_through_folders_that_name_nobody(self):
        """Nesting means one job splitting into stages; the stages are for the same
        customer as the job."""
        assert resolve_customer_id(None, GRANDCHILD, TREE) == ACME

    def test_the_nearest_named_folder_wins(self):
        """A sub-folder naming its own customer is a shared parent folder holding work for
        different customers — the case that makes folder-only modelling wrong."""
        tree = dict(TREE)
        tree[CHILD] = FolderNode(folder_id=CHILD, parent_id=ROOT, customer_id=OTHER)
        assert resolve_customer_id(None, GRANDCHILD, tree) == OTHER

    def test_a_project_in_no_folder_has_no_customer(self):
        assert resolve_customer_id(None, None, TREE) is None

    def test_a_tree_where_nobody_names_a_customer_yields_none(self):
        """Not a placeholder and not the first customer in the table. Guessing would put a name
        on a report nobody entered."""
        nameless = {
            ROOT: FolderNode(folder_id=ROOT, parent_id=None, customer_id=None),
            CHILD: FolderNode(folder_id=CHILD, parent_id=ROOT, customer_id=None),
        }
        assert resolve_customer_id(None, CHILD, nameless) is None

    def test_a_dangling_folder_reference_yields_none_rather_than_guessing(self):
        assert resolve_customer_id(None, ORPHAN, TREE) is None

    def test_a_cycle_terminates(self):
        """The folder service prevents cycles on write. A walk that trusts that and is wrong
        hangs a worker inside a request; tracking visited ids turns a corrupted tree into a
        missing customer instead."""
        cyclic = {
            ROOT: FolderNode(folder_id=ROOT, parent_id=CHILD, customer_id=None),
            CHILD: FolderNode(folder_id=CHILD, parent_id=ROOT, customer_id=None),
        }
        assert resolve_customer_id(None, ROOT, cyclic) is None

    def test_a_cycle_still_finds_a_customer_on_the_way(self):
        cyclic = {
            ROOT: FolderNode(folder_id=ROOT, parent_id=CHILD, customer_id=None),
            CHILD: FolderNode(folder_id=CHILD, parent_id=ROOT, customer_id=ACME),
        }
        assert resolve_customer_id(None, ROOT, cyclic) == ACME


class TestInheritedFromFolder:
    def test_an_explicit_customer_is_not_inherited(self):
        assert inherited_from_folder(OTHER, ROOT, TREE) is False

    def test_a_customer_from_the_folder_is_reported_as_inherited(self):
        """Shown in the UI so an operator does not "correct" a value they never typed and pin
        it by accident."""
        assert inherited_from_folder(None, GRANDCHILD, TREE) is True

    def test_no_customer_at_all_is_not_inherited(self):
        assert inherited_from_folder(None, None, TREE) is False
