"""Resources belong to a site, and resource groups are flat.

Two changes are pinned here, and both are the kind that pass a naive test while being wrong.

THE SENTINEL. ``site_id`` is optional, so None is a MEANINGFUL value: a resource can stop
belonging to a site. If the update path used None as its "leave alone" marker — as it does for
``name`` and ``group_id``, where the field is mandatory and clearing is not a case — then removing
a site would be impossible to express, and the API would silently ignore the request. The tests
therefore assert the difference between "field absent" and "field explicitly null", which is
exactly what a round-trip test would miss.

No database. ``get_*_resource_by_id`` reaches the session only through ``get``, so a dict-backed
double exercises the real service code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.models.resource import InfrastructureResource, PersonalResource
from app.schemas.resource import ResourceCreate, ResourceUpdate
from app.services import resource_service
from app.services.partial_update import UNSET

GROUP = UUID("22222222-0000-0000-0000-000000000001")
SITE_A = UUID("33333333-0000-0000-0000-00000000000a")
SITE_B = UUID("33333333-0000-0000-0000-00000000000b")


class _FakeSession:
    """Enough AsyncSession to run the resource service: get, add, commit."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = {(type(r), r.id): r for r in rows}
        self.committed = 0

    async def get(self, model: type, pk: UUID) -> Any:
        return self._rows.get((model, pk))

    def add(self, obj: Any) -> None:  # pragma: no cover — nothing to assert
        pass

    async def commit(self) -> None:
        self.committed += 1


def _personal(site_id: UUID | None) -> PersonalResource:
    return PersonalResource(
        id=uuid4(),
        name="Müller",
        group_id=GROUP,
        site_id=site_id,
        is_active=True,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _infrastructure(site_id: UUID | None) -> InfrastructureResource:
    return InfrastructureResource(
        id=uuid4(),
        name="Gleis 27",
        group_id=GROUP,
        site_id=site_id,
        is_active=True,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )


class TestTheUpdateSentinel:
    """Omitting a site and clearing a site are different requests."""

    @pytest.mark.asyncio
    async def test_omitting_the_site_leaves_it_untouched(self):
        resource = _personal(SITE_A)
        session = _FakeSession([resource])
        result = await resource_service.update_personal_resource(
            session,  # type: ignore[arg-type]
            resource.id,
            name="Müller",
        )
        assert result.site_id == SITE_A

    @pytest.mark.asyncio
    async def test_passing_none_removes_the_site(self):
        """The case a None-means-leave-alone implementation cannot express at all."""
        resource = _personal(SITE_A)
        session = _FakeSession([resource])
        result = await resource_service.update_personal_resource(
            session,  # type: ignore[arg-type]
            resource.id,
            site_id=None,
        )
        assert result.site_id is None

    @pytest.mark.asyncio
    async def test_passing_a_site_moves_the_resource(self):
        resource = _personal(SITE_A)
        session = _FakeSession([resource])
        result = await resource_service.update_personal_resource(
            session,  # type: ignore[arg-type]
            resource.id,
            site_id=SITE_B,
        )
        assert result.site_id == SITE_B

    @pytest.mark.asyncio
    async def test_unset_is_explicitly_the_leave_alone_value(self):
        resource = _personal(SITE_A)
        session = _FakeSession([resource])
        result = await resource_service.update_personal_resource(
            session,  # type: ignore[arg-type]
            resource.id,
            site_id=UNSET,
        )
        assert result.site_id == SITE_A

    @pytest.mark.asyncio
    async def test_infrastructure_behaves_identically(self):
        """Both resource types share one code path; a divergence here would be silent."""
        resource = _infrastructure(SITE_A)
        session = _FakeSession([resource])
        cleared = await resource_service.update_infrastructure_resource(
            session,  # type: ignore[arg-type]
            resource.id,
            site_id=None,
        )
        assert cleared.site_id is None


class TestCreateTakesASite:
    """A site is optional on create, because a single-plant operator files nothing at one."""

    @pytest.mark.asyncio
    async def test_a_resource_can_be_created_without_a_site(self):
        session = _FakeSession([])
        result = await resource_service.create_personal_resource(
            session,  # type: ignore[arg-type]
            name="Schmidt",
            group_id=GROUP,
        )
        assert result.site_id is None

    @pytest.mark.asyncio
    async def test_a_resource_can_be_created_at_a_site(self):
        session = _FakeSession([])
        result = await resource_service.create_infrastructure_resource(
            session,  # type: ignore[arg-type]
            name="Gleis 31",
            group_id=GROUP,
            site_id=SITE_B,
        )
        assert result.site_id == SITE_B


class TestTheRouterContract:
    """What the router relies on to tell "absent" from "null" — pure Pydantic, no service."""

    def test_an_omitted_site_does_not_appear_in_the_sent_fields(self):
        sent = ResourceUpdate(name="Müller").model_dump(exclude_unset=True)
        assert "site_id" not in sent

    def test_an_explicit_null_site_does_appear_in_the_sent_fields(self):
        """Without this, clearing a site is indistinguishable from not mentioning it."""
        sent = ResourceUpdate(name="Müller", site_id=None).model_dump(
            exclude_unset=True
        )
        assert "site_id" in sent
        assert sent["site_id"] is None

    def test_create_defaults_the_site_to_none(self):
        assert ResourceCreate(name="Schmidt", group_id=GROUP).site_id is None
