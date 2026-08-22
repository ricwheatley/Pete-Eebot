"""Authoritative PostgreSQL schema migration management."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sysconfig
from time import perf_counter
from typing import Iterable, Sequence

import psycopg
from psycopg import ClientCursor


LEDGER_TABLE = "petee_schema_migrations"
MANIFEST_FILENAME = "manifest.json"
INITIAL_REVISION = "00000000_initial_schema"
ADVISORY_LOCK_KEY = 8_066_337_733_127_064_348
SAFE_RESET_DATABASE_PREFIXES = ("pete_e_dev", "pete_e_test")
SAFE_RESET_HOSTS = {"", "127.0.0.1", "::1", "localhost"}
LEGACY_RESET_MISSING_REVISIONS = (
    "20260511_add_nutrition_log_extended_fields",
    "20260511_add_nutrition_log_updated_at",
    "20260516_add_job_leases_and_recovery",
)

_TRANSACTION_CONTROL = re.compile(
    r"(?im)^\s*(?:BEGIN|COMMIT|ROLLBACK|START\s+TRANSACTION)\s*;\s*(?:--.*)?$"
)
_NON_TRANSACTIONAL_SQL = re.compile(
    r"(?im)^\s*(?:VACUUM\b|ALTER\s+SYSTEM\b|CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\b|"
    r"REINDEX\b.*\bCONCURRENTLY\b)"
)


class SchemaMigrationError(RuntimeError):
    """Base error for migration manifest, ledger, and upgrade failures."""


class ManifestError(SchemaMigrationError):
    """The checked-in migration manifest is incomplete or has drifted."""


class LedgerError(SchemaMigrationError):
    """The database ledger does not match authoritative migration history."""


class UntrackedDatabaseError(SchemaMigrationError):
    """A populated database has no authoritative revision ledger."""


class IncompatibleSchemaError(SchemaMigrationError):
    """The database schema does not satisfy its recorded revision."""


@dataclass(frozen=True)
class Migration:
    revision: str
    filename: str
    checksum: str
    position: int
    path: Path
    transactional: bool = True


@dataclass(frozen=True)
class AppliedMigration:
    revision: str
    filename: str
    checksum: str
    position: int
    baseline: bool


@dataclass(frozen=True)
class SchemaStatus:
    state: str
    head_revision: str
    current_revision: str | None
    applied_count: int
    pending_revisions: tuple[str, ...]
    compatible: bool
    detail: str


@dataclass(frozen=True)
class SchemaProbe:
    revision: str
    description: str
    sql: str


SCHEMA_PROBES: tuple[SchemaProbe, ...] = (
    SchemaProbe(
        INITIAL_REVISION,
        "initial training and health tables",
        """
        SELECT to_regclass('public.training_plans') IS NOT NULL
           AND to_regclass('public.daily_summary') IS NOT NULL
           AND to_regclass('public.wger_exercise') IS NOT NULL
        """,
    ),
    SchemaProbe(
        "20251003_update_body_age_function",
        "direct VO2 body-age function",
        """
        SELECT COALESCE(
            position('v_vo2_direct' IN pg_get_functiondef(
                to_regprocedure('public.sp_upsert_body_age(date,date)')
            )) > 0,
            false
        )
        """,
    ),
    SchemaProbe(
        "20260401_harden_plan_generation",
        "core pool and single-active-plan index",
        """
        SELECT to_regclass('public.core_pool') IS NOT NULL
           AND to_regclass('public.ux_training_plans_single_active') IS NOT NULL
        """,
    ),
    SchemaProbe(
        "20260413_capture_withings_measure_groups",
        "raw Withings measure groups",
        "SELECT to_regclass('public.withings_measure_groups') IS NOT NULL",
    ),
    SchemaProbe(
        "20260421_add_running_prescriptions",
        "running prescription columns",
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'training_plan_workouts'
              AND column_name = 'details'
        )
        """,
    ),
    SchemaProbe(
        "20260421_allow_comment_only_plan_sessions",
        "nullable plan exercise reference",
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'training_plan_workouts'
              AND column_name = 'exercise_id'
              AND is_nullable = 'YES'
        )
        """,
    ),
    SchemaProbe(
        "20260423_add_withings_body_comp_metrics",
        "enriched Withings body-composition columns",
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'daily_summary'
              AND column_name = 'visceral_fat_index'
        )
        """,
    ),
    SchemaProbe(
        "20260423_enrich_body_age_body_comp",
        "body-age enriched-composition audit column",
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'body_age_daily'
              AND column_name = 'used_enriched_body_comp'
        )
        """,
    ),
    SchemaProbe(
        "20260511_add_nutrition_log",
        "nutrition log",
        "SELECT to_regclass('public.nutrition_log') IS NOT NULL",
    ),
    SchemaProbe(
        "20260511_add_nutrition_log_extended_fields",
        "extended nutrition fields",
        """
        SELECT count(*) = 3
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'nutrition_log'
          AND column_name IN ('alcohol_g', 'fiber_g', 'estimated_total_calories')
        """,
    ),
    SchemaProbe(
        "20260511_add_nutrition_log_updated_at",
        "nutrition update timestamp",
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'nutrition_log'
              AND column_name = 'updated_at'
        )
        """,
    ),
    SchemaProbe(
        "20260515_add_auth_users_sessions_rbac",
        "authentication, sessions, and RBAC tables",
        """
        SELECT to_regclass('public.auth_users') IS NOT NULL
           AND to_regclass('public.auth_sessions') IS NOT NULL
           AND to_regclass('public.auth_user_roles') IS NOT NULL
        """,
    ),
    SchemaProbe(
        "20260515_add_user_profiles",
        "profile tables",
        """
        SELECT to_regclass('public.user_profiles') IS NOT NULL
           AND to_regclass('public.auth_user_profiles') IS NOT NULL
        """,
    ),
    SchemaProbe(
        "20260515_add_web_console_jobs",
        "application jobs and web console history",
        """
        SELECT to_regclass('public.application_jobs') IS NOT NULL
           AND to_regclass('public.web_console_command_history') IS NOT NULL
           AND to_regclass('public.application_operation_locks') IS NOT NULL
        """,
    ),
    SchemaProbe(
        "20260516_add_auth_mfa_fields",
        "authentication MFA columns",
        """
        SELECT count(*) = 3
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'auth_users'
          AND column_name IN ('mfa_secret', 'mfa_enabled', 'mfa_recovery_code_hashes')
        """,
    ),
    SchemaProbe(
        "20260516_add_job_leases_and_recovery",
        "job lease and recovery columns",
        """
        SELECT count(*) = 7
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'application_jobs'
          AND column_name IN (
              'worker_id', 'attempt_number', 'lease_expires_at',
              'last_heartbeat_at', 'ownership_token', 'abandon_reason',
              'progress_summary'
          )
        """,
    ),
    SchemaProbe(
        "20260610_add_coach_voice_payloads",
        "coach voice payload audit table",
        "SELECT to_regclass('public.coach_voice_payloads') IS NOT NULL",
    ),
    SchemaProbe(
        "20260624_add_assistance_difficulty",
        "assistance difficulty column",
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'assistance_pool'
              AND column_name = 'difficulty'
        )
        """,
    ),
    SchemaProbe(
        "20260628_adaptive_exercise_difficulty",
        "adaptive exercise difficulty tables",
        """
        SELECT to_regclass('public.exercise_programming_metadata') IS NOT NULL
           AND to_regclass('public.exercise_difficulty_unlock_state') IS NOT NULL
        """,
    ),
    SchemaProbe(
        "20260820_add_readiness_adjustment_idempotency",
        "readiness adjustment ledger and baseline prescription columns",
        """
        SELECT to_regclass('public.plan_readiness_adjustments') IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = 'training_plan_workouts'
                 AND column_name = 'baseline_sets'
           )
           AND EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = 'training_plan_weeks'
                 AND column_name = 'effective_readiness_adjustment_id'
           )
        """,
    ),
    SchemaProbe(
        "20260822_reconcile_untracked_schema",
        "training cycle and plan metadata",
        """
        SELECT to_regclass('public.training_cycle') IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = 'training_plans'
                 AND column_name = 'metadata'
           )
        """,
    ),
)


def _candidate_migration_directories() -> Iterable[Path]:
    configured = os.getenv("PETEEEBOT_MIGRATIONS_DIR")
    if configured:
        yield Path(configured).expanduser()
    yield Path(__file__).resolve().parents[2] / "migrations"
    yield Path.cwd() / "migrations"
    yield Path(sysconfig.get_path("data")) / "share" / "pete_e" / "migrations"


def migrations_directory(path: Path | str | None = None) -> Path:
    """Resolve the authoritative migration directory without database access."""

    if path is not None:
        candidate = Path(path).resolve()
        if not (candidate / MANIFEST_FILENAME).is_file():
            raise ManifestError(f"Migration manifest not found in {candidate}")
        return candidate

    checked: list[str] = []
    for candidate in _candidate_migration_directories():
        resolved = candidate.resolve()
        checked.append(str(resolved))
        if (resolved / MANIFEST_FILENAME).is_file():
            return resolved
    raise ManifestError("Migration manifest not found; checked: " + ", ".join(checked))


def load_manifest(path: Path | str | None = None) -> tuple[Migration, ...]:
    """Load and validate filenames, ordering, checksums, and transaction policy."""

    directory = migrations_directory(path)
    manifest_path = directory / MANIFEST_FILENAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Cannot read {manifest_path}: {exc}") from exc

    if payload.get("format") != 1 or not isinstance(payload.get("migrations"), list):
        raise ManifestError("Migration manifest format must be 1 with a migrations list")

    entries = payload["migrations"]
    revisions = [entry.get("revision") for entry in entries]
    filenames = [entry.get("filename") for entry in entries]
    if not revisions or any(not isinstance(value, str) or not value for value in revisions):
        raise ManifestError("Every migration must have a non-empty revision")
    if len(set(revisions)) != len(revisions):
        raise ManifestError("Migration manifest contains duplicate revisions")
    if len(set(filenames)) != len(filenames):
        raise ManifestError("Migration manifest contains duplicate filenames")
    if filenames != sorted(filenames):
        raise ManifestError("Migration manifest entries must remain in filename order")
    if revisions[0] != INITIAL_REVISION:
        raise ManifestError(f"First migration must be {INITIAL_REVISION}")

    tracked_files = set(filenames)
    actual_files = {item.name for item in directory.glob("*.sql")}
    if tracked_files != actual_files:
        missing = sorted(tracked_files - actual_files)
        untracked = sorted(actual_files - tracked_files)
        raise ManifestError(f"Migration file set differs from manifest: missing={missing}, untracked={untracked}")

    migrations: list[Migration] = []
    for position, entry in enumerate(entries, start=1):
        filename = entry["filename"]
        revision = entry["revision"]
        if Path(filename).stem != revision or Path(filename).suffix != ".sql":
            raise ManifestError(f"Revision and SQL filename disagree: {revision!r}, {filename!r}")
        if entry.get("transactional") is not True:
            raise ManifestError(f"Non-transactional migration is not supported: {filename}")

        migration_path = directory / filename
        raw = migration_path.read_bytes()
        sql_text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        actual_checksum = sha256(sql_text.encode("utf-8")).hexdigest()
        expected_checksum = str(entry.get("sha256") or "").lower()
        if actual_checksum != expected_checksum:
            raise ManifestError(
                f"Migration checksum differs from manifest for {filename}: "
                f"expected {expected_checksum}, found {actual_checksum}"
            )

        if _TRANSACTION_CONTROL.search(sql_text):
            raise ManifestError(f"Migration contains transaction control owned by the runner: {filename}")
        if _NON_TRANSACTIONAL_SQL.search(sql_text):
            raise ManifestError(f"Migration contains non-transactional PostgreSQL SQL: {filename}")
        migrations.append(
            Migration(
                revision=revision,
                filename=filename,
                checksum=actual_checksum,
                position=position,
                path=migration_path,
            )
        )
    return tuple(migrations)


def previous_release_revision(path: Path | str | None = None) -> str:
    directory = migrations_directory(path)
    payload = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    revision = str(payload.get("previous_release_revision") or "")
    revisions = {migration.revision for migration in load_manifest(directory)}
    if revision not in revisions:
        raise ManifestError("previous_release_revision is not present in the migration manifest")
    return revision


def head_revision(path: Path | str | None = None) -> str:
    return load_manifest(path)[-1].revision


def _connect(database_url: str, timeout: float = 5.0) -> psycopg.Connection:
    return psycopg.connect(
        database_url,
        autocommit=True,
        connect_timeout=max(1, int(timeout + 0.999)),
        cursor_factory=ClientCursor,
    )


def _ledger_exists(connection: psycopg.Connection) -> bool:
    row = connection.execute(
        "SELECT to_regclass(%s) IS NOT NULL",
        (f"public.{LEDGER_TABLE}",),
    ).fetchone()
    return bool(row and row[0])


def _database_has_user_objects(connection: psycopg.Connection) -> bool:
    row = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
              AND relation.relname <> %s
        ) OR EXISTS (
            SELECT 1
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'public'
        )
        """,
        (LEDGER_TABLE,),
    ).fetchone()
    return bool(row and row[0])


