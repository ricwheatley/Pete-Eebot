"""Contracts proving framework imports resolve to installed distributions."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest


pytestmark = pytest.mark.contract

TESTS_DIR = Path(__file__).resolve().parent
FRAMEWORK_MODULES = (
    "click",
    "dropbox",
    "fastapi",
    "psycopg",
    "psycopg_pool",
    "pydantic",
    "pydantic_settings",
    "requests",
    "rich",
    "starlette",
    "tenacity",
    "typer",
)


def assert_installed_module(module: ModuleType) -> Path:
    """Reject dynamically-created modules and modules sourced from ``tests``."""

    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    module_file = getattr(module, "__file__", None)
    if spec is None or not origin or not module_file:
        raise AssertionError(f"{module.__name__} is a dynamically created substitute module")

    resolved = Path(module_file).resolve()
    if resolved == TESTS_DIR or TESTS_DIR in resolved.parents:
        raise AssertionError(f"{module.__name__} resolved inside tests: {resolved}")
    return resolved


@pytest.mark.parametrize("module_name", FRAMEWORK_MODULES)
def test_framework_module_resolves_from_installed_environment(module_name: str) -> None:
    module = importlib.import_module(module_name)

    assert_installed_module(module)


def test_import_guard_rejects_homemade_framework_module() -> None:
    fake_fastapi = ModuleType("fastapi")
    fake_fastapi.__file__ = str(TESTS_DIR / "conftest.py")

    with pytest.raises(AssertionError, match="dynamically created substitute"):
        assert_installed_module(fake_fastapi)
