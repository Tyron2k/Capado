"""Mixed-type replacements and current overnight resolutions against real rows."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.assignment import Assignment
from app.models.calendar import InfrastructureAvailabilityWindow
from app.models.conflict import Conflict
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.skill import InfrastructureResourceSkill, PersonalResourceSkill
from app.schemas.assignment import AssignmentPreviewRequest
from app.services.assignment_preview import AssignmentPreviewService
from app.services.assignment_service import AssignmentService
from app.services.conflict_service import ConflictService
from app.services.conflict_suggestion_service import ConflictSuggestionService
from tests.planning_reference import MONDAY, WEDNESDAY, _clock, _seed_plan


@pytest.mark.parametrize("kind", [ResourceType.personal, ResourceType.infrastructure])
async def test_replacement_keeps_type_and_previews_then_applies(db_session, kind):
    plan = await _seed_plan(db_session)
    original = (
        plan.crew_bookings[0] if kind == ResourceType.personal else plan.machine_booking
    )
    model = (
        PersonalResource if kind == ResourceType.personal else InfrastructureResource
    )
    qualification_model = (
        PersonalResourceSkill
        if kind == ResourceType.personal
        else InfrastructureResourceSkill
    )
    group = (
        plan.people[0].group_id
        if kind == ResourceType.personal
        else plan.machine.group_id
    )
    attribute = (
        plan.crew_qualifications[0]
        if kind == ResourceType.personal
        else plan.machine_qualification
    ).skill_attribute_id
    replacement = model(name="Qualified replacement", group_id=group)
    db_session.add(replacement)
    await db_session.flush()
    db_session.add(
        qualification_model(
            resource_id=replacement.id, skill_attribute_id=attribute, level=3
        )
    )
    await db_session.commit()

    suggestions = await ConflictSuggestionService(
        db_session
    ).get_assignment_suggestions(original.id, alternatives_only=True)
    assert [s.target_resource_id for s in suggestions] == [replacement.id]
    assert all(
        s.type == "swap_resource" and s.assignment_id == original.id
        for s in suggestions
    )
    assert not db_session.new and not db_session.dirty
    assert (await db_session.scalars(select(Conflict))).all() == []
    preview = await AssignmentPreviewService(db_session).preview(
        AssignmentPreviewRequest(
            assignment_id=original.id,
            resource_id=replacement.id,
            resource_type=kind,
            work_package_id=original.work_package_id,
            start_date=original.start_date,
            end_date=original.end_date,
            allocation_percent=original.allocation_percent,
            start_at=original.start_at,
            end_at=original.end_at,
        )
    )
    assert all(not r.conflicts_after for r in preview.resources)
    assert original.resource_id != replacement.id
    updated, _ = await AssignmentService(db_session).update(
        original.id, resource_id=replacement.id
    )
    assert updated.resource_id == replacement.id and updated.resource_type == kind


@pytest.mark.parametrize(
    "invalid", ["low_level", "expired", "busy", "closed", "inactive"]
)
async def test_infrastructure_alternatives_require_valid_qualified_free_interval(
    db_session, invalid
):
    from datetime import time

    plan = await _seed_plan(db_session)
    candidate = InfrastructureResource(
        name="Invalid replacement",
        group_id=plan.machine.group_id,
        is_active=invalid != "inactive",
    )
    db_session.add(candidate)
    await db_session.flush()
    db_session.add(
        InfrastructureResourceSkill(
            resource_id=candidate.id,
            skill_attribute_id=plan.machine_qualification.skill_attribute_id,
            level=1 if invalid == "low_level" else 3,
            valid_until=MONDAY if invalid == "expired" else None,
        )
    )
    if invalid == "busy":
        db_session.add(
            Assignment(
                resource_id=candidate.id,
                resource_type=ResourceType.infrastructure,
                work_package_id=plan.package.id,
                start_at=plan.machine_booking.start_at + timedelta(hours=1),
                end_at=plan.machine_booking.end_at + timedelta(hours=1),
            )
        )
    if invalid == "closed":
        db_session.add(
            InfrastructureAvailabilityWindow(
                resource_id=candidate.id,
                weekday=0,
                start_time=time(6),
                end_time=time(14),
            )
        )
    await db_session.commit()
    result = await ConflictSuggestionService(db_session).get_assignment_suggestions(
        plan.machine_booking.id, alternatives_only=True
    )
    assert result == []


async def test_overnight_window_search_moves_to_another_day_without_saved_conflicts(
    db_session,
):
    plan = await _seed_plan(db_session)
    booking = plan.machine_booking
    booking.start_at, booking.end_at = (
        _clock(WEDNESDAY, 21),
        _clock(WEDNESDAY + timedelta(days=1), 1),
    )
    await db_session.commit()
    suggestions = await ConflictSuggestionService(
        db_session
    ).get_assignment_suggestions(booking.id)
    (shift,) = [s for s in suggestions if s.type == "shift_into_window"]
    assert shift.new_start_at == _clock(MONDAY + timedelta(days=1), 2)
    assert shift.new_end_at == _clock(MONDAY + timedelta(days=1), 6)
    assert shift.new_end_at - shift.new_start_at == booking.end_at - booking.start_at
    assert not db_session.new and not db_session.dirty
    assert (await db_session.scalars(select(Conflict))).all() == []
    result = await AssignmentPreviewService(db_session).preview(
        AssignmentPreviewRequest(
            assignment_id=booking.id,
            resource_id=booking.resource_id,
            resource_type=booking.resource_type,
            work_package_id=booking.work_package_id,
            start_at=shift.new_start_at,
            end_at=shift.new_end_at,
        )
    )
    assert result.resources[0].conflicts_before
    assert result.resources[0].conflicts_after == []


async def test_window_search_joins_midnight_spans_and_subtracts_competing_bookings(
    db_session,
):
    plan = await _seed_plan(db_session)
    booking = plan.machine_booking
    booking.start_at, booking.end_at = (
        _clock(MONDAY, 20),
        _clock(MONDAY + timedelta(days=1), 0),
    )
    other = Assignment(
        resource_id=booking.resource_id,
        resource_type=booking.resource_type,
        work_package_id=booking.work_package_id,
        start_at=_clock(MONDAY + timedelta(days=1), 2),
        end_at=_clock(MONDAY + timedelta(days=1), 6),
    )
    db_session.add(other)
    await db_session.commit()
    suggestions = await ConflictSuggestionService(
        db_session
    ).get_assignment_suggestions(booking.id)
    (shift,) = [s for s in suggestions if s.type == "shift_into_window"]
    assert (shift.new_start_at, shift.new_end_at) == (
        _clock(MONDAY, 22),
        _clock(MONDAY + timedelta(days=1), 2),
    )
    booking.start_at, booking.end_at = shift.new_start_at, shift.new_end_at
    assert (
        await ConflictService(db_session).calculate_periods(booking.resource_id) == []
    )


async def test_window_search_does_not_invent_a_slot_outside_package(db_session):
    plan = await _seed_plan(db_session)
    booking = plan.machine_booking
    plan.package.start_date = WEDNESDAY
    booking.start_at, booking.end_at = (
        _clock(WEDNESDAY, 21),
        _clock(WEDNESDAY + timedelta(days=1), 1),
    )
    await db_session.commit()
    assert (
        await ConflictSuggestionService(db_session).get_assignment_suggestions(
            booking.id
        )
        == []
    )


async def test_personnel_replacement_cannot_hide_a_day_without_calendar_supply(
    db_session,
):
    from app.models.calendar import Holiday

    plan = await _seed_plan(db_session)
    candidate = PersonalResource(
        name="Closed-site candidate",
        group_id=plan.people[0].group_id,
        site_id=plan.site.id,
    )
    db_session.add(candidate)
    await db_session.flush()
    db_session.add_all(
        [
            PersonalResourceSkill(
                resource_id=candidate.id,
                skill_attribute_id=plan.crew_qualifications[0].skill_attribute_id,
                level=3,
            ),
            Holiday(
                site_id=plan.site.id, day=WEDNESDAY, name="Closure", working_minutes=0
            ),
        ]
    )
    await db_session.commit()
    assert (
        await ConflictSuggestionService(db_session).get_assignment_suggestions(
            plan.crew_bookings[0].id, alternatives_only=True
        )
        == []
    )


async def test_live_suggestions_bound_competing_history_without_mutating_it(
    db_session, monkeypatch
):
    plan = await _seed_plan(db_session)
    history = Assignment(
        resource_id=plan.people[0].id,
        resource_type=ResourceType.personal,
        work_package_id=plan.package.id,
        start_date=MONDAY - timedelta(days=10000),
        end_date=WEDNESDAY + timedelta(days=10000),
        allocation_percent=50,
    )
    db_session.add(history)
    await db_session.commit()
    from app.services.working_time_service import WorkingTimeService

    original = WorkingTimeService.prepare

    async def bounded(self, resource_ids, start, end):
        assert (end - start).days <= 365
        return await original(self, resource_ids, start, end)

    monkeypatch.setattr(WorkingTimeService, "prepare", bounded)
    result = await ConflictSuggestionService(db_session).get_assignment_suggestions(
        plan.crew_bookings[0].id
    )
    assert result
    assert history.start_date == MONDAY - timedelta(days=10000)
    assert not db_session.new and not db_session.dirty
