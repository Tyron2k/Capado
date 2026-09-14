#!/usr/bin/env python3
"""Run mypy with ``attr-defined`` enabled and report only the findings that mean something.

WHY THIS EXISTS

``attr-defined`` is one of five error codes switched off for this project, and switching it off was
correct: SQLModel annotates a column as its Python type, so ``Model.field.in_(...)`` looks like
calling ``.in_()`` on a ``str``. That produces ~150 findings which are all the same handful of
SQLAlchemy column operators, and nobody reads a 150-line report.

It was also expensive. Three real bugs shipped in one afternoon (2026-08-26) in code that passed
ruff, mypy and tsc, all of them a missing or misplaced attribute:

- ``violation.shortfall_working_days`` — the field is ``working_days_short``
- ``work_package.committed_date`` — the field is ``committed_delivery_date`` AND lives on
  ``Project``, so an entire loop had the wrong shape
- ``assignment.start_datetime`` — the column is ``start_at``

Every one of those would have appeared here.

THE INSIGHT

The noise is a CLOSED SET of attribute names — the column operators below. Everything else that
``attr-defined`` reports is either a real missing attribute or a place where a variable is typed so
loosely (``object``, ``type``, the ``SQLModel`` base) that the checker has nothing to check. Both
are worth fixing, so filtering by name turns an unreadable report into a gate.

WHY NOT MIGRATE TO SQLALCHEMY 2.0 ``Mapped[]``

``docs/reference/known-limitations.md`` used to name that as the way out. It is wrong, and the doc
is corrected: this project uses SQLModel, which does not use ``Mapped[]`` annotations at all.
Getting them would mean replacing SQLModel with plain SQLAlchemy across 17 model files, 237 field
definitions and every query — a rearchitecture with no functional benefit. This script costs
nothing by comparison and closes the same gap.

USAGE

    ./.venv/bin/python scripts/check_attr_defined.py

This REPLACES the plain ``mypy`` call rather than running next to it: every normal mypy error is
reported unchanged, plus the attr-defined findings that survive the filter. Two runs of the same
checker would cost twice the CI minutes to learn the same thing.

Exits 1 with the findings listed when anything is reported.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# SQLAlchemy column operators and result-proxy members. Accessing one of these on what the checker
# believes is a plain ``str`` or ``date`` is the known false positive.
#
# Adding a name here SILENCES it permanently, so add only genuine SQLAlchemy API — never a name
# from this codebase, which is precisely what the check is for.
_OPERATORS = frozenset(
    {
        "in_",
        "notin_",
        "is_",
        "is_not",
        "isnot",
        "asc",
        "desc",
        "label",
        "like",
        "ilike",
        "notlike",
        "notilike",
        "between",
        "contains",
        "startswith",
        "endswith",
        "op",
        "any",
        "all",
        "distinct",
        "nulls_first",
        "nulls_last",
        "collate",
        "rowcount",
    }
)

_PATTERN = re.compile(r'has no attribute "([A-Za-z_][A-Za-z0-9_]*)"')


def main() -> int:
    """Run mypy and filter its output. Returns the intended exit code."""
    backend = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--enable-error-code",
            "attr-defined",
        ],
        cwd=backend,
        capture_output=True,
        text=True,
        check=False,
    )

    findings: list[str] = []
    for line in result.stdout.splitlines():
        if ": error:" not in line:
            continue
        if "[attr-defined]" in line:
            match = _PATTERN.search(line)
            # A finding whose shape this script does not recognise is REPORTED rather than
            # dropped. Silently ignoring an unparsed line would let a whole class of error hide
            # behind a formatting change in mypy's output.
            if match is not None and match.group(1) in _OPERATORS:
                continue
        # Every OTHER mypy error is reported unchanged. This script replaces the plain `mypy`
        # invocation rather than running alongside it — two runs of the same checker cost twice
        # the CI minutes to learn the same thing.
        findings.append(line)

    if not findings:
        print(
            "mypy: sauber, attr-defined eingeschlossen "
            f"({len(_OPERATORS)} SQLAlchemy-Operatoren gefiltert)"
        )
        return 0

    print(f"mypy: {len(findings)} Meldung(en):\n")
    for finding in findings:
        print(f"  {finding}")
    print(
        "\nEine attr-defined-Meldung ist entweder ein fehlendes Attribut — ein Tippfehler oder ein\n"
        "Feld am falschen Modell — oder eine Variable, die so lose typisiert ist (object,\n"
        "type, SQLModel), dass die Prüfung nichts prüfen kann. Beides gehört behoben, nicht\n"
        "in die Operator-Menge aufgenommen."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
