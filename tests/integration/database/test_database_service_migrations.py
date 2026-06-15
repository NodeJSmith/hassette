"""Integration tests for the PRAGMA user_version migration runner and schema correctness."""

import sqlite3
from pathlib import Path

from hassette.core.migration_runner import run_migrations

EXPECTED_TABLES = {
    "sessions": {
        "id",
        "started_at",
        "stopped_at",
        "last_heartbeat_at",
        "status",
        "error_type",
        "error_message",
        "error_traceback",
        "dropped_overflow",
        "dropped_exhausted",
        "dropped_shutdown",
    },
    "listeners": {
        "id",
        "app_key",
        "instance_index",
        "name",
        "handler_method",
        "topic",
        "debounce",
        "throttle",
        "once",
        "priority",
        "mode",
        "immediate",
        "duration",
        "entity_id",
        "predicate_description",
        "human_description",
        "source_location",
        "registration_source",
        "retired_at",
        "cancelled_at",
        "source_tier",
    },
    "scheduled_jobs": {
        "id",
        "app_key",
        "instance_index",
        "job_name",
        "handler_method",
        "trigger_type",
        "trigger_label",
        "trigger_detail",
        "repeat",
        "args_json",
        "kwargs_json",
        "source_location",
        "registration_source",
        "retired_at",
        "source_tier",
        "group",
        "cancelled_at",
        "name_auto",
    },
    "executions": {
        "id",
        "kind",
        "listener_id",
        "job_id",
        "session_id",
        "execution_start_ts",
        "duration_ms",
        "status",
        "error_type",
        "error_message",
        "error_traceback",
        "is_di_failure",
        "source_tier",
        "execution_id",
        "trigger_context_id",
        "trigger_origin",
        "trigger_mode",
        "retry_count",
        "attempt_number",
        "args_json",
        "kwargs_json",
    },
    "log_records": {
        "id",
        "seq",
        "timestamp",
        "level",
        "logger_name",
        "func_name",
        "lineno",
        "message",
        "exc_info",
        "app_key",
        "instance_name",
        "instance_index",
        "execution_id",
        "source_tier",
    },
}


def test_fresh_db_migrates_to_head(tmp_path: Path) -> None:
    """Create an empty DB, run migrations, verify all expected tables exist."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = sorted(row[0] for row in cursor.fetchall())
        assert tables == sorted(EXPECTED_TABLES.keys())
    finally:
        conn.close()


def test_migration_schema_matches_expected_columns(tmp_path: Path) -> None:
    """After running migrations, compare resulting columns against expected schema."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        actual_tables = {row[0] for row in cursor.fetchall()}

        expected_table_names = set(EXPECTED_TABLES.keys())

        missing_tables = expected_table_names - actual_tables
        assert not missing_tables, f"Tables in expected schema but missing from DB: {missing_tables}"

        extra_tables = actual_tables - expected_table_names
        assert not extra_tables, f"Tables in DB but missing from expected schema: {extra_tables}"

        for table_name in sorted(actual_tables):
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            actual_columns = {row[1] for row in cursor.fetchall()}
            expected_columns = EXPECTED_TABLES[table_name]

            missing_columns = expected_columns - actual_columns
            assert not missing_columns, (
                f"Table {table_name!r}: columns in expected schema but missing from DB: {missing_columns}"
            )

            extra_columns = actual_columns - expected_columns
            assert not extra_columns, (
                f"Table {table_name!r}: columns in DB but missing from expected schema: {extra_columns}"
            )
    finally:
        conn.close()


def test_user_version_set_after_migration(tmp_path: Path) -> None:
    """PRAGMA user_version is set to 3 after all migrations run."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()

    assert version == 3


def test_auto_vacuum_set_on_fresh_db(tmp_path: Path) -> None:
    """auto_vacuum = INCREMENTAL (2) is set before tables are created."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
    finally:
        conn.close()

    assert mode == 2, f"Expected auto_vacuum = 2 (INCREMENTAL), got {mode}"


def test_no_alembic_version_table(tmp_path: Path) -> None:
    """The new schema does not create an alembic_version table."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE name = 'alembic_version'")
        row = cursor.fetchone()
    finally:
        conn.close()

    assert row is None, "alembic_version table must not exist in the new schema"
