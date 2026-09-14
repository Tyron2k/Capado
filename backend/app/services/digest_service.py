"""Load what the digest needs, in as few queries as the shape allows.

Separate from :mod:`app.services.digest_collector` on purpose: the collector is pure and
testable, this is the part that talks to the database. Keeping them apart is what lets every
suppression and severity rule be tested without a fixture, and it is also what makes this
file boring — it loads rows and hands them over, it decides nothing.

One deliberate cost: the digest reads the whole open plan, so it is the most expensive read
in the application. It is not on a hot path (a person opens it, or a nightly job calls it),
and the alternative — recomputing per project and merging — would repeat the calendar setup
once per project, which is the expensive part.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.organization_settings import OrganizationSettings
from app.models.project import Project, WorkPackage
from app.models.resource import PersonalResource
from app.models.skill import PersonalResourceSkill, Skill, SkillAttribute
from app.services.digest import DigestBuilder, DigestThresholds
from app.services.digest_collector import (
    CommitmentRecord,
    DependencyRecord,
    QualificationRecord,
    UncoveredRequirement,
    collect,
)
from app.services.qualification import HeldQualification
from app.services.unmet_requirements_service import get_unmet_requirements
from app.services.work_package_dependency_service import WorkPackageDependencyService
from app.services.working_time_service import WorkingTimeService

# Sentinel resource for calendar questions that are about the plant, not a person. The
# digest asks "does the plant work on this day", the same question the project overview
# asks, and for the same reason: a lead time is a property of a process.
_NO_RESOURCE = UUID("00000000-0000-0000-0000-000000000000")


async def thresholds_from_settings(session: AsyncSession) -> DigestThresholds:
    """Read the configured thresholds, falling back to the defaults.

    Falls back rather than failing when no settings row exists yet: a fresh install should
    produce a useful digest before anybody visits the settings page.
    """
    result = await session.execute(select(OrganizationSettings).limit(1))
    settings = result.scalars().first()
    if settings is None:
        return DigestThresholds()
    return DigestThresholds(
        horizon_days=settings.digest_horizon_days,
        critical_days=settings.digest_critical_days,
        warning_days=settings.digest_warning_days,
        max_findings=settings.digest_max_findings,
    )


async def _load_qualifications(session: AsyncSession) -> list[QualificationRecord]:
    """Every personal qualification that has an expiry date.

    Filtered in SQL rather than in Python: qualifications without an expiry are the
    majority and can never produce a finding, so loading them would mean reading the whole
    join to discard most of it.
    """
    statement = (
        select(PersonalResourceSkill, PersonalResource, SkillAttribute, Skill)
        .join(
            PersonalResource, PersonalResourceSkill.resource_id == PersonalResource.id
        )
        .join(
            SkillAttribute,
            PersonalResourceSkill.skill_attribute_id == SkillAttribute.id,
        )
        .join(Skill, SkillAttribute.skill_id == Skill.id)
        .where(PersonalResourceSkill.valid_until.is_not(None))
    )
    result = await session.execute(statement)
    return [
        QualificationRecord(
            resource_id=resource.id,
            resource_name=resource.name,
            skill_label=f"{skill.name} {attribute.name}".strip(),
            qualification=HeldQualification(
                valid_from=assignment.valid_from,
                valid_until=assignment.valid_until,
                level=assignment.level,
            ),
        )
        for assignment, resource, attribute, skill in result.all()
    ]


async def build_digest(session: AsyncSession, today: date) -> DigestBuilder:
    """Assemble the digest for the whole open plan."""
    thresholds = await thresholds_from_settings(session)

    projects = (await session.execute(select(Project))).scalars().all()
    qualifications = await _load_qualifications(session)

    if not projects:
        # No plan, but qualifications still expire. Returning early with an empty digest
        # would hide a lapsed certificate just because no project is open.
        return collect(
            today=today,
            is_working_day=lambda _day: True,
            qualifications=qualifications,
            commitments=[],
            dependencies=[],
            uncovered=[],
            thresholds=thresholds,
        )

    work_packages = (await session.execute(select(WorkPackage))).scalars().all()

    # One calendar for the whole digest, spanning everything it will ask about. Preparing
    # per project would repeat this setup, which is the expensive part of the read.
    working_time = WorkingTimeService(session)
    span_start = min(p.start_date for p in projects)
    span_end = max(
        max((wp.end_date for wp in work_packages), default=span_start),
        max(p.end_date for p in projects),
    )
    await working_time.prepare([], span_start, span_end)

    def _is_working_day(day: date) -> bool:
        """Whether the plant works on this date, per the default profile."""
        profile = working_time.profile_for(_NO_RESOURCE, day)
        if profile is None:
            return False
        return profile.minutes_for_weekday(day.weekday()) > 0

    wp_by_id = {wp.id: wp for wp in work_packages}
    project_of_wp = {wp.id: wp.project_id for wp in work_packages}

    commitments = [
        CommitmentRecord(
            project_id=project.id,
            label=project.name,
            committed=project.committed_delivery_date,
            planned_end=project.end_date,
            # derived_end comes from recorded lead times, which the project overview
            # computes per project from its templates. Passing None here means the check
            # reports only the breach visible in the dates and never a hidden one — the
            # digest under-reports rather than inventing a shortfall it did not measure.
            derived_end=None,
        )
        for project in projects
        if project.committed_delivery_date is not None
    ]

    dependency_service = WorkPackageDependencyService(session)
    dependencies: list[DependencyRecord] = []
    for project in projects:
        for edge in await dependency_service.edges_for_project(project.id):
            predecessor = wp_by_id.get(edge.predecessor_id)
            successor = wp_by_id.get(edge.successor_id)
            if predecessor is None or successor is None:
                # A dangling edge is a data problem, not a scheduling one. Reporting it
                # here would put it in front of a planner who cannot act on it.
                continue
            dependencies.append(
                DependencyRecord(
                    edge=edge,
                    predecessor_label=predecessor.name,
                    successor_label=successor.name,
                    successor_id=successor.id,
                    project_id=project_of_wp.get(successor.id, project.id),
                    predecessor_end=predecessor.end_date,
                    successor_start=successor.start_date,
                )
            )

    # Requirements nobody covers. get_unmet_requirements already loads the whole plan in bulk
    # and returns work package, project, dates and the gap — an earlier note in this file
    # claimed it had no batched form and left this out, which was simply wrong.
    #
    # It also computes up to five suggested resources per requirement, which the digest does
    # not use. Accepted rather than duplicating the detection to avoid it: one implementation
    # that does slightly too much beats two that can disagree about what is uncovered.
    uncovered = [
        UncoveredRequirement(
            work_package_id=unmet.work_package_id,
            project_id=unmet.project_id,
            label=unmet.work_package_name,
            skill_label=(
                f"{unmet.skill_name} {unmet.attribute_name}".strip()
                if unmet.attribute_name
                else unmet.skill_name
            ),
            # The work package's START is when the gap bites: that is the day somebody was
            # supposed to begin and there is nobody to do it. Its end date would report the
            # problem after the work should already have been finished.
            needed_by=unmet.start_date,
        )
        for unmet in await get_unmet_requirements(session)
    ]

    return collect(
        today=today,
        is_working_day=_is_working_day,
        qualifications=qualifications,
        commitments=commitments,
        dependencies=dependencies,
        uncovered=uncovered,
        thresholds=thresholds,
    )
