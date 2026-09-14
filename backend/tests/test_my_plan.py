"""The signed-in person reading their own plan, and an admin setting the link.

The security property of ``GET /api/me/plan`` is structural rather than checked: the resource id comes
from the CALLER'S account and there is no path parameter to point elsewhere. These tests pin the two
things that could still go wrong — an unlinked account must not silently look like an empty plan, and
the id handed to the services must be the caller's own.

Linking is an admin action, so its failure modes are pinned too: an unknown person, and a person
already claimed by a different account.

Mock sessions and services throughout; the composition is what is under test, not the queries the
three services already have their own tests for.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.routers.me import get_my_plan
from app.routers.users import update_user
from app.schemas.user import UserUpdateRequest


@pytest.fixture(autouse=True)
def setup_database():
    """No-op override: these tests use mocks, not the test database."""
    yield


def _user(resource_id=None, role=UserRole.editor) -> User:
    """An account, optionally linked to a scheduled person."""
    return User(
        id=uuid4(),
        email="person@example.test",
        name="Scheduled Person",
        password_hash="hash",
        role=role,
        is_active=True,
        must_change_password=False,
        resource_id=resource_id,
    )


class TestMyPlan:
    """Reading one's own plan."""

    async def test_unlinked_account_is_a_409_not_an_empty_plan(self):
        """An empty plan and "nobody told this system who you are" are different answers.

        Returning the first for the second would have people conclude they are scheduled for nothing.
        """
        with pytest.raises(HTTPException) as exc_info:
            await get_my_plan(current_user=_user(resource_id=None), session=AsyncMock())

        assert exc_info.value.status_code == 409
        assert exc_info.value.headers["X-Error-Code"] == "no_linked_resource"

    async def test_the_caller_s_own_resource_id_is_what_gets_queried(self):
        """The whole security model: the id comes from the account, never from the request."""
        mine = uuid4()
        caller = _user(resource_id=mine)

        with (
            patch("app.routers.me.AssignmentService") as assignments,
            patch("app.routers.me.AbsenceService") as absences,
            patch("app.routers.me.SkillService") as skills,
        ):
            assignments.return_value.get_all = AsyncMock(return_value=([], 0))
            absences.return_value.get_for_resource = AsyncMock(return_value=([], 0))
            skills.return_value.get_personal_resource_skills = AsyncMock(
                return_value=[]
            )

            result = await get_my_plan(current_user=caller, session=AsyncMock())

            assert (
                assignments.return_value.get_all.await_args.kwargs["resource_id"]
                == mine
            )
            assert absences.return_value.get_for_resource.await_args.args[0] == mine
            assert (
                skills.return_value.get_personal_resource_skills.await_args.args[0]
                == mine
            )

        assert result.resource_id == mine

    async def test_totals_are_carried_alongside_the_pages(self):
        """A caller has to tell "this is everything" from "this is the first page"."""
        caller = _user(resource_id=uuid4())

        with (
            patch("app.routers.me.AssignmentService") as assignments,
            patch("app.routers.me.AbsenceService") as absences,
            patch("app.routers.me.SkillService") as skills,
        ):
            assignments.return_value.get_all = AsyncMock(return_value=([], 412))
            absences.return_value.get_for_resource = AsyncMock(return_value=([], 7))
            skills.return_value.get_personal_resource_skills = AsyncMock(
                return_value=[]
            )

            result = await get_my_plan(current_user=caller, session=AsyncMock())

        assert result.assignment_total == 412
        assert result.absence_total == 7


def _session_for_update(user: User, clash: User | None = None) -> AsyncMock:
    """Mock session: the target user by id, a PersonalResource by get(), and a clash query."""
    target_result = MagicMock()
    target_result.scalar_one_or_none = lambda: user
    clash_result = MagicMock()
    clash_result.scalar_one_or_none = lambda: clash

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[target_result, clash_result])
    session.get = AsyncMock(return_value=object())  # the personal resource exists
    session.add = MagicMock()
    return session


class TestAdminSetsTheLink:
    """An administrator connects an account to the person it plans."""

    async def test_link_is_set(self):
        target = _user(resource_id=None)
        person = uuid4()
        session = _session_for_update(target)

        await update_user(
            target.id,
            UserUpdateRequest(resource_id=person),
            admin_user=_user(role=UserRole.admin),
            session=session,
        )

        assert target.resource_id == person

    async def test_omitting_the_field_leaves_an_existing_link_alone(self):
        """Otherwise every rename would silently unlink somebody from their own plan."""
        existing = uuid4()
        target = _user(resource_id=existing)
        session = _session_for_update(target)

        await update_user(
            target.id,
            UserUpdateRequest(name="Renamed"),
            admin_user=_user(role=UserRole.admin),
            session=session,
        )

        assert target.resource_id == existing

    async def test_clearing_needs_its_own_flag(self):
        """Removing a link is explicit, since omission has to mean "leave alone"."""
        target = _user(resource_id=uuid4())
        session = _session_for_update(target)

        await update_user(
            target.id,
            UserUpdateRequest(clear_resource_id=True),
            admin_user=_user(role=UserRole.admin),
            session=session,
        )

        assert target.resource_id is None

    async def test_unknown_person_is_a_404(self):
        target = _user(resource_id=None)
        session = _session_for_update(target)
        session.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await update_user(
                target.id,
                UserUpdateRequest(resource_id=uuid4()),
                admin_user=_user(role=UserRole.admin),
                session=session,
            )

        assert exc_info.value.status_code == 404

    async def test_person_already_linked_elsewhere_is_a_409(self):
        """Two accounts claiming one person would make "my plan" depend on which you used."""
        target = _user(resource_id=None)
        other_account = _user(resource_id=uuid4())
        session = _session_for_update(target, clash=other_account)

        with pytest.raises(HTTPException) as exc_info:
            await update_user(
                target.id,
                UserUpdateRequest(resource_id=uuid4()),
                admin_user=_user(role=UserRole.admin),
                session=session,
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.headers["X-Error-Code"] == "resource_already_linked"
