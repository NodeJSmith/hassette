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


def test_existing_rows_and_their_names_survive(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=19)
    with sqlite_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO listeners (app_key, instance_index, instance_name, name, handler_method, topic, "
            "source_location) VALUES ('my_app', 1, 'office', 'l', 'on_x', 'light.x', 'app.py:1')"
        )
        conn.commit()

    run_migrations(db_path)

    with sqlite_conn(db_path) as conn:
        rows = conn.execute("SELECT app_key, instance_name FROM listeners").fetchall()
        assert [tuple(row) for row in rows] == [("my_app", "office")]
        assert conn.execute("SELECT COUNT(*) FROM active_listeners").fetchone()[0] == 1
