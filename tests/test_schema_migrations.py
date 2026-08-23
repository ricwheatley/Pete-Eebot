from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from pete_e.infrastructure.schema_migrations import (
    INITIAL_REVISION,
    ManifestError,
    SchemaMigrationError,
    SchemaStatus,
    head_revision,
    load_manifest,
    reset_development_database,
)


def test_manifest_is_complete_ordered_transactional_and_checksum_valid() -> None:
    migrations = load_manifest()

    assert migrations[0].revision == INITIAL_REVISION
    assert migrations[-1].revision == head_revision()
    assert len(migrations) == 24
    assert [migration.filename for migration in migrations] == sorted(
        migration.filename for migration in migrations
    )
    assert all(migration.transactional for migration in migrations)


def test_initial_revision_is_non_destructive_and_runner_owns_transactions() -> None:
    migrations = load_manifest()
    initial = migrations[0].path.read_text(encoding="utf-8").upper()

    assert "DROP TABLE" not in initial
    assert "DROP SCHEMA" not in initial
    for migration in migrations:
        lines = {
            line.strip().upper()
            for line in migration.path.read_text(encoding="utf-8").splitlines()
        }
        assert "BEGIN;" not in lines
        assert "COMMIT;" not in lines
        assert "ROLLBACK;" not in lines


def test_modified_migration_is_rejected_by_checksum(tmp_path: Path) -> None:
    copied = tmp_path / "migrations"
    shutil.copytree("migrations", copied)
    target = copied / "20260511_add_nutrition_log.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- drift\n", encoding="utf-8")

    with pytest.raises(ManifestError, match="checksum"):
        load_manifest(copied)


def test_missing_and_reordered_manifest_entries_are_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "migrations"
    shutil.copytree("migrations", copied)
    manifest_path = copied / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["migrations"][1], manifest["migrations"][2] = (
        manifest["migrations"][2],
        manifest["migrations"][1],
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ManifestError, match="filename order"):
        load_manifest(copied)


@pytest.mark.parametrize(
    ("database_url", "message"),
    [
        ("postgresql://test:test@db.example/pete_e_test_reset", "loopback"),
        ("postgresql://test:test@127.0.0.1/real_database", "must start"),
    ],
)
def test_development_reset_rejects_unsafe_target_before_connecting(
    database_url: str,
    message: str,
) -> None:
    with pytest.raises(SchemaMigrationError, match=message):
        reset_development_database(
            database_url,
            confirm_database="wrong",
            destructive_confirmation=True,
        )


def test_schema_status_is_explicit_about_compatibility() -> None:
    status = SchemaStatus(
        state="stale",
        head_revision="head",
        current_revision="old",
        applied_count=1,
        pending_revisions=("head",),
        compatible=False,
        detail="1 migration pending",
    )

    assert status.compatible is False
    assert status.pending_revisions == ("head",)
