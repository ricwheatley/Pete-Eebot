"""Dependency-direction checks for the morning-report application operation."""

from __future__ import annotations

import ast
from pathlib import Path


def test_morning_report_operation_has_no_framework_or_adapter_imports() -> None:
    module_path = (
        Path(__file__).parents[2] / "pete_e" / "application" / "morning_report.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "pete_e.api",
        "pete_e.api_routes",
        "pete_e.cli",
        "pete_e.infrastructure",
        "fastapi",
        "starlette",
    )
    assert not {
        name
        for name in imported
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    }

    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert names.isdisjoint({"Request", "HTTPException", "ApplicationJobService"})
