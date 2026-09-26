"""The shared resource importer, against a real schema.

WHY THESE ARE NOT DOUBLE-BASED TESTS

This subsystem was measured at 18% coverage (`common.py`, 273 statements) and it is the one that
writes data in BULK — a faulty import damages many rows at once, where a faulty read damages a
display. Its helpers were already unit-tested (`test_import_site.py`); the main path,
`_import_resources`, was not.

A recording double is the wrong instrument here and this repository has the measurement to prove it:
removing a `WHERE` filter from the erasure code — a bug that deletes every absence in the database —
left all 11 double-based tests green and was caught only by the two integration tests. An importer
that writes the WRONG rows looks identical to a correct one from the outside. So these tests read the
rows back.

WHAT SQLITE CANNOT PROVE HERE, and it matters more for this file than for any other

The importer resolves names **case-insensitively**, via `func.lower(...) == name.lower()` on the SQL
side. PostgreSQL and SQLite agree on `lower()` for ASCII and **disagree beyond it**: SQLite's built-in
`lower()` does not fold non-ASCII characters at all, so `lower('Ä')` stays `'Ä'` there while
PostgreSQL folds it under a UTF-8 collation.

The consequence for these tests, stated rather than papered over: a case test using ASCII names
(`müller` vs `MÜLLER` is NOT ascii-safe; `Mueller` vs `MUELLER` is) proves the mechanism works. A case
test on umlauts would pass or fail here for reasons that say nothing about production. The ASCII case
is therefore tested and the non-ASCII case is deliberately not — see `conftest.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.models.resource import PersonalResource
from app.models.resource_group import ResourceGroup
from app.models.site import Site
from app.models.skill import PersonalResourceSkill, Skill, SkillAttribute
from app.services.import_export.personnel import import_personnel

HEADER = ("Name", "Group", "Skill", "Attribute", "Site")


def _now() -> datetime:
    return datetime.now(UTC)


async def _count(session: AsyncSession, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return int((await session.execute(stmt)).scalar_one())


@pytest.fixture
async def group(db_session: AsyncSession) -> ResourceGroup:
    row = ResourceGroup(
        id=uuid4(),
        name="Lackierer",
        resource_type="personal",
        created_at=_now(),
        updated_at=_now(),
    )
    db_session.add(row)
    await db_session.commit()
    return row


class TestCreatingResources:
    async def test_a_new_person_is_created(self, db_session: AsyncSession, group):
        result = await import_personnel(
            db_session, [HEADER, ("Mueller", "Lackierer", "", "", "")]
        )
        assert result.created == 1
        assert await _count(db_session, PersonalResource, name="Mueller") == 1

    async def test_an_unknown_group_is_created_automatically(
        self, db_session: AsyncSession
    ):
        """Documented behaviour, and the reason the import is admin-only: a typo in this column adds
        to the catalogue silently rather than failing."""
        result = await import_personnel(
            db_session, [HEADER, ("Mueller", "Schlosser", "", "", "")]
        )
        assert result.created == 1
        assert await _count(db_session, ResourceGroup, name="Schlosser") == 1

    async def test_two_rows_for_one_person_create_one_person(
        self, db_session: AsyncSession, group
    ):
        """One row per skill assignment is the documented shape, so the name repeats."""
        rows = [
            HEADER,
            ("Mueller", "Lackierer", "Spritzen", "Typ A", ""),
            ("Mueller", "Lackierer", "Spritzen", "Typ B", ""),
        ]
        await import_personnel(db_session, rows)
        assert await _count(db_session, PersonalResource, name="Mueller") == 1
        assert await _count(db_session, SkillAttribute) == 2


class TestNotCreatingDuplicates:
    async def test_an_existing_person_is_not_created_twice(
        self, db_session: AsyncSession, group
    ):
        await import_personnel(
            db_session, [HEADER, ("Mueller", "Lackierer", "", "", "")]
        )
        result = await import_personnel(
            db_session, [HEADER, ("Mueller", "Lackierer", "", "", "")]
        )
        assert result.created == 0
        assert await _count(db_session, PersonalResource, name="Mueller") == 1

    async def test_matching_ignores_case(self, db_session: AsyncSession, group):
        """ASCII only, on purpose: see the module docstring on lower() across backends."""
        await import_personnel(
            db_session, [HEADER, ("Mueller", "Lackierer", "", "", "")]
        )
        result = await import_personnel(
            db_session, [HEADER, ("MUELLER", "LACKIERER", "", "", "")]
        )
        assert result.created == 0, "a case difference created a second person"
        assert await _count(db_session, PersonalResource) == 1

    async def test_the_same_skill_twice_creates_one_assignment(
        self, db_session: AsyncSession, group
    ):
        rows = [HEADER, ("Mueller", "Lackierer", "Spritzen", "Typ A", "")]
        await import_personnel(db_session, rows)
        await import_personnel(db_session, rows)
        assert await _count(db_session, PersonalResourceSkill) == 1
        assert await _count(db_session, Skill, name="Spritzen") == 1


class TestTheSiteColumn:
    async def test_a_known_site_is_assigned(self, db_session: AsyncSession, group):
        site = Site(
            id=uuid4(), name="Werk Ammendorf", is_active=True, created_at=_now()
        )
        db_session.add(site)
        await db_session.commit()

        await import_personnel(
            db_session, [HEADER, ("Mueller", "Lackierer", "", "", "Werk Ammendorf")]
        )
        person = (
            (
                await db_session.execute(
                    select(PersonalResource).where(PersonalResource.name == "Mueller")
                )
            )
            .scalars()
            .one()
        )
        assert person.site_id == site.id

    async def test_an_unknown_site_rejects_the_row_and_writes_nothing(
        self, db_session: AsyncSession, group
    ):
        """The one column that refuses instead of creating: a site owns the holiday calendar, so a
        typo would produce a plant with no holidays. The row must not land half-written."""
        result = await import_personnel(
            db_session, [HEADER, ("Mueller", "Lackierer", "", "", "Werk Amendorf")]
        )
        assert result.errors, "an unknown site did not produce an error"
        assert result.created == 0
        assert await _count(db_session, PersonalResource) == 0, (
            "the row was written anyway"
        )
        assert await _count(db_session, Site) == 0, (
            "a site was created despite the refusal"
        )

    async def test_a_missing_site_column_leaves_an_existing_assignment_alone(
        self, db_session: AsyncSession, group
    ):
        """Every file exported before the column existed has no Site header. Re-importing one must
        not unfile every person in it."""
        site = Site(
            id=uuid4(), name="Werk Ammendorf", is_active=True, created_at=_now()
        )
        db_session.add(site)
        await db_session.commit()
        await import_personnel(
            db_session, [HEADER, ("Mueller", "Lackierer", "", "", "Werk Ammendorf")]
        )

        await import_personnel(
            db_session,
            [("Name", "Group", "Skill", "Attribute"), ("Mueller", "Lackierer", "", "")],
        )
        person = (
            (
                await db_session.execute(
                    select(PersonalResource).where(PersonalResource.name == "Mueller")
                )
            )
            .scalars()
            .one()
        )
        assert person.site_id == site.id, (
            "the site was cleared by a file that never mentioned it"
        )


class TestRefusals:
    async def test_a_row_without_a_name_is_reported_and_skipped(
        self, db_session: AsyncSession, group
    ):
        result = await import_personnel(
            db_session, [HEADER, ("", "Lackierer", "", "", "")]
        )
        assert result.errors
        assert await _count(db_session, PersonalResource) == 0

    async def test_a_completely_empty_row_is_ignored_without_an_error(
        self, db_session: AsyncSession, group
    ):
        """Trailing blank rows are what a spreadsheet produces, not what a user meant."""
        result = await import_personnel(db_session, [HEADER, ("", "", "", "", "")])
        assert not result.errors
        assert result.created == 0

    async def test_a_skill_matrix_file_is_refused_by_shape(
        self, db_session: AsyncSession
    ):
        """The matrix export has its header on the second row and cannot be read back."""
        result = await import_personnel(
            db_session,
            [
                ("Personnel",),
                ("Name", "Group", "Spritzen"),
                ("Mueller", "Lackierer", "X"),
            ],
        )
        assert result.errors
        assert await _count(db_session, PersonalResource) == 0
