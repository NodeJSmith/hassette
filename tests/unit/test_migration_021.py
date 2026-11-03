"""Tests for migration 021: a nullable description column on app_manifests."""

from pathlib import Path

from hassette.core.migration_runner import run_migrations
from tests.support.sql import sqlite_conn


def test_existing_manifest_rows_get_a_null_description(tmp_path: Path) -> None:
    """A manifest row written before 021 survives the migration with no description."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=20)  # the schema just before 021
    with sqlite_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO app_manifests (app_key, class_name, display_name, filename) VALUES (?, ?, ?, ?)",
            ("porch_light", "PorchLight", "Porch Light", "porch_light.py"),
        )
        conn.commit()

    run_migrations(db_path)

    with sqlite_conn(db_path) as conn:
        row = conn.execute("SELECT app_key, description FROM app_manifests").fetchone()
    assert tuple(row) == ("porch_light", None)
