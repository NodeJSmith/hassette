"""Tests for migration 020: the instance_index column dropped from every table that held it."""

from pathlib import Path

import pytest

from hassette.core.migration_runner import run_migrations
from tests.support.sql import sqlite_conn

TABLES = ("log_records", "blocking_events", "listeners", "scheduled_jobs")


def columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


@pytest.mark.parametrize("table", TABLES)
def test_the_column_is_gone_and_the_name_stays(tmp_path: Path, table: str) -> None:
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=19)
    with sqlite_conn(db_path) as conn:
        assert "instance_index" in columns(conn, table)

    run_migrations(db_path)

    with sqlite_conn(db_path) as conn:
        after = columns(conn, table)
    assert "instance_index" not in after
    assert "instance_name" in after


def insert_row(conn, table: str, values: dict[str, object]) -> int:
    """Insert a row, giving each NOT NULL column with no default a placeholder of its type."""
    filled = dict(values)
    for _, name, ctype, notnull, default, pk in conn.execute(f"PRAGMA table_info({table})").fetchall():
        if name not in filled and notnull and default is None and not pk:
            filled[name] = 1 if ctype.upper() in ("INTEGER", "REAL") else "x"
    placeholders = ", ".join("?" for _ in filled)
    sql = f"INSERT INTO {table} ({', '.join(filled)}) VALUES ({placeholders})"
    return conn.execute(sql, tuple(filled.values())).lastrowid


@pytest.mark.parametrize("table", TABLES)
def test_rows_survive_the_rewrite_of_every_table(tmp_path: Path, table: str) -> None:
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=19)
    identity = {"app_key": "my_app", "instance_index": 1, "instance_name": "office"}
    with sqlite_conn(db_path) as conn:
        session = insert_row(conn, "sessions", {"status": "stopped"})
        listener = insert_row(conn, "listeners", {**identity, "source_tier": "app"})
        insert_row(conn, "scheduled_jobs", {**identity, "source_tier": "app", "schedule_status": "manual"})
        insert_row(
            conn,
            "executions",
            {"execution_id": "e1", "kind": "handler", "listener_id": listener, "session_id": session}
            | {"source_tier": "app", "status": "success"},
        )
        insert_row(
            conn,
            "blocking_events",
            {**identity, "execution_id": "e1", "session_id": session, "source_tier": "app", "tier": "watchdog"},
        )
        insert_row(conn, "log_records", {**identity, "level": "INFO"})
        conn.commit()

    run_migrations(db_path)

    with sqlite_conn(db_path) as conn:
        rows = conn.execute(f"SELECT app_key, instance_name FROM {table}").fetchall()
        active_listeners = conn.execute("SELECT COUNT(*) FROM active_listeners").fetchone()[0]
    assert [tuple(row) for row in rows] == [("my_app", "office")]
    assert active_listeners == 1