def _create_ledger(connection: psycopg.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{LEDGER_TABLE} (
            revision TEXT PRIMARY KEY,
            filename TEXT NOT NULL UNIQUE,
            checksum CHAR(64) NOT NULL,
            position INTEGER NOT NULL UNIQUE CHECK (position > 0),
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            execution_ms INTEGER NOT NULL CHECK (execution_ms >= 0),
            baseline BOOLEAN NOT NULL DEFAULT false
        )
        """
    )
    connection.execute(
        f"COMMENT ON TABLE public.{LEDGER_TABLE} IS "
        "'Authoritative Pete-Eebot schema revision ledger; managed only by pete-schema.'"
    )


def _read_applied(connection: psycopg.Connection) -> tuple[AppliedMigration, ...]:
    if not _ledger_exists(connection):
        return ()
    try:
        rows = connection.execute(
            f"""
            SELECT revision, filename, checksum, position, baseline
            FROM public.{LEDGER_TABLE}
            ORDER BY position
            """
        ).fetchall()
    except psycopg.Error as exc:
        raise LedgerError("Schema migration ledger exists but cannot be read or has invalid columns") from exc
    return tuple(
        AppliedMigration(
            revision=str(row[0]),
            filename=str(row[1]),
            checksum=str(row[2]).strip(),
            position=int(row[3]),
            baseline=bool(row[4]),
        )
        for row in rows
    )


def _validate_applied_prefix(
    applied: Sequence[AppliedMigration],
    migrations: Sequence[Migration],
) -> None:
    if len(applied) > len(migrations):
        raise LedgerError("Database ledger contains more revisions than the manifest")
    for index, recorded in enumerate(applied):
        expected = migrations[index]
        differences: list[str] = []
        if recorded.position != expected.position:
            differences.append(f"position {recorded.position} != {expected.position}")
        if recorded.revision != expected.revision:
            differences.append(f"revision {recorded.revision!r} != {expected.revision!r}")
        if recorded.filename != expected.filename:
            differences.append(f"filename {recorded.filename!r} != {expected.filename!r}")
        if recorded.checksum != expected.checksum:
            differences.append("checksum differs")
        if differences:
            raise LedgerError(
                f"Applied migration history diverges at position {index + 1}: "
                + "; ".join(differences)
            )


def _revision_position(migrations: Sequence[Migration], revision: str) -> int:
    if revision == "head":
        return len(migrations)
    for migration in migrations:
        if migration.revision == revision:
            return migration.position
    raise ManifestError(f"Unknown target revision: {revision}")


def _probe_results(
    connection: psycopg.Connection,
    migrations: Sequence[Migration],
) -> tuple[tuple[SchemaProbe, bool], ...]:
    revision_positions = {migration.revision: migration.position for migration in migrations}
    results: list[tuple[SchemaProbe, bool]] = []
    for probe in SCHEMA_PROBES:
        if probe.revision not in revision_positions:
            raise ManifestError(f"Schema probe references unknown revision: {probe.revision}")
        row = connection.execute(probe.sql).fetchone()
        results.append((probe, bool(row and row[0])))
    return tuple(results)


def _missing_schema_requirements(
    connection: psycopg.Connection,
    migrations: Sequence[Migration],
    revision: str,
) -> list[str]:
    target_position = _revision_position(migrations, revision)
    positions = {migration.revision: migration.position for migration in migrations}
    return [
        probe.description
        for probe, satisfied in _probe_results(connection, migrations)
        if positions[probe.revision] <= target_position and not satisfied
    ]


def _validate_exact_baseline_schema(
    connection: psycopg.Connection,
    migrations: Sequence[Migration],
    revision: str,
) -> None:
    target_position = _revision_position(migrations, revision)
    positions = {migration.revision: migration.position for migration in migrations}
    missing: list[str] = []
    later: list[str] = []
    for probe, satisfied in _probe_results(connection, migrations):
        if positions[probe.revision] <= target_position and not satisfied:
            missing.append(probe.description)
        elif positions[probe.revision] > target_position and satisfied:
            later.append(probe.description)
    if missing or later:
        raise IncompatibleSchemaError(
            "Database cannot be safely baselined at the requested revision: "
            f"missing expected markers={missing}; later/non-linear markers={later}"
        )


def _validate_legacy_reset_schema(
    connection: psycopg.Connection,
    migrations: Sequence[Migration],
) -> None:
    """Recognize only the exact non-linear shape of the retired reset snapshot."""

    missing_revisions = set(LEGACY_RESET_MISSING_REVISIONS)
    missing_expected: list[str] = []
    unexpectedly_present: list[str] = []
    for probe, satisfied in _probe_results(connection, migrations):
        if probe.revision in missing_revisions and satisfied:
            unexpectedly_present.append(probe.description)
        elif probe.revision not in missing_revisions and not satisfied:
            missing_expected.append(probe.description)

    partial_columns = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'nutrition_log'
               AND column_name IN (
                   'alcohol_g', 'fiber_g', 'estimated_total_calories', 'updated_at'
               )),
            (SELECT count(*) FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'application_jobs'
               AND column_name IN (
                   'worker_id', 'attempt_number', 'lease_expires_at',
                   'last_heartbeat_at', 'ownership_token', 'abandon_reason',
                   'progress_summary'
               ))
        """
    ).fetchone()
    if missing_expected or unexpectedly_present or partial_columns != (0, 0):
        raise IncompatibleSchemaError(
            "Database does not match the retired reset-snapshot adoption profile: "
            f"missing expected markers={missing_expected}; "
            f"unexpected repaired markers={unexpectedly_present}; "
            f"partial omitted-column counts={partial_columns}"
        )


