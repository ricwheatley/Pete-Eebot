"""Package-native access to Pete-Eebot runtime resources."""

from __future__ import annotations

import os
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path


def package_resource(*parts: str) -> Traversable:
    """Return a bundled resource without inferring a checkout or working directory."""

    return files("pete_e").joinpath(*parts)


def package_resource_directory(*parts: str) -> Path:
    """Return a filesystem-backed package directory for path-only consumers.

    Wheels installed by standard Python installers are unpacked onto the
    filesystem. Fail clearly for unsupported zipped importers instead of
    constructing a path from ``__file__`` that may point somewhere incorrect.
    """

    resource = package_resource(*parts)
    if not resource.is_dir():
        raise FileNotFoundError(f"Bundled resource directory is missing: {'/'.join(parts)}")
    try:
        path = Path(os.fspath(resource))
    except TypeError as exc:
        raise RuntimeError(
            f"Bundled resource directory is not filesystem-backed: {'/'.join(parts)}"
        ) from exc
    if not path.is_dir():
        raise FileNotFoundError(f"Bundled resource directory is missing: {path}")
    return path
