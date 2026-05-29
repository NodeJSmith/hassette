"""Unit tests for the PRAGMA user_version migration runner.

Covers:
- FR#7: migrations applied in order, user_version set atomically
- FR#9: crash mid-migration leaves DB at previous version
- FR#19: new columns (trigger_mode, retry_count, etc.) exist after 001
- FR#17 / AC#11: kind CHECK constraint rejects invalid values at the SQL level
"""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from hassette.core.migration_runner import (
    _apply_migration,
    _collect_migrations,
    _read_user_version,
    _set_auto_vacuum,
    run_migrations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_version(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cursor.fetchall()}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# _collect_migrations
# ---------------------------------------------------------------------------


def test_collect_migrations_finds_sql_files(tmp_path: Path) -> None:
    """_collect_migrations returns {version: path} for numeric .sql stems."""
    (tmp_path / "001.sql").write_text("SELECT 1;")
    (tmp_path / "002.sql").write_text("SELECT 2;")
    (tmp_path / "not_numeric.sql").write_text("SELECT 3;")

    with patch("hassette.core.migration_runner._MIGRATIONS_DIR", tmp_path):
        result = _collect_migrations(None)

    assert 1 in result
    assert 2 in result
    assert all(isinstance(k, int) for k in result)
    # non-numeric stem is excluded
    assert len(result) == 2


def test_collect_migrations_respects_target(tmp_path: Path) -> None:
    """_collect_migrations with target=1 returns only version 1."""
    (tmp_path / "001.sql").write_text("SELECT 1;")
    (tmp_path / "002.sql").write_text("SELECT 2;")

    with patch("hassette.core.migration_runner._MIGRATIONS_DIR", tmp_path):
        result = _collect_migrations(1)

    assert set(result.keys()) == {1}


def test_collect_migrations_empty_dir(tmp_path: Path) -> None:
    """_collect_migrations returns empty dict for a directory with no .sql files."""
    with patch("hassette.core.migration_runner._MIGRATIONS_DIR", tmp_path):
        result = _collect_migrations(None)

    assert result == {}


# ---------------------------------------------------------------------------
# _read_user_version
# ---------------------------------------------------------------------------


def test_read_user_version_fresh_db(tmp_path: Path) -> None:
    """Fresh database has PRAGMA user_version = 0."""
    db_path = tmp_path / "fresh.db"
    conn = sqlite3.connect(db_path)
    conn.close()

    assert _read_user_version(db_path) == 0


def test_read_user_version_after_set(tmp_path: Path) -> None:
    """_read_user_version returns the value set by a prior migration."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 5")
    conn.close()

    assert _read_user_version(db_path) == 5


# ---------------------------------------------------------------------------
# _set_auto_vacuum
# ---------------------------------------------------------------------------


def test_set_auto_vacuum_sets_incremental(tmp_path: Path) -> None:
    """_set_auto_vacuum sets auto_vacuum = INCREMENTAL (2) on a fresh database."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.close()

    _set_auto_vacuum(db_path)

    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
    finally:
        conn.close()

    assert mode == 2


def test_set_auto_vacuum_noop_if_already_incremental(tmp_path: Path) -> None:
    """_set_auto_vacuum does not fail if auto_vacuum is already INCREMENTAL."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    conn.close()

    # Should not raise
    _set_auto_vacuum(db_path)

    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
    finally:
        conn.close()

    assert mode == 2


# ---------------------------------------------------------------------------
# _apply_migration
# ---------------------------------------------------------------------------


def test_apply_migration_creates_table(tmp_path: Path) -> None:
    """_apply_migration runs the SQL and sets PRAGMA user_version."""
    db_path = tmp_path / "test.db"
    sql_path = tmp_path / "001.sql"
    sql_path.write_text("CREATE TABLE foo (id INTEGER PRIMARY KEY);")

    _apply_migration(db_path, 1, sql_path)

    assert "foo" in _tables(db_path)
    assert _user_version(db_path) == 1


def test_apply_migration_sets_version_atomically(tmp_path: Path) -> None:
    """Simulated crash mid-migration leaves DB at previous user_version.

    FR#9: each migration is atomic — crash leaves DB at previous version.
    """
    db_path = tmp_path / "test.db"

    # Apply migration 1 successfully first
    sql1 = tmp_path / "001.sql"
    sql1.write_text("CREATE TABLE v1 (id INTEGER PRIMARY KEY);")
    _apply_migration(db_path, 1, sql1)
    assert _user_version(db_path) == 1

    # Simulate migration 2 that raises mid-way by having bad SQL after a valid statement
    sql2 = tmp_path / "002.sql"
    sql2.write_text("CREATE TABLE v2 (id INTEGER PRIMARY KEY);\nNOT VALID SQL;")

    with pytest.raises(sqlite3.OperationalError):
        _apply_migration(db_path, 2, sql2)

    # user_version must still be 1 — the failed migration left no trace
    assert _user_version(db_path) == 1
    # v2 table must not exist (rolled back)
    assert "v2" not in _tables(db_path)


# ---------------------------------------------------------------------------
# run_migrations (integration with real 001.sql)
# ---------------------------------------------------------------------------


def test_run_migrations_applies_001(tmp_path: Path) -> None:
    """run_migrations applies migrations in order and sets version atomically (FR#7)."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    assert _user_version(db_path) == 1
    assert "executions" in _tables(db_path)
    assert "listeners" in _tables(db_path)
    assert "scheduled_jobs" in _tables(db_path)
    assert "sessions" in _tables(db_path)
    assert "log_records" in _tables(db_path)


def test_run_migrations_idempotent(tmp_path: Path) -> None:
    """Calling run_migrations twice does not raise or change the version."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)
    run_migrations(db_path)  # second call is a no-op

    assert _user_version(db_path) == 1


def test_run_migrations_partial_target(tmp_path: Path) -> None:
    """run_migrations with target=0 applies nothing to a fresh database."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=0)

    assert _user_version(db_path) == 0
    assert "executions" not in _tables(db_path)


def test_run_migrations_skips_already_applied(tmp_path: Path) -> None:
    """Migrations up to current version are not reapplied."""
    migrations_dir = tmp_path / "migrations_sql"
    migrations_dir.mkdir()
    real_001 = Path(__file__).parent.parent.parent.parent / "src" / "hassette" / "migrations_sql" / "001.sql"
    (migrations_dir / "001.sql").write_bytes(real_001.read_bytes())
    db_path = tmp_path / "test.db"

    with patch("hassette.core.migration_runner._MIGRATIONS_DIR", migrations_dir):
        run_migrations(db_path)
        version_after_first = _user_version(db_path)

        # A fake second migration with invalid SQL must never run, because
        # version 1 is already current and target=1 caps application at 1.
        (migrations_dir / "002.sql").write_text("THIS IS INVALID SQL THAT SHOULD NEVER RUN;")
        run_migrations(db_path, target=1)
        assert _user_version(db_path) == version_after_first


# ---------------------------------------------------------------------------
# Schema content tests (FR#19, FR#17, AC#11)
# ---------------------------------------------------------------------------


def test_new_columns_exist_after_001(tmp_path: Path) -> None:
    """Known future columns exist in executions table after 001 applies (FR#19)."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    cols = _columns(db_path, "executions")
    # Future columns baked into initial schema to avoid follow-up migrations
    assert "trigger_mode" in cols, "trigger_mode missing from executions"
    assert "retry_count" in cols, "retry_count missing from executions"
    assert "attempt_number" in cols, "attempt_number missing from executions"
    assert "args_json" in cols, "args_json missing from executions"
    assert "kwargs_json" in cols, "kwargs_json missing from executions"


def test_kind_check_rejects_invalid_values(tmp_path: Path) -> None:
    """kind CHECK constraint rejects values other than 'handler' and 'job' (FR#17, AC#11)."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
        conn.execute(
            "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
            " VALUES ('app', 0, 'my_listener', 'on_x', 'light.x', 'app.py:1')"
        )
        conn.commit()

        # Valid kind values must succeed
        conn.execute(
            "INSERT INTO executions "
            "(kind, listener_id, session_id, execution_start_ts, duration_ms, status, source_tier) "
            "VALUES ('handler', 1, 1, 1.0, 5.0, 'success', 'app')"
        )
        conn.commit()

        # Invalid kind must raise IntegrityError
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO executions "
                "(kind, listener_id, session_id, execution_start_ts, duration_ms, status, source_tier) "
                "VALUES ('invalid_kind', 1, 1, 2.0, 5.0, 'success', 'app')"
            )
    finally:
        conn.close()


def test_kind_check_accepts_job(tmp_path: Path) -> None:
    """kind='job' is accepted when job_id is set (and listener_id is NULL)."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
        conn.execute(
            "INSERT INTO scheduled_jobs "
            "(app_key, instance_index, job_name, handler_method, source_location, source_tier)"
            " VALUES ('app', 0, 'my_job', 'on_x', 'app.py:1', 'app')"
        )
        conn.commit()

        conn.execute(
            "INSERT INTO executions "
            "(kind, job_id, session_id, execution_start_ts, duration_ms, status, source_tier) "
            "VALUES ('job', 1, 1, 1.0, 5.0, 'success', 'app')"
        )
        conn.commit()

        cursor = conn.execute("SELECT kind FROM executions WHERE id = 1")
        assert cursor.fetchone()[0] == "job"
    finally:
        conn.close()


def test_fk_mutex_check_rejects_both_null(tmp_path: Path) -> None:
    """CHECK constraint rejects rows with both listener_id and job_id NULL."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO executions "
                "(kind, listener_id, job_id, session_id, execution_start_ts, duration_ms, status, source_tier) "
                "VALUES ('handler', NULL, NULL, 1, 1.0, 5.0, 'success', 'app')"
            )
    finally:
        conn.close()


def test_fk_mutex_check_rejects_both_set(tmp_path: Path) -> None:
    """CHECK constraint rejects rows with both listener_id and job_id set."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
        conn.execute(
            "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
            " VALUES ('app', 0, 'my_listener', 'on_x', 'light.x', 'app.py:1')"
        )
        conn.execute(
            "INSERT INTO scheduled_jobs "
            "(app_key, instance_index, job_name, handler_method, source_location, source_tier)"
            " VALUES ('app', 0, 'my_job', 'on_x', 'app.py:1', 'app')"
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO executions "
                "(kind, listener_id, job_id, session_id, execution_start_ts, duration_ms, status, source_tier) "
                "VALUES ('handler', 1, 1, 1, 1.0, 5.0, 'success', 'app')"
            )
    finally:
        conn.close()


def test_listeners_natural_key_unique_index(tmp_path: Path) -> None:
    """idx_listeners_natural is on (app_key, instance_index, name, topic) with no WHERE filter."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_listeners_natural'")
        row = cursor.fetchone()
    finally:
        conn.close()

    assert row is not None, "idx_listeners_natural index not found"
    index_sql = row[0].lower()

    # Must include name and topic
    assert "name" in index_sql
    assert "topic" in index_sql

    # Must NOT have a WHERE clause (once-listeners now participate in upsert)
    assert "where" not in index_sql

    # Must NOT include handler_method or coalesce in the key
    assert "handler_method" not in index_sql
    assert "coalesce" not in index_sql