def inspect_database(
    database_url: str,
    *,
    migrations_dir: Path | str | None = None,
    timeout: float = 5.0,
) -> SchemaStatus:
    """Inspect ledger and required schema using read-only metadata queries."""

    migrations = load_manifest(migrations_dir)
    head = migrations[-1].revision
    with _connect(database_url, timeout) as connection:
        if not _ledger_exists(connection):
            state = "untracked" if _database_has_user_objects(connection) else "empty"
            return SchemaStatus(
                state=state,
                head_revision=head,
                current_revision=None,
                applied_count=0,
                pending_revisions=tuple(migration.revision for migration in migrations),
                compatible=False,
                detail=(
                    "populated database has no migration ledger; run the verified baseline workflow"
                    if state == "untracked"
                    else "empty database has not been upgraded"
                ),
            )

        try:
            applied = _read_applied(connection)
            _validate_applied_prefix(applied, migrations)
        except LedgerError as exc:
            return SchemaStatus(
                state="invalid",
                head_revision=head,
                current_revision=None,
                applied_count=0,
                pending_revisions=(),
                compatible=False,
                detail=str(exc),
            )

        if not applied and _database_has_user_objects(connection):
            return SchemaStatus(
                state="untracked",
                head_revision=head,
                current_revision=None,
                applied_count=0,
                pending_revisions=tuple(migration.revision for migration in migrations),
                compatible=False,
                detail="populated database has an empty ledger; verified baseline is required",
            )

        current = applied[-1].revision if applied else None
        if current is not None:
            missing = _missing_schema_requirements(connection, migrations, current)
            if missing:
                return SchemaStatus(
                    state="incomplete",
                    head_revision=head,
                    current_revision=current,
                    applied_count=len(applied),
                    pending_revisions=(),
                    compatible=False,
                    detail="recorded schema markers missing: " + ", ".join(missing),
                )

        pending = tuple(migration.revision for migration in migrations[len(applied) :])
        if pending:
            return SchemaStatus(
                state="stale",
                head_revision=head,
                current_revision=current,
                applied_count=len(applied),
                pending_revisions=pending,
                compatible=False,
                detail=f"{len(pending)} migration(s) pending",
            )

        missing = _missing_schema_requirements(connection, migrations, head)
        if missing:
            return SchemaStatus(
                state="incomplete",
                head_revision=head,
                current_revision=current,
                applied_count=len(applied),
                pending_revisions=(),
                compatible=False,
                detail="required schema markers missing: " + ", ".join(missing),
            )
        return SchemaStatus(
            state="head",
            head_revision=head,
            current_revision=current,
            applied_count=len(applied),
            pending_revisions=(),
            compatible=True,
            detail="schema is at the required revision",
        )


