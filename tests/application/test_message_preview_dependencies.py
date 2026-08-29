"""Dependency-direction checks for generic message preview ownership."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_preview_application_module_has_no_framework_cli_or_infrastructure_imports() -> (
    None
):
    module_path = ROOT / "pete_e" / "application" / "message_preview.py"
    imported = _imports(module_path)
    forbidden = (
        "pete_e.api",
        "pete_e.api_routes",
        "pete_e.cli",
        "pete_e.infrastructure",
        "fastapi",
        "starlette",
        "typer",
        "click",
    )

    assert not {
        name
        for name in imported
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    }

    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert names.isdisjoint(
        {"Request", "HTTPException", "ApplicationJobService", "subprocess"}
    )


def test_web_has_no_cli_message_builder_import_or_lazy_reference() -> None:
    web_path = ROOT / "pete_e" / "api_routes" / "web.py"
    source = web_path.read_text(encoding="utf-8")
    imported = _imports(web_path)

    assert "pete_e.cli.messenger" not in imported
    assert "pete_e.cli.messenger" not in source
    assert "build_daily_summary" not in source
    assert "build_trainer_summary" not in source
    assert "build_weekly_plan_overview" not in source
