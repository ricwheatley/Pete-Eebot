from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

import psycopg
from psycopg import ClientCursor
from psycopg_pool import ConnectionPool
import pytest

import pete_e.cli.status as health_status
from pete_e.infrastructure.job_repository import PostgresApplicationJobRepository
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.profile_repository import PostgresProfileRepository
from pete_e.infrastructure.schema_migrations import (
    LEGACY_RESET_MISSING_REVISIONS,
    LEDGER_TABLE,
    SchemaMigrationError,
    adopt_legacy_reset_database,
    baseline_database,
    head_revision,
    inspect_database,
    load_manifest,
    preflight_upgrade,
    previous_release_revision,
    reset_development_database,
    upgrade_database,
)
from pete_e.infrastructure.user_repository import PostgresUserRepository


pytestmark = pytest.mark.integration


def _database_name(dsn: str) -> str:
    return str(psycopg.conninfo.conninfo_to_dict(dsn).get("dbname") or "")


def _canonical_checksum(path: Path) -> str:
    return sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _manually_apply_through(dsn: str, revision: str) -> None:
    migrations = load_manifest()
    with psycopg.connect(dsn, autocommit=True, cursor_factory=ClientCursor) as connection:
        for migration in migrations:
            with connection.transaction():
                connection.execute(migration.path.read_text(encoding="utf-8"))
            if migration.revision == revision:
                return
    raise AssertionError(f"Revision not found: {revision}")


def _manually_apply_except(dsn: str, excluded_revisions: set[str]) -> None:
    with psycopg.connect(dsn, autocommit=True, cursor_factory=ClientCursor) as connection:
        for migration in load_manifest():
            if migration.revision in excluded_revisions:
                continue
            with connection.transaction():
                connection.execute(migration.path.read_text(encoding="utf-8"))


def _seed_representative_previous_release_data(dsn: str) -> None:
    with psycopg.connect(dsn) as connection:
        user_id = connection.execute(
            """
            INSERT INTO auth_users (username, username_normalized, password_hash)
            VALUES ('Retained User', 'retained-user', 'test-hash')
            RETURNING id
            """
        ).fetchone()[0]
        profile_id = connection.execute(
            """
            INSERT INTO user_profiles (slug, display_name, is_default)
            VALUES ('retained-profile', 'Retained Profile', false)
            RETURNING id
            """
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO auth_user_profiles (user_id, profile_id) VALUES (%s, %s)",
            (user_id, profile_id),
        )
        connection.execute(
            """
            INSERT INTO application_jobs (
                id, operation, requester_user_id, status, request_id,
                correlation_id, request_summary
            ) VALUES (
                'retained-job', 'sync', %s, 'queued', 'retained-request',
                'retained-correlation', '{}'::jsonb
            )
            """,
            (user_id,),
        )
        connection.execute(
            """
            INSERT INTO nutrition_log (
                client_event_id, dedupe_fingerprint, eaten_at, local_date,
                protein_g, carbs_g, fat_g, calories_est, source, confidence,
                raw_payload_json
            ) VALUES (
                'retained-event', 'retained-fingerprint', now(), CURRENT_DATE,
                30, 40, 10, 370, 'migration-test', 'high', '{}'::jsonb
            )
            """
        )
        connection.execute(
            "INSERT INTO training_plans (start_date, weeks, is_active) "
            "VALUES (CURRENT_DATE, 1, false)"
        )


def test_empty_database_upgrades_to_head_and_rerun_is_noop(
    disposable_database_factory,
) -> None:
    dsn = disposable_database_factory("fresh")

    before = inspect_database(dsn)
    first = upgrade_database(dsn)
    with psycopg.connect(dsn) as connection:
        ledger_before = connection.execute(
            f"SELECT revision, applied_at FROM {LEDGER_TABLE} ORDER BY position"
        ).fetchall()
        assert connection.execute("SELECT to_regclass('auth_users')").fetchone()[0] == "auth_users"
        assert connection.execute("SELECT to_regclass('application_jobs')").fetchone()[0] == "application_jobs"
        assert connection.execute("SELECT to_regclass('nutrition_log')").fetchone()[0] == "nutrition_log"

    second = upgrade_database(dsn)
    with psycopg.connect(dsn) as connection:
        ledger_after = connection.execute(
            f"SELECT revision, applied_at FROM {LEDGER_TABLE} ORDER BY position"
        ).fetchall()

    assert before.state == "empty"
    assert first.compatible is True
    assert first.current_revision == head_revision()
    assert second == first
    assert ledger_after == ledger_before
    assert len(ledger_after) == len(load_manifest())