def verify_database(
    database_url: str,
    *,
    migrations_dir: Path | str | None = None,
    timeout: float = 5.0,
) -> SchemaStatus:
    status = inspect_database(database_url, migrations_dir=migrations_dir, timeout=timeout)
    if not status.compatible:
        raise IncompatibleSchemaError(
            f"Schema is incompatible (state={status.state}, current={status.current_revision or 'none'}, "
            f"required={status.head_revision}): {status.detail}"
        )
    return status


def preflight_upgrade(
    database_url: str,
    *,
    migrations_dir: Path | str | None = None,
    timeout: float = 5.0,
) -> SchemaStatus:
    """Require an empty database or a valid tracked prefix before any DDL."""

    status = inspect_database(database_url, migrations_dir=migrations_dir, timeout=timeout)
    if status.state not in {"empty", "stale", "head"}:
        raise IncompatibleSchemaError(
            f"Schema upgrade preflight refused state={status.state}: {status.detail}"
        )
    return status


def upgrade_database(
    database_url: str,
    *,
    target_revision: str = "head",
    migrations_dir: Path | str | None = None,
    timeout: float = 5.0,
) -> SchemaStatus:
    """Apply pending revisions transactionally and record each only on success."""

    migrations = load_manifest(migrations_dir)
    target_position = _revision_position(migrations, target_revision)
    with _connect(database_url, timeout) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            if not _ledger_exists(connection):
                if _database_has_user_objects(connection):
                    raise UntrackedDatabaseError(
                        "Refusing to migrate a populated database without a ledger. "
                        "Inspect it and use baseline with an explicit confirmed revision."
                    )
                with connection.transaction():
                    _create_ledger(connection)

            applied = _read_applied(connection)
            _validate_applied_prefix(applied, migrations)
            if not applied and _database_has_user_objects(connection):
                raise UntrackedDatabaseError(
                    "Refusing to migrate a populated database with an empty ledger. "
                    "Inspect it and use baseline with an explicit confirmed revision."
                )
            if len(applied) > target_position:
                raise LedgerError(
                    f"Database is already beyond requested target {target_revision}; downgrades are not supported"
                )

            for migration in migrations[len(applied) : target_position]:
                sql_text = migration.path.read_text(encoding="utf-8")
                started = perf_counter()
                try:
                    with connection.transaction():
                        connection.execute(sql_text)
                        elapsed_ms = max(0, int((perf_counter() - started) * 1000))
                        connection.execute(
                            f"""
                            INSERT INTO public.{LEDGER_TABLE} (
                                revision, filename, checksum, position, execution_ms, baseline
                            ) VALUES (%s, %s, %s, %s, %s, false)
                            """,
                            (
                                migration.revision,
                                migration.filename,
                                migration.checksum,
                                migration.position,
                                elapsed_ms,
                            ),
                        )
                except Exception as exc:
                    raise SchemaMigrationError(
                        f"Migration {migration.revision} failed and was rolled back: {exc}"
                    ) from exc
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))

    return inspect_database(database_url, migrations_dir=migrations_dir, timeout=timeout)


