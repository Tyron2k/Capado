"""Fictional planning data shared by domain regressions and browser workflows."""

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.models.assignment import Assignment
from app.models.calendar import InfrastructureAvailabilityWindow, WorkWeekProfile
from app.models.project import Project, WorkPackage
from app.models.resource import InfrastructureResource, PersonalResource, ResourceType
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.skill import (
    InfrastructureResourceSkill,
    PersonalResourceSkill,
    Skill,
    SkillAttribute,
)
from app.models.work_package_requirement import RequirementMode, WorkPackageRequirement
from app.services.time_zone import local_wall_time_to_utc, planning_zone

DAY = MONDAY = date(2099, 1, 5)
LAST_DAY = WEDNESDAY = MONDAY + timedelta(days=2)


def _clock(day, hour):
    return local_wall_time_to_utc(datetime.combine(day, time(hour)), planning_zone())


async def _seed_case(
    session,
    *,
    kind=ResourceType.personal,
    quantity=1,
    mode=RequirementMode.headcount,
    minimum_level=None,
    people=(),
):
    """Persist a small fictional requirement and the specified resource bookings."""
    if (
        await session.scalar(select(WorkWeekProfile).where(WorkWeekProfile.is_default))
        is None
    ):
        session.add(WorkWeekProfile(name="Fixture standard", is_default=True))
    group = ResourceGroup(name="Fixture team", resource_type=kind)
    skill = Skill(name="Fixture qualification", resource_type=kind.value)
    project = Project(name="Fixture project", start_date=DAY, end_date=LAST_DAY)
    session.add_all([group, skill, project])
    await session.flush()

    attribute = SkillAttribute(name="Fixture attribute", skill_id=skill.id)
    package = WorkPackage(
        name="Fixture package",
        project_id=project.id,
        start_date=DAY,
        end_date=LAST_DAY,
    )
    session.add_all([attribute, package])
    await session.flush()

    session.add(
        WorkPackageRequirement(
            work_package_id=package.id,
            skill_id=skill.id,
            skill_attribute_id=attribute.id,
            quantity=quantity,
            requirement_mode=mode,
            min_allocation_percent=100.0,
            min_level=minimum_level,
        )
    )

    bookings = []
    for index, person in enumerate(people):
        if kind == ResourceType.personal:
            resource = PersonalResource(
                name=f"Person {index}",
                group_id=group.id,
                is_active=person.get("active", True),
            )
        else:
            resource = InfrastructureResource(
                name=f"Machine {index}",
                group_id=group.id,
                is_active=person.get("active", True),
            )
        session.add(resource)
        await session.flush()

        if person.get("qualified", True):
            held = {
                "resource_id": resource.id,
                "skill_attribute_id": attribute.id,
                "level": person.get("level", 4),
                "valid_from": person.get("valid_from"),
                "valid_until": person.get("valid_until"),
            }
            if kind == ResourceType.personal:
                session.add(PersonalResourceSkill(**held))
            else:
                session.add(InfrastructureResourceSkill(**held))

        if kind == ResourceType.personal:
            booking = Assignment(
                resource_type=kind,
                resource_id=resource.id,
                work_package_id=package.id,
                start_date=person.get("start_date", DAY),
                end_date=person.get("end_date", LAST_DAY),
                allocation_percent=person.get("allocation", 100.0),
            )
        else:
            booking = Assignment(
                resource_type=kind,
                resource_id=resource.id,
                work_package_id=package.id,
                start_at=person.get("start_at", datetime(2099, 1, 5, 10, tzinfo=UTC)),
                end_at=person.get("end_at", datetime(2099, 1, 5, 12, tzinfo=UTC)),
            )
        session.add(booking)
        bookings.append(booking)

    await session.commit()
    return package, bookings


async def _seed_plan(session, *, windows=True):
    # Extend the existing personnel fixture rather than maintain a parallel seed.
    package, crew_bookings = await _seed_case(
        session,
        quantity=2,
        minimum_level=3,
        people=[{"level": 3, "valid_from": MONDAY, "valid_until": WEDNESDAY}] * 2,
    )
    assert (package.start_date, package.end_date) == (MONDAY, WEDNESDAY)
    people_by_id = {
        p.id: p
        for p in (
            await session.scalars(
                select(PersonalResource).where(
                    PersonalResource.id.in_([b.resource_id for b in crew_bookings])
                )
            )
        ).all()
    }
    people = [people_by_id[b.resource_id] for b in crew_bookings]
    qualifications = {
        q.resource_id: q
        for q in (
            await session.scalars(
                select(PersonalResourceSkill).where(
                    PersonalResourceSkill.resource_id.in_(people_by_id)
                )
            )
        ).all()
    }
    crew_qualifications = [qualifications[p.id] for p in people]
    crew_requirement = (
        await session.scalars(
            select(WorkPackageRequirement).where(
                WorkPackageRequirement.work_package_id == package.id
            )
        )
    ).one()
    profile = await session.scalar(
        select(WorkWeekProfile).where(WorkWeekProfile.is_default)
    )
    for weekday in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        setattr(profile, weekday + "_minutes", 480)
    profile.saturday_minutes = profile.sunday_minutes = 0
    site = Site(name="Fictional workshop")
    machine_group = ResourceGroup(
        name="Fictional machines", resource_type=ResourceType.infrastructure
    )
    machine_skill = Skill(
        name="Fictional lifting capability", resource_type="infrastructure"
    )
    session.add_all([site, machine_group, machine_skill])
    await session.flush()
    for person in people:
        person.site_id = site.id
    machine = InfrastructureResource(
        name="Fictional crane", group_id=machine_group.id, site_id=site.id
    )
    machine_attribute = SkillAttribute(
        name="Fictional assessed lifting", skill_id=machine_skill.id
    )
    session.add_all([machine, machine_attribute])
    await session.flush()
    machine_qualification = InfrastructureResourceSkill(
        resource_id=machine.id,
        skill_attribute_id=machine_attribute.id,
        level=3,
        valid_from=MONDAY,
        valid_until=WEDNESDAY,
    )
    machine_requirement = WorkPackageRequirement(
        work_package_id=package.id,
        skill_id=machine_skill.id,
        skill_attribute_id=machine_attribute.id,
        quantity=1,
        min_level=2,
    )
    machine_booking = Assignment(
        resource_type=ResourceType.infrastructure,
        resource_id=machine.id,
        work_package_id=package.id,
        start_at=_clock(MONDAY, 22),
        end_at=_clock(MONDAY + timedelta(days=1), 2),
    )
    session.add_all([machine_qualification, machine_requirement, machine_booking])
    if windows:
        session.add(
            InfrastructureAvailabilityWindow(
                resource_id=machine.id, weekday=0, start_time=time(22), end_time=time(6)
            )
        )
    await session.commit()
    return SimpleNamespace(
        package=package,
        people=people,
        machine=machine,
        site=site,
        crew_qualifications=crew_qualifications,
        machine_qualification=machine_qualification,
        crew_requirement=crew_requirement,
        crew_bookings=crew_bookings,
        machine_booking=machine_booking,
        resource_ids={person.id for person in people} | {machine.id},
    )
