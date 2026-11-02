"""Tests for migration 019: log_records rows at a non-standard level become INFO."""

from pathlib import Path

from hassette.core.migration_runner import run_migrations
from tests.support.sql import sqlite_conn

PRE_019_VERSION = 18

# (stored level, level after the migration)
LEVELS = [
    ("TRACE", "INFO"),
    ("SUCCESS", "INFO"),
    ("Level 35", "INFO"),
    ("DEBUG", "DEBUG"),
    ("INFO", "INFO"),
    ("WARNING", "WARNING"),
    ("ERROR", "ERROR"),
    ("CRITICAL", "CRITICAL"),
]


def test_only_non_standard_levels_are_rewritten(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=PRE_019_VERSION)
    with sqlite_conn(db_path) as conn:
        conn.executemany(
            "INSERT INTO log_records (seq, timestamp, level, logger_name, message, author) "
            "VALUES (?, 0.0, ?, 'x', 'line', 'app')",
            [(seq, stored) for seq, (stored, _) in enumerate(LEVELS)],
        )
        conn.commit()

    run_migrations(db_path)

    with sqlite_conn(db_path) as conn:
        rows = conn.execute("SELECT level FROM log_records ORDER BY seq").fetchall()
    assert [level for (level,) in rows] == [expected for _, expected in LEVELS]
