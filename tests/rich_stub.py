"""Provide a light-weight stub for the rich library used in tests."""
from __future__ import annotations

import sys
import types


if "rich.console" not in sys.modules:
    rich_module = types.ModuleType("rich")
    console_module = types.ModuleType("rich.console")
    table_module = types.ModuleType("rich.table")
    text_module = types.ModuleType("rich.text")

    class _Console:
        def __init__(self, *args, **kwargs):  # pragma: no cover - simple stub
            pass
            """Initialize this object."""

        def print(self, *args, **kwargs):  # pragma: no cover - mimic Console API
            pass
            """Perform print."""
        """Represent Console."""

    console_module.Console = _Console
    rich_module.console = console_module

    class _Table:
        def __init__(self, *args, **kwargs):  # pragma: no cover - simple stub
            pass
            """Initialize this object."""

        def add_column(self, *args, **kwargs):  # pragma: no cover - mimic API
            pass
            """Perform add column."""

        def add_row(self, *args, **kwargs):  # pragma: no cover - mimic API
            pass
            """Perform add row."""
        """Represent Table."""

    table_module.Table = _Table
    rich_module.table = table_module

    class _Text:
        def __init__(self, *args, **kwargs):  # pragma: no cover - simple stub
            pass
            """Initialize this object."""

        def append(self, *args, **kwargs):  # pragma: no cover - mimic API
            pass
            """Perform append."""
        """Represent Text."""

    text_module.Text = _Text
    rich_module.text = text_module

    sys.modules["rich"] = rich_module
    sys.modules["rich.console"] = console_module
    sys.modules["rich.table"] = table_module
    sys.modules["rich.text"] = text_module
