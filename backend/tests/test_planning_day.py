"""Calendar defaults must agree on Berlin's day even on a UTC server."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.project import Project, WorkPackage
from app.models.resource import PersonalResource
from app.models.skill import Skill
from app.models.work_package_requirement import WorkPackageRequirement
from app.routers import capacity, dashboard, digest, reports, team_week
from app.services import project_overview_service, time_zone, unmet_requirements_service
from app.services.digest_service import DigestBuilder

INSTANT = datetime(2026, 10, 25, 23, 30, tzinfo=UTC)
BERLIN_DAY = date(2026, 10, 26)


@pytest.fixture
def midnight(monkeypatch):
    class HostDate(date):
        @classmethod
        def today(cls):
            return INSTANT.date()  # Reproduce the backend running in UTC.

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return INSTANT if tz is None else INSTANT.astimezone(tz)

    monkeypatch.setattr(time_zone, "datetime", Clock)
    for module in (
        capacity,
        dashboard,
        digest,
        reports,
        team_week,
        project_overview_service,
        unmet_requirements_service,
    ):
        monkeypatch.setattr(module, "date", HostDate, raising=False)
        monkeypatch.setattr(module, "datetime", Clock, raising=False)


async def test_digest_uses_local_day(midnight, monkeypatch):
    builder = AsyncMock(side_effect=lambda _session, today: DigestBuilder(today=today))
    monkeypatch.setattr(digest, "build_digest", builder)
    result = await digest.get_digest(session=None, current_user=None)
    assert result.generated_for == BERLIN_DAY
    assert builder.call_args.args[1] == BERLIN_DAY


async def test_team_week_uses_local_monday(midnight, monkeypatch):
    build = AsyncMock(return_value=([], []))
    monkeypatch.setattr(team_week, "build_team_week", build)
    monkeypatch.setattr(team_week, "group_name", AsyncMock(return_value="Team"))
    await team_week.get_team_week(
        uuid4(), week_of=None, session=None, current_user=None
    )
    assert build.call_args.args[2] == BERLIN_DAY


async def test_dashboard_default_week_is_local(midnight, monkeypatch):
    service = SimpleNamespace(
        get_aggregated_utilization=AsyncMock(return_value=[]),
        get_projects_with_conflict_count=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(dashboard, "DashboardService", lambda _session: service)
    await dashboard.get_dashboard(
        start_date=None,
        end_date=None,
        department=None,
        location=None,
        project_ids=None,
        session=None,
        _current_user=None,
    )
    assert service.get_aggregated_utilization.call_args_list[0].args[1] == BERLIN_DAY


async def test_report_dates_use_local_day(midnight, monkeypatch):
    build = AsyncMock(return_value=b"test report")
    monkeypatch.setattr(reports, "build_utilization_report", build)
    result = await reports.utilization_report(
        start=None, end=None, group_id=None, session=None, current_user=None
    )
    assert build.call_args.args[1] == BERLIN_DAY
    assert str(BERLIN_DAY) in result.headers["content-disposition"]


async def test_capacity_detail_default_week_is_local(midnight, monkeypatch):
    person = PersonalResource(name="Person", group_id=uuid4())
    session = SimpleNamespace(get=AsyncMock(side_effect=[person, None]))
    service = SimpleNamespace(calculate_utilization=AsyncMock(return_value=[]))
    monkeypatch.setattr(capacity, "CapacityService", lambda _session: service)
    await capacity.get_resource_capacity_detail(
        person.id, start_date=None, end_date=None, session=session, _current_user=None
    )
    assert service.calculate_utilization.call_args.args[1] == BERLIN_DAY


async def test_overview_counts_local_active_packages(midnight, db_session):
    project = Project(name="Midnight", start_date=INSTANT.date(), end_date=BERLIN_DAY)
    db_session.add(project)
    await db_session.flush()
    db_session.add(
        WorkPackage(
            name="Monday",
            project_id=project.id,
            start_date=BERLIN_DAY,
            end_date=BERLIN_DAY,
        )
    )
    await db_session.commit()
    service = project_overview_service.ProjectOverviewService(db_session)
    result = await service.get_overview()
    assert result.projects[0].active_work_package_count == 1
    # Explicit historical input keeps its meaning.
    historic = await service.get_overview(today=INSTANT.date())
    assert historic.projects[0].active_work_package_count == 0


async def test_unmet_requirements_exclude_locally_expired_packages(
    midnight, db_session
):
    project = Project(name="Sunday", start_date=INSTANT.date(), end_date=INSTANT.date())
    skill = Skill(name="Browser skill")
    db_session.add_all([project, skill])
    await db_session.flush()
    package = WorkPackage(
        name="Expired",
        project_id=project.id,
        start_date=INSTANT.date(),
        end_date=INSTANT.date(),
    )
    db_session.add(package)
    await db_session.flush()
    db_session.add(
        WorkPackageRequirement(
            work_package_id=package.id, skill_id=skill.id, quantity=1
        )
    )
    await db_session.commit()
    assert await unmet_requirements_service.get_unmet_requirements(db_session) == []


async def test_capacity_overview_default_week_is_local(midnight, db_session):
    result = await capacity.get_capacity_overview(
        start_date=None,
        end_date=None,
        resource_type=None,
        department=None,
        project_ids=None,
        session=db_session,
        _current_user=None,
    )
    assert result.start_date == BERLIN_DAY
    assert result.end_date == BERLIN_DAY + timedelta(weeks=4)


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (datetime(2026, 1, 4, 23, 0, tzinfo=UTC), date(2026, 1, 5)),
        (datetime(2026, 7, 5, 22, 0, tzinfo=UTC), date(2026, 7, 6)),
        (datetime(2026, 3, 29, 0, 30, tzinfo=UTC), date(2026, 3, 29)),
        (datetime(2026, 3, 29, 1, 30, tzinfo=UTC), date(2026, 3, 29)),
        (datetime(2026, 3, 29, 22, 0, tzinfo=UTC), date(2026, 3, 30)),
        (datetime(2026, 10, 25, 0, 30, tzinfo=UTC), date(2026, 10, 25)),
        (datetime(2026, 10, 25, 1, 30, tzinfo=UTC), date(2026, 10, 25)),
        (INSTANT, BERLIN_DAY),
    ],
)
def test_planning_today_at_midnight_and_dst(instant, expected):
    assert time_zone.planning_today(now=instant) == expected
    assert instant.tzinfo == UTC


def test_planning_today_rejects_ambiguous_naive_clock():
    with pytest.raises(ValueError, match="offset"):
        time_zone.planning_today(now=datetime(2026, 10, 25, 2, 30))


def test_planning_today_does_not_use_host_timezone(midnight, monkeypatch):
    import os
    import time

    original = os.environ.get("TZ")
    try:
        for name in ("UTC", "America/Los_Angeles", "Asia/Tokyo"):
            monkeypatch.setenv("TZ", name)
            time.tzset()
            assert time_zone.planning_today() == BERLIN_DAY
    finally:
        if original is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original)
        time.tzset()


def test_report_default_clock_is_local(midnight, monkeypatch):
    from app.services.reports import workbook

    monkeypatch.setattr(workbook, "datetime", time_zone.datetime)
    assert "26.10.2026 00:30" in workbook.generated_subtitle("Test")
