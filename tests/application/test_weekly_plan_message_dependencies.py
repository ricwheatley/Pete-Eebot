"""Dependency-direction checks for the weekly-plan application boundary."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from pete_e.application.weekly_plan_message import WeeklyPlanPresentationService


def test_weekly_plan_application_module_has_no_adapter_or_framework_imports() -> None:
    module_path = (
        Path(__file__).parents[2] / "pete_e" / "application" / "weekly_plan_message.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "pete_e.cli",
        "pete_e.infrastructure",
        "psycopg",
        "typer",
        "click",
        "fastapi",
        "starlette",
    )
    assert not {
        name
        for name in imported
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    }


def test_presentation_service_contains_no_dynamic_collaborator_discovery() -> None:
    source = inspect.getsource(WeeklyPlanPresentationService)
    assert "getattr(" not in source
    assert "PostgresDal" not in source
