"""Tests for migration 015: log_records.source_tier -> author, derived for existing rows."""

import sqlite3
from pathlib import Path

import pytest

from hassette.core.migration_runner import run_migrations
from tests.support.sql import sqlite_conn

# (logger_name, instance_name, expected author). The stored source_tier is deliberately the same
# for every row: the migration derives author from the logger name, never from the old value.
LEGACY_ROWS = [
    # v0.59.0 naming: hassette.<Class>.<instance>, or hassette.<instance> when the instance starts with the class name
    ("hassette.MotionLights.motion_lights_0", "motion_lights_0", "app"),
    ("hassette.MotionLights0", "MotionLights0", "app"),
    ("hassette.MotionLights.motion_lights_0.Bus", "motion_lights_0", "framework"),
    ("hassette.MotionLights.motion_lights_0.Scheduler", "motion_lights_0", "framework"),
    # current naming
    ("hassette.apps.motion_lights", "motion_lights", "app"),
    ("hassette.apps.motion_lights.Lifecycle", "motion_lights", "framework"),
    ("hassette.apps.motion_lights.Api", "motion_lights", "framework"),
    # a lowercase instance whose child ends in the capitalized class: exact and case-sensitive
    ("hassette.apps.api.Api", "api", "framework"),
    # `_` is a literal, not a wildcard
    ("hassette.MyApp.myXapp", "my_app", "framework"),
    # outside the hassette namespace
    ("my_package.helpers", "motion_lights", "app"),
    ("py.warnings", None, "app"),
    ("hassettex.module", None, "app"),
    # inside the namespace, no instance
    ("hassette", None, "framework"),
    ("hassette.core.service_watcher", None, "framework"),
]


@pytest.fixture
def migrated(tmp_path: Path) -> Path:
    """A DB with LEGACY_ROWS written at 014, then migrated to head."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=14)
    with sqlite_conn(db_path) as conn:
        conn.executemany(
            "INSERT INTO log_records (seq, timestamp, level, logger_name, message, instance_name, source_tier) "
            "VALUES (?, 0.0, 'INFO', ?, 'line', ?, 'app')",
            [(seq, logger_name, instance_name) for seq, (logger_name, instance_name, _) in enumerate(LEGACY_ROWS)],
        )
        conn.commit()
    run_migrations(db_path)
    return db_path


def test_existing_rows_get_the_derived_author(migrated: Path) -> None:
    with sqlite_conn(migrated) as conn:
        rows = conn.execute("SELECT logger_name, instance_name, author FROM log_records ORDER BY seq").fetchall()

    assert rows == LEGACY_ROWS


def test_source_tier_column_is_dropped(migrated: Path) -> None:
    with sqlite_conn(migrated) as conn:
        dropped = conn.execute("SELECT 1 FROM pragma_table_info('log_records') WHERE name = 'source_tier'")
        assert dropped.fetchone() is None


def test_author_rejects_values_outside_the_vocabulary(migrated: Path) -> None:
    with sqlite_conn(migrated) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO log_records (seq, timestamp, level, logger_name, message, author) "
            "VALUES (99, 0.0, 'INFO', 'x', 'line', 'all')"
        )