def baseline_database(
    database_url: str,
    *,
    revision: str,
    confirm_database: str,
    migrations_dir: Path | str | None = None,
    timeout: float = 5.0,
) -> SchemaStatus:
    """Adopt a matching untracked installation without replaying schema changes."""

    migrations = load_manifest(migrations_dir)
    target_position = _revision_position(migrations, revision)
    target_revision = migrations[target_position - 1].revision
    with _connect(database_url, timeout) as connection:
        actual_database = str(connection.info.dbname)
        if confirm_database != actual_database:
            raise UntrackedDatabaseError(
                f"Database confirmation mismatch: expected exact name {actual_database!r}"
            )
        connection.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            if _ledger_exists(connection) and _read_applied(connection):
                raise LedgerError("Refusing to baseline a database that already has recorded revisions")
            if not _database_has_user_objects(connection):
                raise UntrackedDatabaseError("Refusing to baseline an empty database; use upgrade instead")

            _validate_exact_baseline_schema(connection, migrations, target_revision)
            with connection.transaction():
                _create_ledger(connection)
                for migration in migrations[:target_position]:
                    connection.execute(
                        f"""
                        INSERT INTO public.{LEDGER_TABLE} (
                            revision, filename, checksum, position, execution_ms, baseline
                        ) VALUES (%s, %s, %s, %s, 0, true)
                        """,
                        (
                            migration.revision,
                            migration.filename,
                            migration.checksum,
                            migration.position,
                        ),
                    )
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
    return inspect_database(database_url, migrations_dir=migrations_dir, timeout=timeout)


