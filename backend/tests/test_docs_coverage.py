"""The reference docs must keep up with the code, and this is what makes that mechanical.

Documentation here has drifted silently more than once: the in-app help kept describing a capacity model
that had been replaced, and data-model.md documented every table while missing 25 of their columns.
Nothing failed, because prose has no compiler.

WHAT THIS FILE GATES, and where each requirement lives:

- **Endpoints: in the code.** api.md no longer lists them. FastAPI generates the list, the request
  bodies and the responses from the decorators and serves them at /docs, so a hand-written copy could
  only be identical or wrong — and it was wrong: it told callers to send an absence reason the API had
  stopped accepting. The requirement moved to `summary` being present on every route, which is what
  makes the generated schema usable on its own.
- **Tables and their COLUMNS: in data-model.md.** The table-level check passed for a long time while
  columns were missing underneath it, which is why the column check exists.
- **Names api.md still uses: must exist.** The file names individual routes where semantics belong to
  one route, and those mentions can go stale.
- **Claims that something is ABSENT: must be accountable.** "Not yet implemented" is the one kind of
  sentence that goes stale without anybody touching it — shipping the feature is what makes it false,
  and the person shipping had no reason to look for it. Such a claim must sit in the omissions register
  or point at where it was resolved.

What none of this can tell: whether a sentence is TRUE. A false statement passes every test here, and
only a reader catches it. Treat a green run as "nothing is missing", never as "the docs are correct" —
the sixteen false statements found by reading this documentation were all found green.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlmodel import SQLModel

import app.models  # noqa: F401  — registers every table on SQLModel.metadata
from app.main import app

DOCS = Path(__file__).parent.parent.parent / "docs" / "reference"
API_DOC = (DOCS / "api.md").read_text(encoding="utf-8")
MODEL_DOC = (DOCS / "data-model.md").read_text(encoding="utf-8")


def _doc_key(path: str) -> str:
    """Reduce a route to how the docs write it: no /api prefix, no path parameters."""
    return path.removeprefix("/api").split("{", 1)[0].rstrip("/")


def _real_routes() -> set[str]:
    """Every /api path, taken from the generated OpenAPI schema.

    Not from app.routes: this FastAPI version wraps included routers in objects that do not expose
    their children, so walking that structure silently finds almost nothing.
    """
    return {path for path in app.openapi()["paths"] if path.startswith("/api")}


def _paths_named_in_prose() -> set[str]:
    """Paths api.md mentions, now that it no longer lists them.

    The file kept a handful of inline mentions — `GET /me/plan`, `PUT /users/{id}` — because the
    semantics being explained belong to a specific route. Those mentions can go stale, which is what
    the test below is for.
    """
    keys = {
        _doc_key("/api" + m.group(2))
        for m in re.finditer(
            r"(GET|POST|PUT|PATCH|DELETE)\s+`?(/[a-z0-9{}/_-]+)", API_DOC
        )
    }
    keys.discard("")
    return keys


def test_every_table_appears_in_the_data_model_reference():
    """A table nobody documented is a table the next person models from scratch."""
    missing = sorted(t for t in SQLModel.metadata.tables if t not in MODEL_DOC)
    assert not missing, (
        f"{len(missing)} table(s) missing from docs/reference/data-model.md:\n  "
        + "\n  ".join(missing)
    )


def _table_section(table_name: str) -> str:
    """The part of data-model.md that belongs to one table.

    From its heading up to the next heading of the same or higher level. Loose on the heading text,
    because the document uses several styles and this check is about columns.
    """
    pattern = re.compile(
        rf"^#{{2,4}}[^\n]*\b{re.escape(table_name)}\b.*?(?=^#{{2,4}} |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(MODEL_DOC)
    return match.group(0) if match else ""


#: Columns the document may describe as a RANGE rather than one row each, e.g.
#: "`monday_minutes` … `friday_minutes`". Seven near-identical rows would be noise, and the range says
#: more. Listed explicitly rather than pattern-matched, so a genuinely undocumented column cannot hide
#: behind a resemblance to one of these.
RANGE_DOCUMENTED = {
    "work_week_profiles": {
        "monday_minutes",
        "tuesday_minutes",
        "wednesday_minutes",
        "thursday_minutes",
        "friday_minutes",
        "saturday_minutes",
        "sunday_minutes",
    },
}


def test_every_column_appears_in_the_data_model_reference():
    """One level below the table check, and the level where drift actually happened.

    Measured before this test existed: all 31 tables were documented, and 25 columns were not — 15 of
    them on organization_settings, which had grown from a branding singleton into settings-plus-mail
    while its description still said "branding table". The table-level check passed the whole time,
    because the table was there. Presence of a heading says nothing about the rows underneath it.
    """
    missing: list[str] = []
    for table_name, table in sorted(SQLModel.metadata.tables.items()):
        section = _table_section(table_name)
        if not section:
            continue  # the table-level test above owns this failure
        allowed = RANGE_DOCUMENTED.get(table_name, set())
        for column in table.columns:
            if column.name in allowed:
                continue
            if not re.search(rf"\b{re.escape(column.name)}\b", section):
                missing.append(f"{table_name}.{column.name}")

    assert not missing, (
        f"{len(missing)} column(s) missing from docs/reference/data-model.md:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd a row to the table's section. If a set of near-identical columns is better written "
        "as a range, add them to RANGE_DOCUMENTED in this file with a reason."
    )


def test_every_endpoint_has_a_summary_in_the_generated_schema():
    """The endpoint documentation belongs in the code, where it cannot drift from the code.

    api.md used to list all 158 endpoints with descriptions — a second copy of what FastAPI already
    generates from the decorators and serves at /docs. A second copy can be wrong; the generated one
    cannot. So the requirement moved here: every endpoint must carry a `summary`, which is what makes
    the generated schema usable on its own.

    All 158 already complied when this was written, so the test starts by protecting rather than by
    demanding work.
    """
    missing = sorted(
        f"{method.upper()} {path}"
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api")
        for method, operation in operations.items()
        if method.upper() not in {"HEAD", "OPTIONS"}
        and not (operation.get("summary") or "").strip()
    )
    assert not missing, (
        f"{len(missing)} endpoint(s) without a summary:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd summary=... to the route decorator. That text is what /docs shows."
    )


def test_the_api_reference_names_no_endpoint_that_was_removed():
    """A reference to a route that no longer exists is worse than no reference.

    This one survived the shrink deliberately. api.md no longer LISTS endpoints — the generated schema
    does that — but it still names individual routes where the semantics it explains belong to one
    route. Those names can go stale, and a stale name in prose is exactly how this file came to tell
    callers to send an absence reason the API had stopped accepting.
    """
    real = {_doc_key(path) for path in _real_routes()}
    # Prose fragments would otherwise register as paths; require a documented key to look like a real
    # first path segment.
    stale = sorted(
        key
        for key in _paths_named_in_prose()
        if key not in real and re.fullmatch(r"/[a-z0-9-]+(/[a-z0-9-]+)*", key)
    )
    assert not stale, (
        f"{len(stale)} path(s) in api.md no longer exist:\n  " + "\n  ".join(stale)
    )


DOCS_ROOT = Path(__file__).parent.parent.parent / "docs"

#: The register whose whole job is to list what Capado deliberately does not do. A claim of absence
#: belongs here, where it sits next to every other one and gets re-read as a set.
OMISSION_REGISTER = "reference/known-limitations.md"

#: Heading that marks a section quoting superseded claims. See the note in the test below for why an
#: ADR is appended to rather than edited.
RESOLUTION_SECTION = re.compile(r"^#{2,3}\s+resolved since\b", re.IGNORECASE)

#: A statement that some capability is absent. Deliberately catches the whole temporal family: what
#: makes these dangerous is not the wording but the tense — they describe a moment, and nothing tells
#: the reader the moment has passed. The "until it exists" branch was added after a claim in ADR-005
#: escaped the first version of this pattern: it announced a suggestion strategy as pending long after
#: `_suggest_shift_into_window` shipped, and said so without using the word "not".
ABSENCE_CLAIM = re.compile(
    r"""
      not \s+ yet \s+ \w+          # not yet implemented / supported / converted / wired
    | (?:has|is|are|was|were) \s+ not \s+ yet
    | not \s+ (?:implemented|supported|solved|wired\ up)
    | \b un(?:solved|implemented|supported) \b
    | until \s+ (?:it|they|that|this) \s+ (?:exists?|lands?|ships?)
    | (?:once|when) \s+ (?:it|this|that) \s+ (?:exists|lands|ships)
    | \b (?:still|currently) \s+ (?:missing|absent|pending|outstanding) \b
    | noch \s+ nicht \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _offenders_in_block(relative: str, block: list[tuple[int, str]]) -> list[str]:
    """Absence claims in one markdown block, unless the block accounts for them.

    Module-level rather than a closure over the enclosing loop: a nested function capturing the loop
    variable binds it late, which is correct only as long as every call happens inside the same
    iteration — a property the next edit silently breaks.
    """
    if not block:
        return []
    if "resolved since" in " ".join(line for _, line in block).lower():
        return []
    return [
        f"{relative}:{number}: {line.strip()[:100]}"
        for number, line in block
        if ABSENCE_CLAIM.search(line)
    ]


