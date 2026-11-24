"""Integration checks for read-only planning previews against the real schema."""

from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_session
from app.exceptions import register_exception_handlers
from app.models.assignment import Assignment
from app.models.calendar import WorkWeekProfile
from app.models.conflict import Conflict
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.user import User
from app.routers.assignments import router
from app.schemas.assignment import AssignmentCreate, AssignmentPreviewRequest
from app.services.assignment_preview import AssignmentPreviewService
from app.services.permissions import get_current_user
from app.services.time_zone import local_wall_time_to_utc, planning_zone
from tests.planning_reference import MONDAY, _clock, _seed_plan


async def test_outdated_review_cannot_overwrite_an_intervening_booking_edit(
    db_session: AsyncSession,
) -> None:
    plan = await _seed_plan(db_session)
    booking = plan.machine_booking
    tuesday = MONDAY + timedelta(days=1)
    path = f"/assignments/{booking.id}"
    proposed = {
        "start_at": _clock(tuesday, 2).isoformat(),
        "end_at": _clock(tuesday, 6).isoformat(),
    }
    intervening = {
        "start_at": _clock(tuesday, 3).isoformat(),
        "end_at": _clock(tuesday, 5).isoformat(),
    }
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def session_for_request():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_for_request
    app.dependency_overrides[get_current_user] = lambda: User(
        email="admin@example.test", name="Admin", password_hash="unused", role="admin"
    )
    async with (
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as reviewer,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as editor,
    ):
        original = (await reviewer.get(path)).json()
        expected = AssignmentCreate.model_validate(original).model_dump(mode="json")
        preview = await reviewer.post(
            "/assignments/preview",
            json={**expected, **proposed, "assignment_id": str(booking.id)},
        )
        assert preview.status_code == 200
        assert (await editor.put(path, json=intervening)).status_code == 200

        response = await reviewer.put(
            path, json={**proposed, "expected_booking": expected}
        )
        assert response.status_code == 409
        assert response.json()["code"] == "assignment_changed"
        latest = (await reviewer.get(path)).json()
        assert datetime.fromisoformat(latest["start_at"]) == _clock(tuesday, 3)
        assert datetime.fromisoformat(latest["end_at"]) == _clock(tuesday, 5)

        current = AssignmentCreate.model_validate(latest).model_dump(mode="json")
        new_preview = await reviewer.post(
            "/assignments/preview",
            json={**current, **proposed, "assignment_id": str(booking.id)},
        )
        assert new_preview.status_code == 200
        applied = await reviewer.put(
            path, json={**proposed, "expected_booking": current}
        )
        assert applied.status_code == 200
        assert datetime.fromisoformat(
            applied.json()["assignment"]["start_at"]
        ) == _clock(tuesday, 2)


@pytest.mark.asyncio
async def test_personal_preview_compares_capacity_without_writing(
    db_session: AsyncSession,
) -> None:
    group = ResourceGroup(name="Fictional team")
    person = PersonalResource(name="Example person", group_id=group.id)
    project = Project(
        name="Example project", start_date=date(2026, 6, 1), end_date=date(2026, 6, 5)
    )
    first_wp = WorkPackage(
        project_id=project.id,
        name="First",
        start_date=project.start_date,
        end_date=project.end_date,
    )
    second_wp = WorkPackage(
        project_id=project.id,
        name="Second",
        start_date=project.start_date,
        end_date=project.end_date,
    )
    original = Assignment(
        resource_id=person.id,
        resource_type=ResourceType.personal,
        work_package_id=first_wp.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        allocation_percent=60,
    )
    db_session.add_all(
        [group, project, WorkWeekProfile(name="Standard", is_default=True)]
    )
    await db_session.flush()
    db_session.add_all([person, first_wp, second_wp])
    await db_session.flush()
    db_session.add(original)
    await db_session.commit()

    result = await AssignmentPreviewService(db_session).preview(
        AssignmentPreviewRequest(
            resource_id=person.id,
            resource_type=ResourceType.personal,
            work_package_id=second_wp.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            allocation_percent=50,
        )
    )

    assert len(result.resources) == 1
    impact = result.resources[0]
    assert impact.resource_name == "Example person"
    assert impact.conflicts_before == []
    assert len(impact.conflicts_after) == 1
    assert len(impact.capacity_days) == 5
    assert impact.capacity_days[0].assigned_before_percent == 60
    assert impact.capacity_days[0].assigned_after_percent == pytest.approx(110)
    assert len((await db_session.execute(select(Assignment))).scalars().all()) == 1
    assert (await db_session.execute(select(Conflict))).scalars().all() == []
    assert not db_session.dirty and not db_session.new


@pytest.mark.asyncio
async def test_infrastructure_preview_reassigns_without_writing(
    db_session: AsyncSession,
) -> None:
    group = ResourceGroup(
        name="Fictional halls", resource_type=ResourceType.infrastructure
    )
    old = InfrastructureResource(name="Old hall", group_id=group.id)
    new = InfrastructureResource(name="New hall", group_id=group.id)
    project = Project(
        name="Example project", start_date=date(2026, 6, 1), end_date=date(2026, 6, 5)
    )
    wp = WorkPackage(
        project_id=project.id,
        name="First",
        start_date=project.start_date,
        end_date=project.end_date,
    )
    occupied_wp = WorkPackage(
        project_id=project.id,
        name="Second",
        start_date=project.start_date,
        end_date=project.end_date,
    )
    moving = Assignment(
        resource_id=old.id,
        resource_type=ResourceType.infrastructure,
        work_package_id=wp.id,
        start_at=local_wall_time_to_utc(datetime(2026, 6, 1, 8), planning_zone()),
        end_at=local_wall_time_to_utc(datetime(2026, 6, 1, 10), planning_zone()),
    )
    occupied = Assignment(
        resource_id=new.id,
        resource_type=ResourceType.infrastructure,
        work_package_id=occupied_wp.id,
        start_at=local_wall_time_to_utc(datetime(2026, 6, 1, 9), planning_zone()),
        end_at=local_wall_time_to_utc(datetime(2026, 6, 1, 11), planning_zone()),
    )
    db_session.add_all([group, project])
    await db_session.flush()
    db_session.add_all([old, new, wp, occupied_wp])
    await db_session.flush()
    db_session.add_all([moving, occupied])
    await db_session.commit()

    result = await AssignmentPreviewService(db_session).preview(
        AssignmentPreviewRequest(
            assignment_id=moving.id,
            resource_id=new.id,
            resource_type=ResourceType.infrastructure,
            work_package_id=wp.id,
            start_at=moving.start_at,
            end_at=moving.end_at,
        )
    )

    assert len(result.resources) == 2
    impacts = {item.resource_id: item for item in result.resources}
    assert impacts[old.id].conflicts_after == []
    assert impacts[new.id].conflicts_before == []
    assert len(impacts[new.id].conflicts_after) == 1
    assert all(item.capacity_days == [] for item in impacts.values())
    assert moving.resource_id == old.id
    assert len((await db_session.execute(select(Assignment))).scalars().all()) == 2
    assert (await db_session.execute(select(Conflict))).scalars().all() == []
    assert not db_session.dirty and not db_session.new
