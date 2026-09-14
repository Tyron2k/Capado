"""The display names a resource response carries but does not store.

WHY THIS EXISTS. ``group_name`` and ``site_name`` are denormalised onto every resource response so a
client can render a table without a request per row. They are not columns, so each endpoint has to
resolve them — and EIGHT of them did not: the paginated list, the single fetch, create and update, for
personal and for infrastructure alike, all returned the raw model rows. Pydantic filled both fields
from their schema default of ``""`` on every response, always.

Nothing in the frontend consumed those endpoints, which is why nothing surfaced it. An API consumer
would have read ``group_name: ""`` as "this resource has no group name": an empty string is a
statement, not an error, so there was nothing for anybody to notice.

Written against the real schema rather than a session double, and that is the point rather than
thoroughness for its own sake. The whole bug is that a response was assembled from the wrong object —
a double asked for ``group_name`` returns whatever it was told to return, so the assertion passes
while production ships an empty string.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource import InfrastructureResource, PersonalResource
from app.models.resource_group import ResourceGroup, ResourceType
from app.models.site import Site
from app.services import resource_names


async def _group(session: AsyncSession, name: str) -> ResourceGroup:
    group = ResourceGroup(name=name)
    session.add(group)
    await session.flush()
    return group


async def _site(session: AsyncSession, name: str) -> Site:
    site = Site(name=name)
    session.add(site)
    await session.flush()
    return site


async def _person(
    session: AsyncSession, name: str, group: ResourceGroup, site: Site | None
) -> PersonalResource:
    person = PersonalResource(
        name=name, group_id=group.id, site_id=site.id if site else None
    )
    session.add(person)
    await session.flush()
    return person


@pytest.mark.asyncio
class TestResourceNames:
    async def test_a_response_carries_the_group_and_site_names(
        self, db_session: AsyncSession
    ) -> None:
        group = await _group(db_session, "Lackierer")
        site = await _site(db_session, "Werk Süd")
        person = await _person(db_session, "A. Beispiel", group, site)

        built = await resource_names.to_response(db_session, person)

        assert built.group_name == "Lackierer"
        assert built.site_name == "Werk Süd"
        # The ids travel too: a client that wants to filter needs them, and a name alone cannot be
        # matched back to anything.
        assert built.group_id == group.id
        assert built.site_id == site.id

    async def test_a_resource_at_no_site_reports_an_empty_site_name(
        self, db_session: AsyncSession
    ) -> None:
        # A single-plant operator files nothing at a site. That must read as "no site", not as a
        # failure to resolve one — which is why the empty string is the right answer HERE and was
        # the wrong answer everywhere else.
        group = await _group(db_session, "Elektrik")
        person = await _person(db_session, "B. Beispiel", group, None)

        built = await resource_names.to_response(db_session, person)

        assert built.group_name == "Elektrik"
        assert built.site_name == ""
        assert built.site_id is None

    async def test_a_list_resolves_every_row(self, db_session: AsyncSession) -> None:
        first = await _group(db_session, "Montage")
        second = await _group(db_session, "Prüfwesen")
        site = await _site(db_session, "Hauptwerk")
        people = [
            await _person(db_session, "C. Beispiel", first, site),
            await _person(db_session, "D. Beispiel", second, None),
            await _person(db_session, "E. Beispiel", first, site),
        ]

        built = await resource_names.to_responses(db_session, people)

        assert [b.group_name for b in built] == ["Montage", "Prüfwesen", "Montage"]
        assert [b.site_name for b in built] == ["Hauptwerk", "", "Hauptwerk"]

    async def test_an_empty_list_needs_no_queries(
        self, db_session: AsyncSession
    ) -> None:
        assert await resource_names.to_responses(db_session, []) == []

    async def test_an_unknown_id_resolves_to_an_empty_name_rather_than_raising(
        self, db_session: AsyncSession
    ) -> None:
        # Asserted on the MAP, not by deleting a group out from under a resource: the foreign key
        # forbids that, which the first draft of this test discovered the hard way. So the tolerance
        # is a property of the lookup — an id it is handed and cannot find — and not a database state
        # anybody can reach while the constraints hold.
        #
        # Worth keeping tolerant even so. A list endpoint that raises on one unresolvable id shows
        # the operator nothing at all, including the rows that are fine and the row they would need
        # to see in order to fix it.
        missing = uuid4()

        groups = await resource_names.group_name_map(db_session, [missing])
        sites = await resource_names.site_name_map(db_session, [missing])

        assert groups == {}
        assert sites == {}
        assert groups.get(missing, "") == ""

    async def test_infrastructure_resolves_the_same_way(
        self, db_session: AsyncSession
    ) -> None:
        # The same builder serves both types. A second implementation for machines is how the tree
        # endpoints and the list endpoints came to disagree in the first place.
        group = ResourceGroup(
            name="Prüfstände", resource_type=ResourceType.infrastructure
        )
        db_session.add(group)
        site = await _site(db_session, "Hauptwerk")
        await db_session.flush()
        machine = InfrastructureResource(
            name="Prüfstand Elektrik", group_id=group.id, site_id=site.id
        )
        db_session.add(machine)
        await db_session.flush()

        built = await resource_names.to_response(db_session, machine)

        assert built.group_name == "Prüfstände"
        assert built.site_name == "Hauptwerk"