def test_previous_release_upgrades_to_head_preserving_representative_data(
    disposable_database_factory,
) -> None:
    dsn = disposable_database_factory("previous")
    previous = previous_release_revision()
    stale = upgrade_database(dsn, target_revision=previous)
    _seed_representative_previous_release_data(dsn)

    upgraded = upgrade_database(dsn)

    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT username FROM auth_users WHERE username_normalized = 'retained-user'"
        ).fetchone() == ("Retained User",)
        assert connection.execute(
            "SELECT display_name FROM user_profiles WHERE slug = 'retained-profile'"
        ).fetchone() == ("Retained Profile",)
        assert connection.execute(
            "SELECT operation FROM application_jobs WHERE id = 'retained-job'"
        ).fetchone() == ("sync",)
        assert connection.execute(
            "SELECT protein_g FROM nutrition_log WHERE client_event_id = 'retained-event'"
        ).fetchone() == (30,)
        assert connection.execute("SELECT count(*) FROM training_plans").fetchone() == (1,)
        assert connection.execute("SELECT to_regclass('training_cycle')").fetchone()[0] == "training_cycle"

    assert stale.state == "stale"
    assert stale.current_revision == previous
    assert upgraded.compatible is True


def test_existing_installation_can_be_verified_baselined_without_replay(
    disposable_database_factory,
) -> None:
    dsn = disposable_database_factory("baseline")
    previous = previous_release_revision()
    _manually_apply_through(dsn, previous)
    _seed_representative_previous_release_data(dsn)

    assert inspect_database(dsn).state == "untracked"
    with pytest.raises(SchemaMigrationError, match="without a ledger"):
        upgrade_database(dsn)
    with pytest.raises(SchemaMigrationError, match="confirmation mismatch"):
        baseline_database(
            dsn,
            revision=previous,
            confirm_database="wrong-database",
        )

    adopted = baseline_database(
        dsn,
        revision=previous,
        confirm_database=_database_name(dsn),
    )
    baseline_count = next(
        migration.position for migration in load_manifest() if migration.revision == previous
    )
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            f"SELECT count(*) FROM {LEDGER_TABLE} WHERE baseline = true"
        ).fetchone() == (baseline_count,)
        assert connection.execute(
            "SELECT count(*) FROM nutrition_log WHERE client_event_id = 'retained-event'"
        ).fetchone() == (1,)

    assert adopted.state == "stale"
    assert upgrade_database(dsn).compatible is True


def test_retired_reset_snapshot_is_repaired_and_adopted_without_replay(
    disposable_database_factory,
) -> None:
    dsn = disposable_database_factory("legacyreset")
    missing_revisions = set(LEGACY_RESET_MISSING_REVISIONS)
    _manually_apply_except(dsn, missing_revisions)
    _seed_representative_previous_release_data(dsn)

    assert inspect_database(dsn).state == "untracked"
    adopted = adopt_legacy_reset_database(
        dsn,
        confirm_database=_database_name(dsn),
    )

    assert adopted.compatible is True
    with psycopg.connect(dsn) as connection:
        ledger = connection.execute(
            f"SELECT revision, baseline FROM {LEDGER_TABLE} ORDER BY position"
        ).fetchall()
        repaired = {revision for revision, baseline in ledger if not baseline}
        assert repaired == missing_revisions
        assert connection.execute(
            "SELECT count(*) FROM nutrition_log WHERE client_event_id = 'retained-event'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM application_jobs WHERE id = 'retained-job'"
        ).fetchone() == (1,)


