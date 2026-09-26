"""The project and template importers, against a real schema.

The two least-tested files in the product: `import_export/projects.py` at 8% of 207 statements and
`templates.py` at 10% of 151. Both write in bulk, so a mistake costs many rows at once.

THE ASYMMETRY WORTH PINNING

The resource importer AUTO-CREATES an unknown skill. These two REFUSE one — `import_projects` and
`import_templates` both report "Skill '…' not found" and skip the requirement. Same product, same
column name, opposite behaviour, and nothing in the file names says so.

That is defensible: a requirement naming a skill nobody has is a plan that cannot be staffed, whereas
a resource carrying a new skill is just a new skill. But it is exactly the kind of difference that gets
"fixed" into consistency by someone who has not read both, so it is asserted here rather than left to
a docstring.

Written against real rows for the reason recorded in `test_import_resources_integration.py`: a
recording double cannot see that a statement selected the WRONG rows, and this repository has the
measurement to prove it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.models.project import Project, WorkPackage
from app.models.skill import Skill, SkillAttribute
from app.models.work_package_requirement import WorkPackageRequirement
from app.services.import_export.projects import import_projects
from app.services.import_export.templates import import_templates

PROJECT_HEADER = (
    "Project",
    "Project Start",
    "Project End",
    "Work Package",
    "WP Start",
    "WP End",
    "Skill",
    "Attribute",
    "Quantity",
)
TEMPLATE_HEADER = ("Template", "Description", "Skill", "Attribute", "Quantity")


def _now() -> datetime:
    return datetime.now(UTC)


async def _count(session: AsyncSession, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return int((await session.execute(stmt)).scalar_one())


@pytest.fixture
async def welding(db_session: AsyncSession) -> Skill:
    """A skill that exists, plus one attribute — requirements can only name existing skills."""
    skill = Skill(
        id=uuid4(), name="Schweissen", resource_type="personal", created_at=_now()
    )
    db_session.add(skill)
    await db_session.flush()
    db_session.add(
        SkillAttribute(id=uuid4(), skill_id=skill.id, name="MIG", created_at=_now())
    )
    await db_session.commit()
    return skill


class TestImportingProjects:
    async def test_a_project_is_created_with_its_dates(self, db_session: AsyncSession):
        result = await import_projects(
            db_session, [PROJECT_HEADER, ("Werk 1", "2026-09-01", "2026-12-31")]
        )
        assert result.created == 1
        project = (
            (await db_session.execute(select(Project).where(Project.name == "Werk 1")))
            .scalars()
            .one()
        )
        assert project.start_date == date(2026, 9, 1)
        assert project.end_date == date(2026, 12, 31)

    async def test_re_importing_updates_the_dates_instead_of_duplicating(
        self, db_session: AsyncSession
    ):
        await import_projects(
            db_session, [PROJECT_HEADER, ("Werk 1", "2026-09-01", "2026-12-31")]
        )
        result = await import_projects(
            db_session, [PROJECT_HEADER, ("Werk 1", "2026-10-01", "2027-01-31")]
        )
        assert result.updated == 1
        assert result.created == 0
        assert await _count(db_session, Project) == 1
        project = (
            (await db_session.execute(select(Project).where(Project.name == "Werk 1")))
            .scalars()
            .one()
        )
        assert project.start_date == date(2026, 10, 1), "the update did not take"

    async def test_matching_a_project_ignores_case(self, db_session: AsyncSession):
        """ASCII only — see test_import_resources_integration.py on lower() across backends."""
        await import_projects(
            db_session, [PROJECT_HEADER, ("Werk 1", "2026-09-01", "2026-12-31")]
        )
        result = await import_projects(
            db_session, [PROJECT_HEADER, ("WERK 1", "2026-09-01", "2026-12-31")]
        )
        assert result.created == 0
        assert await _count(db_session, Project) == 1

    async def test_a_missing_date_is_refused_and_nothing_is_written(
        self, db_session: AsyncSession
    ):
        result = await import_projects(db_session, [PROJECT_HEADER, ("Werk 1", "", "")])
        assert result.errors
        assert await _count(db_session, Project) == 0

    async def test_an_unparseable_date_is_refused_rather_than_guessed(
        self, db_session: AsyncSession
    ):
        """01.09.2026 is what a German Excel writes, and it must fail loudly rather than land as
        some other day."""
        result = await import_projects(
            db_session, [PROJECT_HEADER, ("Werk 1", "01.09.2026", "31.12.2026")]
        )
        assert result.errors
        assert await _count(db_session, Project) == 0

    async def test_a_row_without_a_project_name_is_skipped_silently(
        self, db_session: AsyncSession
    ):
        """Trailing blank rows are what a spreadsheet produces, not what a user meant."""
        result = await import_projects(db_session, [PROJECT_HEADER, ("", "", "")])
        assert not result.errors
        assert await _count(db_session, Project) == 0


class TestWorkPackages:
    async def test_a_work_package_inherits_the_project_dates_when_its_own_are_empty(
        self, db_session: AsyncSession
    ):
        await import_projects(
            db_session,
            [PROJECT_HEADER, ("Werk 1", "2026-09-01", "2026-12-31", "Rahmen", "", "")],
        )
        wp = (
            (
                await db_session.execute(
                    select(WorkPackage).where(WorkPackage.name == "Rahmen")
                )
            )
            .scalars()
            .one()
        )
        assert wp.start_date == date(2026, 9, 1)
        assert wp.end_date == date(2026, 12, 31)

    async def test_its_own_dates_win_when_given(self, db_session: AsyncSession):
        await import_projects(
            db_session,
            [
                PROJECT_HEADER,
                (
                    "Werk 1",
                    "2026-09-01",
                    "2026-12-31",
                    "Rahmen",
                    "2026-10-05",
                    "2026-10-20",
                ),
            ],
        )
        wp = (
            (
                await db_session.execute(
                    select(WorkPackage).where(WorkPackage.name == "Rahmen")
                )
            )
            .scalars()
            .one()
        )
        assert wp.start_date == date(2026, 10, 5)


class TestRequirementsRefuseUnknownSkills:
    """The asymmetry: the resource importer creates a missing skill, these two refuse it."""

    async def test_a_requirement_with_a_known_skill_is_created(
        self, db_session: AsyncSession, welding
    ):
        result = await import_projects(
            db_session,
            [
                PROJECT_HEADER,
                (
                    "Werk 1",
                    "2026-09-01",
                    "2026-12-31",
                    "Rahmen",
                    "",
                    "",
                    "Schweissen",
                    "MIG",
                    "2",
                ),
            ],
        )
        assert not result.errors
        req = (await db_session.execute(select(WorkPackageRequirement))).scalars().one()
        assert req.quantity == 2

    async def test_the_quantity_defaults_to_one(
        self, db_session: AsyncSession, welding
    ):
        await import_projects(
            db_session,
            [
                PROJECT_HEADER,
                (
                    "Werk 1",
                    "2026-09-01",
                    "2026-12-31",
                    "Rahmen",
                    "",
                    "",
                    "Schweissen",
                    "MIG",
                    "",
                ),
            ],
        )
        req = (await db_session.execute(select(WorkPackageRequirement))).scalars().one()
        assert req.quantity == 1

    async def test_an_unknown_skill_is_reported_and_no_skill_is_created(
        self, db_session: AsyncSession
    ):
        result = await import_projects(
            db_session,
            [
                PROJECT_HEADER,
                (
                    "Werk 1",
                    "2026-09-01",
                    "2026-12-31",
                    "Rahmen",
                    "",
                    "",
                    "Zaubern",
                    "",
                    "1",
                ),
            ],
        )
        assert result.errors, "an unknown skill did not produce an error"
        assert await _count(db_session, Skill) == 0, (
            "the importer created the skill anyway"
        )
        assert await _count(db_session, WorkPackageRequirement) == 0

    async def test_the_project_still_lands_when_only_its_requirement_fails(
        self, db_session: AsyncSession
    ):
        """A partial refusal: the plan is worth keeping even when one requirement cannot resolve."""
        await import_projects(
            db_session,
            [
                PROJECT_HEADER,
                (
                    "Werk 1",
                    "2026-09-01",
                    "2026-12-31",
                    "Rahmen",
                    "",
                    "",
                    "Zaubern",
                    "",
                    "1",
                ),
            ],
        )
        assert await _count(db_session, Project, name="Werk 1") == 1


class TestImportingTemplates:
    async def test_a_template_is_created(self, db_session: AsyncSession):
        result = await import_templates(
            db_session,
            [TEMPLATE_HEADER, ("Standard-Rahmen", "Beschreibung", "", "", "")],
        )
        assert result.created == 1

    async def test_re_importing_updates_the_description(self, db_session: AsyncSession):
        await import_templates(
            db_session, [TEMPLATE_HEADER, ("Standard-Rahmen", "Alt", "", "", "")]
        )
        result = await import_templates(
            db_session, [TEMPLATE_HEADER, ("Standard-Rahmen", "Neu", "", "", "")]
        )
        assert result.updated == 1
        assert result.created == 0

    async def test_an_unknown_skill_is_reported_here_too(
        self, db_session: AsyncSession
    ):
        result = await import_templates(
            db_session, [TEMPLATE_HEADER, ("Standard-Rahmen", "", "Zaubern", "", "1")]
        )
        assert result.errors
        assert await _count(db_session, Skill) == 0

    async def test_a_requirement_with_a_known_skill_is_created(
        self, db_session: AsyncSession, welding
    ):
        result = await import_templates(
            db_session,
            [TEMPLATE_HEADER, ("Standard-Rahmen", "", "Schweissen", "MIG", "3")],
        )
        assert not result.errors
