"""One request path commits in exactly one layer.

WHY THIS IS A TEST AND NOT A REFACTOR

An architecture review counted 67 ``session.commit()`` calls across 19 service modules and 29 across
9 router modules and graded that a blocker: two layers committing means a router could commit after a
service already had, and a failure between the two would leave a state no code intended and no
rollback could reach.

Then the claim was checked, twice, with two different parsers. **No function in any router both
commits and calls a committing service function.** The double-commit path does not exist. The count
was real and the conclusion was wrong.

What is actually true is narrower and worth keeping: the codebase uses BOTH ownership patterns.

- Service-owned: ``resources``, ``projects``, ``work_packages`` — the router delegates and the
  service commits.
- Router-owned: ``templates``, ``customers``, ``work_package_requirements``, ``users``, ``auth``,
  resource *groups* — there is no service at all, and the router persists inline.

Neither is wrong on its own. What would be wrong is a single endpoint doing both, and nothing prevents
someone from writing one — the two patterns sit side by side in the same directory, so mixing them is
the natural mistake rather than a careless one. Refactoring 96 call sites would fix nothing that is
broken today; this test makes the defect impossible to introduce tomorrow, which is what the finding
actually warranted.

HOW IT DECIDES

Per-FUNCTION, not per-module, and that distinction is the whole reason it can be strict. A
module-level check would flag ``resources.py``, which legitimately commits for resource *groups* while
also calling read-only functions of ``resource_service`` — a module that commits elsewhere. Only the
functions that actually commit count.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).parent.parent
ROUTERS = BACKEND / "app" / "routers"
SERVICES = BACKEND / "app" / "services"


def _commits(node: ast.AST) -> bool:
    """True when this function body contains a ``session.commit()`` call."""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "commit"
        ):
            return True
    return False


def _functions(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out[node.name] = node
    return out


def _committing_service_functions() -> set[tuple[str, str]]:
    """``(module, function)`` for every service function that commits."""
    found: set[tuple[str, str]] = set()
    for path in sorted(SERVICES.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        module = path.stem
        for name, node in _functions(path).items():
            if _commits(node):
                found.add((module, name))
    return found


def _service_calls(node: ast.AST) -> set[tuple[str, str]]:
    """``(module, function)`` pairs this function calls as ``<module>.<function>(...)``."""
    calls: set[tuple[str, str]] = set()
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and isinstance(sub.func.value, ast.Name)
        ):
            calls.add((sub.func.value.id, sub.func.attr))
    return calls


def test_no_endpoint_commits_in_two_layers():
    """A function that commits must not also call a service function that commits.

    The failure this forbids is silent by construction: both writes succeed in the happy path, and
    only an error arriving between them reveals that the first one can no longer be rolled back. It
    is therefore exactly the kind of defect that reaches production and cannot be reproduced there.
    """
    committing_services = _committing_service_functions()
    offenders: list[str] = []

    for path in sorted(ROUTERS.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        for name, node in _functions(path).items():
            if not _commits(node):
                continue
            overlap = _service_calls(node) & committing_services
            if overlap:
                calls = ", ".join(f"{m}.{f}" for m, f in sorted(overlap))
                offenders.append(
                    f"{path.name}:{node.lineno} {name}() commits AND calls {calls}"
                )

    assert not offenders, (
        "A request path must commit in exactly one layer. These commit themselves AND delegate to a "
        "service that commits:\n  " + "\n  ".join(offenders) + "\n\n"
        "Either move the whole write into the service, or stop the service from committing and let "
        "the router own the unit of work. Do not leave both."
    )


def test_the_check_can_actually_see_a_committing_service():
    """Guard against the guard passing because it found nothing to compare against.

    A set-intersection test is vacuously green when either side is empty. This repository has service
    functions that commit; if this assertion ever fails, the AST walk above stopped working and the
    real test became decorative — which is worse than not having it.
    """
    committing = _committing_service_functions()
    assert len(committing) > 10, (
        f"Expected many committing service functions, found {len(committing)}. The detection is "
        "broken, so test_no_endpoint_commits_in_two_layers is passing without checking anything."
    )