def test_failed_migration_rolls_back_schema_and_ledger_then_can_rerun(
    disposable_database_factory,
    tmp_path: Path,
) -> None:
    dsn = disposable_database_factory("failure")
    upgrade_database(dsn)
    copied = tmp_path / "migrations"
    shutil.copytree("migrations", copied)
    failing = copied / "99999999_failure_probe.sql"
    failing.write_text(
        "CREATE TABLE migration_failure_probe (id INTEGER PRIMARY KEY);\nSELECT 1 / 0;\n",
        encoding="utf-8",
    )
    manifest_path = copied / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["migrations"].append(
        {
            "revision": failing.stem,
            "filename": failing.name,
            "sha256": _canonical_checksum(failing),
            "transactional": True,
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(SchemaMigrationError, match="failed and was rolled back"):
        upgrade_database(dsn, migrations_dir=copied)

    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT to_regclass('migration_failure_probe')"
        ).fetchone() == (None,)
        assert connection.execute(
            f"SELECT count(*) FROM {LEDGER_TABLE} WHERE revision = %s",
            (failing.stem,),
        ).fetchone() == (0,)

    failing.write_text(
        "CREATE TABLE migration_failure_probe (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    manifest["migrations"][-1]["sha256"] = _canonical_checksum(failing)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    rerun = upgrade_database(dsn, migrations_dir=copied)

    assert rerun.compatible is True
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT to_regclass('migration_failure_probe')"
        ).fetchone() == ("migration_failure_probe",)


def test_readiness_fails_when_stale_and_succeeds_at_head(
    disposable_database_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = disposable_database_factory("readiness")
    monkeypatch.setattr(health_status, "get_database_url", lambda: dsn)

    assert health_status.check_database(timeout=2).ok is False
    upgrade_database(dsn, target_revision=previous_release_revision())
    assert health_status.check_database(timeout=2).ok is False
    upgrade_database(dsn)
    result = health_status.check_database(timeout=2)

    assert result.ok is True
    assert head_revision() in result.detail

    with psycopg.connect(dsn) as connection:
        connection.execute("DROP TABLE nutrition_log")
    incomplete = health_status.check_database(timeout=2)

    assert incomplete.ok is False
    assert "incomplete" in incomplete.detail


def test_preflight_refuses_untracked_schema_before_any_upgrade(
    disposable_database_factory,
) -> None:
    dsn = disposable_database_factory("preflight")
    _manually_apply_through(dsn, previous_release_revision())

    with pytest.raises(SchemaMigrationError, match="preflight refused state=untracked"):
        preflight_upgrade(dsn)
    assert inspect_database(dsn).state == "untracked"


def test_guarded_development_reset_rebuilds_only_confirmed_test_database(
    disposable_database_factory,
) -> None:
    dsn = disposable_database_factory("reset")
    upgrade_database(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("CREATE TABLE reset_marker (id INTEGER)")

    reset = reset_development_database(
        dsn,
        confirm_database=_database_name(dsn),
        destructive_confirmation=True,
    )

    assert reset.compatible is True
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT to_regclass('reset_marker')").fetchone() == (None,)


def test_auth_jobs_profile_and_nutrition_repositories_smoke_at_head(
    disposable_database_factory,
) -> None:
    dsn = disposable_database_factory("repositories")
    upgrade_database(dsn)
    pool = ConnectionPool(conninfo=dsn, min_size=1, max_size=2, open=True)
    try:
        users = PostgresUserRepository(pool=pool)
        profiles = PostgresProfileRepository(pool=pool)
        jobs = PostgresApplicationJobRepository(pool=pool)
        dal = PostgresDal(pool=pool)

        user = users.create_user(
            username="Repository User",
            username_normalized="repository-user",
            email=None,
            email_normalized=None,
            display_name="Repository User",
            password_hash="test-hash",
            roles=("owner",),
        )
        session = users.create_session(
            user_id=user.id,
            token_hash="a" * 64,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        profile = profiles.create_profile(
            slug="repository-profile",
            display_name="Repository Profile",
            date_of_birth=None,
            height_cm=None,
            goal_weight_kg=None,
            timezone="Europe/London",
            is_default=False,
            owner_user_id=user.id,
        )
        job = jobs.create(
            job_id="repository-job",
            operation="sync",
            requester_user_id=user.id,
            requester_username=user.username,
            auth_scheme="session",
            request_id="repository-request",
            correlation_id="repository-correlation",
            request_summary={"lane": "migration-smoke"},
        )
        nutrition, duplicate = dal.insert_nutrition_log(
            {
                "client_event_id": "repository-event",
                "dedupe_fingerprint": "repository-fingerprint",
                "eaten_at": datetime.now(timezone.utc),
                "local_date": date.today(),
                "protein_g": 30,
                "carbs_g": 40,
                "fat_g": 10,
                "alcohol_g": 0,
                "fiber_g": 5,
                "estimated_total_calories": 370,
                "calories_est": 370,
                "source": "migration-smoke",
                "context": None,
                "confidence": "high",
                "meal_label": "smoke",
                "notes": None,
                "raw_payload_json": {"lane": "migration-smoke"},
            }
        )

        assert users.get_user_for_active_session("a" * 64, datetime.now(timezone.utc)).id == user.id
        assert session.user_id == user.id
        assert profiles.get_profile_by_slug_for_user(user.id, profile.slug).id == profile.id
        assert jobs.get(job.id).operation == "sync"
        assert duplicate is False
        assert nutrition["client_event_id"] == "repository-event"
    finally:
        pool.close()


def test_job_ownership_migration_abandons_unowned_legacy_running_rows(
    disposable_database_factory,
) -> None:
    dsn = disposable_database_factory("jobownership")
    upgrade_database(dsn, target_revision=previous_release_revision())
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO application_jobs (
                id, operation, status, request_id, correlation_id, request_summary
            ) VALUES (
                'legacy-unowned-running', 'sync', 'running',
                'legacy-unowned-running', 'legacy-unowned-running', '{}'::jsonb
            )
            """
        )
        connection.execute(
            """
            INSERT INTO application_operation_locks (lock_name, operation, job_id)
            VALUES ('high_risk_operation', 'sync', 'legacy-unowned-running')
            """
        )

    assert upgrade_database(dsn).compatible is True
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT status, abandon_reason FROM application_jobs WHERE id = %s",
            ("legacy-unowned-running",),
        ).fetchone() == ("abandoned", "ownership_migration")
        assert connection.execute(
            "SELECT count(*) FROM application_operation_locks WHERE job_id = %s",
            ("legacy-unowned-running",),
        ).fetchone() == (0,)
