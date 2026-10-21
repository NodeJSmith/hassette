"""Tests for migration 014: drop app_manifests.auto_loaded."""

from pathlib import Path

from hassette.core.migration_runner import run_migrations
from tests.support.sql import sqlite_conn


def test_autodetected_manifest_row_survives_the_column_drop(tmp_path: Path) -> None:
    """A row an autodetected app wrote at 013 keeps its identity at 014, minus auto_loaded."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=13)
    with sqlite_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO app_manifests (app_key, class_name, display_name, filename, enabled, autostart, auto_loaded) "
            "VALUES ('apps.my_app.LightsApp', 'LightsApp', 'Lights', 'my_app.py', 0, 1, 1)"
        )
        conn.commit()

    run_migrations(db_path)

    with sqlite_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT app_key, class_name, display_name, filename, enabled, autostart FROM app_manifests"
        ).fetchall()
        dropped = conn.execute("SELECT 1 FROM pragma_table_info('app_manifests') WHERE name = 'auto_loaded'")
        assert dropped.fetchone() is None

    assert rows == [("apps.my_app.LightsApp", "LightsApp", "Lights", "my_app.py", 0, 1)]
