"""Tests for migration 018: listeners and scheduled_jobs keyed by instance_name instead of instance_index.

Pre-migration app-tier rows can't be attributed to a name, so they retire under a placeholder. Framework rows
are named in place and keep their history. Parents are altered in place, so executions keep their foreign keys.
"""

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from hassette.core.migration_runner import run_migrations
from hassette.types.types import FRAMEWORK_APP_KEY
from tests.support.factories import TEST_SOURCE_LOCATION
from tests.support.sql import insert_execution_row, sqlite_conn

REGISTRATION_TABLES = ("listeners", "scheduled_jobs")
FRAMEWORK_KEY = f"{FRAMEWORK_APP_KEY}.BusService"
EARLIER_RETIREMENT = 100.0


def insert_listener(
    conn: sqlite3.Connection, app_key: str, index: int, tier: str = "app", retired_at: float | None = None
) -> None:
    conn.execute(
        "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location, source_tier, "
        "retired_at) VALUES (?, ?, 'shared_name', 'on_x', 'light.kitchen', ?, ?, ?)",
        (app_key, index, TEST_SOURCE_LOCATION, tier, retired_at),
    )


def insert_job(
    conn: sqlite3.Connection, app_key: str, index: int, tier: str = "app", retired_at: float | None = None
) -> None:
    conn.execute(
        "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, source_location, source_tier, "
        "retired_at, schedule_status) VALUES (?, ?, 'shared_job', 'do_thing', ?, ?, ?, 'scheduled')",
        (app_key, index, TEST_SOURCE_LOCATION, tier, retired_at),
    )


@pytest.fixture
def migrated_db(tmp_path: Path) -> Path:
    """Two sibling app instances sharing a name and topic, a framework resource, and history on each."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=17)
    with sqlite_conn(db_path) as conn:
        conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
        for insert in (insert_listener, insert_job):
            insert(conn, "my_app", 0)
            insert(conn, "my_app", 1)
            insert(conn, "my_app", 2, retired_at=EARLIER_RETIREMENT)
            insert(conn, FRAMEWORK_KEY, 0, tier="framework")
        conn.commit()
        insert_execution_row(conn, kind="handler", listener_id=1, session_id=1, execution_start_ts=1.0, duration_ms=1.0)
        insert_execution_row(conn, kind="job", job_id=4, session_id=1, execution_start_ts=2.0, duration_ms=1.0)
        conn.commit()
    run_migrations(db_path)
    return db_path


@pytest.mark.parametrize("table", REGISTRATION_TABLES)
def test_app_rows_retire_under_distinct_legacy_names(migrated_db: Path, table: str) -> None:
    """Siblings can share a natural key apart from the index, so the placeholder keeps the index."""
    with sqlite_conn(migrated_db) as conn:
        rows = conn.execute(
            f"SELECT instance_name, retired_at FROM {table} WHERE app_key = 'my_app' ORDER BY instance_index"
        ).fetchall()

    assert [row[0] for row in rows] == ["__legacy__.0", "__legacy__.1", "__legacy__.2"]
    assert all(row[1] is not None for row in rows)


@pytest.mark.parametrize("table", REGISTRATION_TABLES)
def test_earlier_retirement_time_is_kept(migrated_db: Path, table: str) -> None:
    with sqlite_conn(migrated_db) as conn:
        row = conn.execute(f"SELECT retired_at FROM {table} WHERE instance_index = 2").fetchone()

    assert row[0] == EARLIER_RETIREMENT


@pytest.mark.parametrize("table", REGISTRATION_TABLES)
def test_framework_rows_are_named_in_place_and_stay_active(migrated_db: Path, table: str) -> None:
    with sqlite_conn(migrated_db) as conn:
        row = conn.execute(f"SELECT instance_name, retired_at FROM {table} WHERE source_tier = 'framework'").fetchone()

    assert row[0] == FRAMEWORK_APP_KEY
    assert row[1] is None


@pytest.mark.parametrize("table", REGISTRATION_TABLES)
def test_no_row_keeps_the_unset_default(migrated_db: Path, table: str) -> None:
    with sqlite_conn(migrated_db) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE instance_name = '__unset__'").fetchone()[0] == 0


@pytest.mark.parametrize("table", REGISTRATION_TABLES)
def test_instance_name_refuses_an_explicit_null(migrated_db: Path, table: str) -> None:
    """A NULL name would never hit ON CONFLICT, so every restart would insert a duplicate row."""
    with sqlite_conn(migrated_db) as conn, pytest.raises(sqlite3.IntegrityError, match="instance_name"):
        conn.execute(f"UPDATE {table} SET instance_name = NULL WHERE source_tier = 'framework'")


def test_executions_keep_their_parents(migrated_db: Path) -> None:
    with sqlite_conn(migrated_db, foreign_keys=True) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute(
            "SELECT l.instance_name FROM executions e JOIN listeners l ON l.id = e.listener_id"
        ).fetchone() == ("__legacy__.0",)
        assert conn.execute(
            "SELECT sj.instance_name FROM executions e JOIN scheduled_jobs sj ON sj.id = e.job_id"
        ).fetchone() == (FRAMEWORK_APP_KEY,)


@pytest.mark.parametrize(
    ("index_name", "columns"),
    [
        ("idx_listeners_natural", ["app_key", "instance_name", "name", "topic"]),
        ("idx_scheduled_jobs_natural", ["app_key", "instance_name", "job_name"]),
        ("idx_listeners_app", ["app_key", "instance_name"]),
        ("idx_scheduled_jobs_app", ["app_key", "instance_name"]),
    ],
)
def test_indexes_key_on_the_name(migrated_db: Path, index_name: str, columns: list[str]) -> None:
    with sqlite_conn(migrated_db) as conn:
        assert [row[2] for row in conn.execute(f"PRAGMA index_info({index_name})").fetchall()] == columns


@pytest.mark.parametrize(("table", "insert"), [("listeners", insert_listener), ("scheduled_jobs", insert_job)])
def test_framework_rows_differing_only_by_index_fail_atomically(
    tmp_path: Path, table: str, insert: Callable[..., None]
) -> None:
    """Naming framework rows in place assumes they sit at index 0, so two at different indexes must fail the upgrade.

    The failure is intended: startup stops loudly and the database stays at schema version 17, with nothing half-done.
    """
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=17)
    with sqlite_conn(db_path) as conn:
        insert(conn, FRAMEWORK_KEY, 0, tier="framework")
        insert(conn, FRAMEWORK_KEY, 1, tier="framework")
        conn.commit()

    with pytest.raises(RuntimeError, match="Migration 18"):
        run_migrations(db_path)

    with sqlite_conn(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (17,)
        assert conn.execute(f"SELECT instance_index FROM {table} ORDER BY instance_index").fetchall() == [(0,), (1,)]
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    assert "instance_name" not in columns
