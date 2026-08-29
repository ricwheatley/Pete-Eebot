"""Static dependency contracts for daily-summary ownership.

The graph parses every ``pete_e/**/*.py`` file with :mod:`ast`, expands
project ``import``/``from`` edges to known modules, recognizes constant
``importlib.import_module`` targets, and finds strongly connected components
with Tarjan's algorithm.
"""

from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "pete_e"
SUMMARY_CYCLE_MODULES = {
    "pete_e.application.orchestrator",
    "pete_e.application.sync",
    "pete_e.application.telegram_listener",
    "pete_e.application.workflows.daily_sync",
    "pete_e.cli.messenger",
    "pete_e.cli.telegram",
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    return ".".join(relative.parts)


def _resolve_from_module(
    *,
    source_module: str,
    imported_module: str | None,
    level: int,
) -> str:
    if level == 0:
        return imported_module or ""
    package_parts = source_module.rsplit(".", 1)[0].split(".")
    base_parts = package_parts[: len(package_parts) - level + 1]
    if imported_module:
        base_parts.append(imported_module)
    return ".".join(base_parts)


def _project_imports(
    path: Path,
    *,
    known_modules: set[str],
) -> set[str]:
    source_module = _module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name for alias in node.names if alias.name.startswith("pete_e")
            )
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from_module(
                source_module=source_module,
                imported_module=node.module,
                level=node.level,
            )
            if not base.startswith("pete_e"):
                continue
            for alias in node.names:
                candidate = f"{base}.{alias.name}"
                imports.add(candidate if candidate in known_modules else base)
        elif _is_constant_import_module_call(node):
            imports.add(node.args[0].value)
    return imports


def _is_constant_import_module_call(node: ast.AST) -> bool:
    return bool(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and node.args[0].value.startswith("pete_e")
    )


def _dependency_graph() -> dict[str, set[str]]:
    paths = sorted(PACKAGE_ROOT.rglob("*.py"))
    known_modules = {_module_name(path) for path in paths}
    return {
        _module_name(path): {
            imported
            for imported in _project_imports(path, known_modules=known_modules)
            if imported in known_modules
        }
        for path in paths
    }


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[set[str]]:
    next_index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low_links: dict[str, int] = {}
    components: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal next_index
        indices[node] = next_index
        low_links[node] = next_index
        next_index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                low_links[node] = min(low_links[node], low_links[target])
            elif target in on_stack:
                low_links[node] = min(low_links[node], indices[target])
        if low_links[node] != indices[node]:
            return
        component: set[str] = set()
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.add(target)
            if target == node:
                break
        components.append(component)

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return components


def test_application_summary_modules_do_not_import_cli_messenger() -> None:
    graph = _dependency_graph()
    summary_application_modules = {
        "pete_e.application.daily_summary",
        "pete_e.application.morning_report",
        "pete_e.application.orchestrator",
        "pete_e.application.telegram_listener",
        "pete_e.application.workflows.daily_sync",
    }

    assert all(
        "pete_e.cli.messenger" not in graph[module]
        for module in summary_application_modules
    )


def test_no_lazy_cli_messenger_reference_remains_in_application() -> None:
    offenders: list[str] = []
    for path in sorted((PACKAGE_ROOT / "application").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        if any(
            isinstance(node, ast.Constant) and node.value == "pete_e.cli.messenger"
            for node in ast.walk(tree)
        ):
            offenders.append(str(path.relative_to(PACKAGE_ROOT.parent)))

    assert offenders == []


def test_original_six_module_summary_component_is_gone() -> None:
    components = _strongly_connected_components(_dependency_graph())
    nontrivial = [component for component in components if len(component) > 1]

    assert all(component.isdisjoint(SUMMARY_CYCLE_MODULES) for component in nontrivial)