def adopt_legacy_reset_database(
    database_url: str,
    *,
    confirm_database: str,
    migrations_dir: Path | str | None = None,
    timeout: float = 5.0,
) -> SchemaStatus:
    """Adopt the exact retired reset snapshot and repair its known omissions."""

    migrations = load_manifest(migrations_dir)
    missing_revisions = set(LEGACY_RESET_MISSING_REVISIONS)
    with _connect(database_url, timeout) as connection:
        actual_database = str(connection.info.dbname)
        if confirm_database != actual_database:
            raise UntrackedDatabaseError(
                f"Database confirmation mismatch: expected exact name {actual_database!r}"
            )
        connection.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            if _ledger_exists(connection) and _read_applied(connection):
                raise LedgerError("Refusing to adopt a database that already has recorded revisions")
            if not _database_has_user_objects(connection):
                raise UntrackedDatabaseError("Refusing legacy adoption for an empty database")

            _validate_legacy_reset_schema(connection, migrations)
            with connection.transaction():
                _create_ledger(connection)
                for migration in migrations:
                    repaired = migration.revision in missing_revisions
                    started = perf_counter()
                    if repaired:
                        connection.execute(migration.path.read_text(encoding="utf-8"))
                    elapsed_ms = max(0, int((perf_counter() - started) * 1000))
                    connection.execute(
                        f"""
                        INSERT INTO public.{LEDGER_TABLE} (
                            revision, filename, checksum, position, execution_ms, baseline
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            migration.revision,
                            migration.filename,
                            migration.checksum,
                            migration.position,
                            elapsed_ms,
                            not repaired,
                        ),
                    )
        except SchemaMigrationError:
            raise
        except Exception as exc:
            raise SchemaMigrationError(
                f"Legacy reset-snapshot adoption failed and was rolled back: {exc}"
            ) from exc
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))

    return verify_database(database_url, migrations_dir=migrations_dir, timeout=timeout)


def reset_development_database(
    database_url: str,
    *,
    confirm_database: str,
    destructive_confirmation: bool,
    migrations_dir: Path | str | None = None,
    timeout: float = 5.0,
) -> SchemaStatus:
    """Drop and rebuild an explicitly confirmed loopback development/test DB."""

    if not destructive_confirmation:
        raise SchemaMigrationError("Development reset requires the destructive confirmation flag")
    connection_info = psycopg.conninfo.conninfo_to_dict(database_url)
    configured_host = str(connection_info.get("host") or "")
    configured_database = str(connection_info.get("dbname") or "")
    if configured_host not in SAFE_RESET_HOSTS:
        raise SchemaMigrationError("Development reset is restricted to a loopback PostgreSQL host")
    if not configured_database.startswith(SAFE_RESET_DATABASE_PREFIXES):
        raise SchemaMigrationError(
            "Development reset database name must start with pete_e_dev or pete_e_test"
        )

    with _connect(database_url, timeout) as connection:
        actual_database = str(connection.info.dbname)
        if confirm_database != actual_database or configured_database != actual_database:
            raise SchemaMigrationError(
                f"Database confirmation mismatch: expected exact name {actual_database!r}"
            )
        connection.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            with connection.transaction():
                connection.execute("DROP SCHEMA public CASCADE")
                connection.execute("CREATE SCHEMA public")
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))

    return upgrade_database(
        database_url,
        migrations_dir=migrations_dir,
        timeout=timeout,
    )


def format_status(status: SchemaStatus) -> str:
    current = status.current_revision or "none"
    return (
        f"state={status.state} current={current} required={status.head_revision} "
        f"applied={status.applied_count} pending={len(status.pending_revisions)} "
        f"compatible={'yes' if status.compatible else 'no'} detail={status.detail}"
    )
