"""Import a plant calendar export into the ``holidays`` table.

Usage (inside the backend container)::

    python -m app.scripts.import_plant_calendar /path/to/Werk_Kalender.csv
    python -m app.scripts.import_plant_calendar cal.csv --from-year 2026 --to-year 2030

The expected shape is the one plant calendars are actually maintained in: a
matrix with one **column per year** and one **row per holiday**, the last field
of each row holding the name.

    2007;2008;...;2036;
    1/1/07;1/1/08;...;1/1/36;Neujahr
    ;;1/2/09;...;;Brückentag
    2/19/07;2/4/08;...;2/25/36;Rosenmontag

Only month and day are read from a cell; the year comes from its column header.
That sidesteps two-digit year ambiguity entirely and means a typo in a cell's
year cannot silently move a holiday.

Why a table and not a holiday library: this file is the reason. A plant calendar
contains Rosenmontag and bridge days, which are not statutory everywhere in Germany,
and it omits days the plant does work. A library would report capacity that does
not exist (ADR-004).

Rows are written with ``working_minutes = 0``. Half days and designated working
Saturdays are edited afterwards, because no export distinguishes them.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import async_session_factory
from app.models.calendar import Holiday
from app.models.site import Site


@dataclass(frozen=True)
class ParsedHoliday:
    """One holiday on one date, as read from the export."""

    day: date
    name: str


def parse_plant_calendar(rows: list[list[str]]) -> list[ParsedHoliday]:
    """Turn the year-by-holiday matrix into flat (date, name) entries.

    The first row is the header and supplies the year for each column. A cell is
    read as ``month/day``; its year comes from the column, not from the cell.

    Malformed cells are skipped rather than raising: these exports are
    hand-maintained over decades and a single bad cell should not cost the whole
    import. Empty cells are normal — a bridge day exists only in some years.
    """
    if not rows:
        return []

    years: dict[int, int] = {}
    for index, field in enumerate(rows[0]):
        value = field.strip()
        if value.isdigit() and len(value) == 4:
            years[index] = int(value)

    entries: list[ParsedHoliday] = []
    seen: set[tuple[date, str]] = set()

    for row in rows[1:]:
        if not row:
            continue
        name = next((field.strip() for field in reversed(row) if field.strip()), "")
        # A row whose only content is its own name carries no dates.
        if not name:
            continue

        for index, field in enumerate(row):
            value = field.strip()
            if not value or index not in years:
                continue
            parts = value.split("/")
            if len(parts) < 2:
                continue
            try:
                month = int(parts[0])
                day_of_month = int(parts[1])
                day = date(years[index], month, day_of_month)
            except ValueError:
                continue

            key = (day, name)
            if key not in seen:
                seen.add(key)
                entries.append(ParsedHoliday(day=day, name=name))

    return sorted(entries, key=lambda e: (e.day, e.name))


def read_csv(path: Path) -> list[list[str]]:
    """Read a semicolon-delimited export, tolerating a UTF-8 BOM."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle, delimiter=";"))


async def resolve_site(session: AsyncSession, site_name: str | None) -> Site:
    """Find the site to import into.

    A named site is looked up by name; without one, the site flagged ``is_default``
    is used. Raises rather than inventing a site: importing a plant's calendar into
    the wrong site would silently give every resource there the wrong non-working
    days, which is worse than the import failing.
    """
    if site_name:
        statement = select(Site).where(Site.name == site_name)
    else:
        statement = select(Site).where(Site.is_default == True)  # noqa: E712
    site: Site | None = (await session.execute(statement)).scalars().first()
    if site is None:
        target = site_name or "the default site"
        raise SystemExit(f"no site found for {target}")
    return site


async def import_entries(
    session: AsyncSession, entries: list[ParsedHoliday], site_name: str | None
) -> tuple[int, int]:
    """Write parsed entries into the holidays table. Returns (inserted, skipped).

    Takes the session rather than opening one, so the insert path is testable with a
    session double — the same seam the services use. ``_import`` supplies the real
    session.

    A day already present for the site is left untouched. One row per site and date
    is the unique key, and a hand-corrected half day must survive a re-import: the
    export cannot express half days, so re-importing over one would silently turn it
    back into a full non-working day.

    A day repeated inside the same file is inserted once, because the seen-set is
    updated as rows are added. Plant calendars do repeat entries across their year
    columns, so this is the ordinary case rather than a defensive flourish.
    """
    site = await resolve_site(session, site_name)

    existing_statement = select(Holiday.day).where(Holiday.site_id == site.id)
    existing: set[date] = set(
        (await session.execute(existing_statement)).scalars().all()
    )

    now = datetime.now(UTC)
    inserted = 0
    skipped = 0
    for entry in entries:
        if entry.day in existing:
            skipped += 1
            continue
        session.add(
            Holiday(
                site_id=site.id,
                day=entry.day,
                name=entry.name,
                # Every imported day starts as fully non-working. Half days and
                # designated working Saturdays are edited afterwards, because no
                # export distinguishes them.
                working_minutes=0,
                created_at=now,
                updated_at=now,
            )
        )
        existing.add(entry.day)
        inserted += 1

    await session.commit()
    return inserted, skipped


async def _import(
    path: Path, site_name: str | None, from_year: int, to_year: int
) -> tuple[int, int, int]:
    """Insert parsed holidays for one site. Returns (parsed, inserted, skipped)."""
    entries = [
        entry
        for entry in parse_plant_calendar(read_csv(path))
        if from_year <= entry.day.year <= to_year
    ]

    async with async_session_factory() as session:
        inserted, skipped = await import_entries(session, entries, site_name)

    return len(entries), inserted, skipped


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the import."""
    parser = argparse.ArgumentParser(
        description="Import a plant calendar export into the holidays table."
    )
    parser.add_argument("csv_path", type=Path, help="Path to the calendar export")
    parser.add_argument(
        "--site",
        default=None,
        help="Site name to import into (default: the site flagged is_default)",
    )
    parser.add_argument("--from-year", type=int, default=date.today().year)
    parser.add_argument("--to-year", type=int, default=date.today().year + 5)
    args = parser.parse_args(argv)

    if not args.csv_path.is_file():
        raise SystemExit(f"not a file: {args.csv_path}")
    if args.to_year < args.from_year:
        raise SystemExit("--to-year must not be before --from-year")

    parsed, inserted, skipped = asyncio.run(
        _import(args.csv_path, args.site, args.from_year, args.to_year)
    )
    print(
        f"parsed {parsed} holiday entries for {args.from_year}-{args.to_year}, "
        f"inserted {inserted}, skipped {skipped} already present"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