def _accountable_absence_claims() -> list[str]:
    """Every absence claim in the docs that neither is registered nor points at its resolution.

    Scanning is per BLOCK, not per line, and that is not a detail: a markdown bullet wraps across
    several lines, so the claim and the pointer that accounts for it routinely sit on different ones.
    A line-wise version of this check rejected a bullet that did carry its pointer, two lines down.
    """
    offenders: list[str] = []
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        relative = path.relative_to(DOCS_ROOT).as_posix()
        if relative == OMISSION_REGISTER:
            continue

        inside_resolution_section = False
        block: list[tuple[int, str]] = []

        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.startswith("#"):
                offenders += _offenders_in_block(relative, block)
                block = []
                inside_resolution_section = bool(RESOLUTION_SECTION.match(line))
                continue
            if not line.strip():
                offenders += _offenders_in_block(relative, block)
                block = []
                continue
            if not inside_resolution_section:
                block.append((number, line))
        offenders += _offenders_in_block(relative, block)
    return offenders


def test_no_document_claims_a_capability_is_absent_without_being_accountable_for_it():
    """A claim that something is missing must be checkable, or it becomes a lie by standing still.

    This is the one failure mode the rest of this file cannot see, and it is not hypothetical. Two
    statements in conflict-detection.md read "not yet implemented" long after the code implemented
    them: availability-window violations were detected by `_detect_window_violations`, carrying the
    very `ConflictCause` discriminator the document said was still needed, and the suggestion service
    had been converted to working-time minutes while the document still warned it reasoned in
    percentages. Both were found by reading, and a reader who did not check would have believed a
    safety check was absent that was in fact running.

    The asymmetry is what justifies a gate. A claim that something EXISTS gets corrected the moment
    someone looks for it and it is not there. A claim that something does NOT exist is never
    contradicted by use — it just quietly stops being true when the feature lands, and the person who
    landed it had no reason to search the prose for a sentence predicting its absence.

    So an absence claim must take one of three accountable forms:

    1. It lives in ``reference/known-limitations.md``, the register of deliberate omissions, where the
       claims sit together and are re-read as a set rather than found by accident.
    2. Its own paragraph points at ``Resolved since``, which is how a historical record admits that a
       consequence it recorded no longer holds. Paragraph, not line: a wrapped bullet carries its
       pointer wherever it fits.
    3. It sits inside a ``## Resolved since`` section, quoting a superseded claim in order to retire it.

    Anything else fails here. The rule is about accountability, not vocabulary: rephrasing "not yet
    implemented" as "unsolved" does not escape it, because the tense is the defect.

    What this still cannot do is verify the claim. An entry in the register can be as stale as the two
    above were — the gate only guarantees there is one place to look.
    """
    offenders = _accountable_absence_claims()
    assert not offenders, (
        f"{len(offenders)} claim(s) that something is absent, with nothing tying them to the code:\n  "
        + "\n  ".join(offenders)
        + f"\n\nEither move the claim into {OMISSION_REGISTER}, or — if the thing now exists — say so "
        "in a 'Resolved since' section and point this line at it."
    )
