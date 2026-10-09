"""Prevent endpoints from committing after a committing service call.

Both router-owned and service-owned transactions are supported. The guard resolves
imported service modules/classes and local instances, including constructor aliases;
it complements database rollback tests rather than attempting a full call graph.
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


def _service_calls(node: ast.AST, tree: ast.AST) -> set[tuple[str, str]]:
    """Resolve module calls and methods on locally constructed service instances."""
    aliases: dict[str, str] = {}
    for imported in ast.walk(tree):
        if isinstance(imported, ast.ImportFrom) and imported.module:
            if imported.module.startswith("app.services."):
                for alias in imported.names:
                    aliases[alias.asname or alias.name] = imported.module.split(".")[-1]
            elif imported.module == "app.services":
                for alias in imported.names:
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(imported, ast.Import):
            for alias in imported.names:
                if alias.name.startswith("app.services.") and alias.asname:
                    aliases[alias.asname] = alias.name.split(".")[-1]

    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign | ast.AnnAssign):
            value = sub.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                module = aliases.get(value.func.id)
                targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                if module:
                    for target in targets:
                        if isinstance(target, ast.Name):
                            aliases[target.id] = module

    calls: set[tuple[str, str]] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            receiver = sub.func.value
            if isinstance(receiver, ast.Call):
                receiver = receiver.func
            if isinstance(receiver, ast.Name) and receiver.id in aliases:
                calls.add((aliases[receiver.id], sub.func.attr))
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
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name, node in _functions(path).items():
            if not _commits(node):
                continue
            overlap = _service_calls(node, tree) & committing_services
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


def test_instance_and_module_aliases_are_resolved():
    tree = ast.parse("""
from app.services.project_service import ProjectService as Projects
from app.services import resource_service as resources
async def create(session):
    service = Projects(session)
    await service.create()
    await Projects(session).delete()
    await resources.update_resource()
    await session.commit()
""")
    node = tree.body[-1]
    assert _commits(node)
    assert _service_calls(node, tree) == {
        ("project_service", "create"),
        ("project_service", "delete"),
        ("resource_service", "update_resource"),
    }
