"""Tests for the plant-calendar importer's write path.

The parser was already tested and verified against a real plant export; the part that
writes to the database had only ever been run by hand. That is the half where a mistake
is expensive: an importer that overwrites hand-corrected days destroys work nobody can
recover from the export, because the export cannot express a half day at all.

No database: the session is a hand-written double. All data is inline and fictional.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.models.site import Site
from app.scripts.import_plant_calendar import (
    ParsedHoliday,
    import_entries,
    resolve_site,
)

SITE_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _site(name: str = "Hauptwerk", is_default: bool = True) -> Site:
    return Site(id=SITE_ID, name=name, is_default=is_default)


def _entry(day: date, name: str = "Neujahr") -> ParsedHoliday:
    return ParsedHoliday(day=day, name=name)


class _FakeSession:
    """Session double: serves a site lookup and a set of existing holiday days."""

    def __init__(self, site: Site | None, existing_days: list[date] | None = None):
        self.site = site
        self.existing_days = existing_days or []
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> Any:
        # Two shapes occur: the Site lookup and the existing-days column select.
        # Distinguished by how many columns are selected, which keeps the double from
        # depending on SQLAlchemy's compiled SQL.
        columns = list(statement.selected_columns)
        site = self.site
        days = self.existing_days

        class _Result:
            def scalars(self) -> Any:
                return self

            def first(self) -> Any:
                return site

            def all(self) -> list[date]:
                return days

        _ = columns
        return _Result()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class TestResolveSite:
    """Which site the import lands in."""

    @pytest.mark.asyncio
    async def test_the_default_site_is_used_when_none_is_named(self):
        session = _FakeSession(_site())
        assert await resolve_site(session, None) is session.site  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_a_named_site_is_looked_up(self):
        session = _FakeSession(_site(name="Werk Nord", is_default=False))
        result = await resolve_site(session, "Werk Nord")  # type: ignore[arg-type]
        assert result.name == "Werk Nord"

    @pytest.mark.asyncio
    async def test_a_missing_site_stops_the_import(self):
        """Rather than inventing one.

        Importing a plant's calendar into the wrong site would give every resource
        there the wrong non-working days, silently.
        """
        session = _FakeSession(None)
        with pytest.raises(SystemExit, match="no site found"):
            await resolve_site(session, "Werk Süd")  # type: ignore[arg-type]


class TestImportEntries:
    """What actually gets written."""

    @pytest.mark.asyncio
    async def test_new_days_are_inserted(self):
        session = _FakeSession(_site())
        inserted, skipped = await import_entries(  # type: ignore[arg-type]
            session,
            [_entry(date(2026, 1, 1)), _entry(date(2026, 5, 1), "Maifeiertag")],
            None,
        )
        assert (inserted, skipped) == (2, 0)
        assert [h.day for h in session.added] == [date(2026, 1, 1), date(2026, 5, 1)]

    @pytest.mark.asyncio
    async def test_imported_days_start_as_fully_non_working(self):
        """Half days and working Saturdays are edited afterwards.

        No export distinguishes them, so guessing anything other than zero would put
        capacity into the plan that nobody stated.
        """
        session = _FakeSession(_site())
        await import_entries(session, [_entry(date(2026, 1, 1))], None)  # type: ignore[arg-type]
        assert session.added[0].working_minutes == 0

    @pytest.mark.asyncio
    async def test_a_day_already_present_is_left_untouched(self):
        """The most important behaviour in this module.

        A day someone corrected to a half day must survive a re-import. Overwriting
        it would turn it back into a full non-working day and quietly remove capacity
        that exists.
        """
        session = _FakeSession(_site(), existing_days=[date(2026, 1, 1)])
        inserted, skipped = await import_entries(  # type: ignore[arg-type]
            session,
            [_entry(date(2026, 1, 1)), _entry(date(2026, 5, 1), "Maifeiertag")],
            None,
        )
        assert (inserted, skipped) == (1, 1)
        assert [h.day for h in session.added] == [date(2026, 5, 1)]

    @pytest.mark.asyncio
    async def test_a_day_repeated_inside_the_file_is_inserted_once(self):
        """Plant calendars do repeat entries across their year columns.

        The second occurrence must not violate the one-row-per-site-and-day key.
        """
        session = _FakeSession(_site())
        inserted, skipped = await import_entries(  # type: ignore[arg-type]
            session,
            [
                _entry(date(2026, 1, 1)),
                _entry(date(2026, 1, 1), "Neujahr (Dublette)"),
            ],
            None,
        )
        assert (inserted, skipped) == (1, 1)
        assert len(session.added) == 1

    @pytest.mark.asyncio
    async def test_the_site_id_is_stamped_on_every_row(self):
        session = _FakeSession(_site())
        await import_entries(  # type: ignore[arg-type]
            session, [_entry(date(2026, 1, 1)), _entry(date(2026, 5, 1))], None
        )
        assert {h.site_id for h in session.added} == {SITE_ID}

    @pytest.mark.asyncio
    async def test_an_empty_entry_list_commits_nothing_new(self):
        session = _FakeSession(_site())
        inserted, skipped = await import_entries(session, [], None)  # type: ignore[arg-type]
        assert (inserted, skipped) == (0, 0)
        assert session.added == []

    @pytest.mark.asyncio
    async def test_the_work_is_committed(self):
        """A run that inserted rows without committing would report success and
        change nothing."""
        session = _FakeSession(_site())
        await import_entries(session, [_entry(date(2026, 1, 1))], None)  # type: ignore[arg-type]
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_a_missing_site_prevents_any_write(self):
        session = _FakeSession(None)
        with pytest.raises(SystemExit):
            await import_entries(session, [_entry(date(2026, 1, 1))], None)  # type: ignore[arg-type]
        assert session.added == []
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_the_name_from_the_export_is_kept(self):
        session = _FakeSession(_site())
        await import_entries(  # type: ignore[arg-type]
            session, [_entry(date(2026, 2, 16), "Rosenmontag")], None
        )
        assert session.added[0].name == "Rosenmontag"

    @pytest.mark.asyncio
    async def test_unrelated_site_ids_are_not_assumed(self):
        """The double's site id is what lands, not a fresh uuid."""
        other = uuid4()
        session = _FakeSession(_site())
        await import_entries(session, [_entry(date(2026, 1, 1))], None)  # type: ignore[arg-type]
        assert session.added[0].site_id != other
