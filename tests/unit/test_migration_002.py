"""Smoke test for migration 002_scheduler_api_redesign.

Verifies that:
- The migration runs cleanly against an in-memory SQLite database.
- ``trigger_label`` and ``trigger_detail`` columns are present in ``scheduled_jobs``.
- An INSERT with ``trigger_type='once'`` succeeds (CHECK constraint accepts known values).
"""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def _run_migrations_to_head(db_path: str) -> None:
    """Run Alembic migrations up to HEAD against the given SQLite DB path."""
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).parent.parent.parent / "src" / "hassette" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")


class TestMigration002:
    def test_migration_002_upgrades(self, tmp_path: Path) -> None:
        """Migration 002 runs cleanly and adds trigger_label/trigger_detail columns."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(scheduled_jobs)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "trigger_label" in columns, "trigger_label column missing from scheduled_jobs"
            assert "trigger_detail" in columns, "trigger_detail column missing from scheduled_jobs"

            # An INSERT with a known trigger_type value must succeed.
            conn.execute(
                """
                INSERT INTO scheduled_jobs (
                    app_key, instance_index, job_name, handler_method,
                    trigger_type, trigger_label,
                    args_json, kwargs_json, source_location, source_tier
                ) VALUES (
                    'my_app', 0, 'my_job', 'my_app.MyApp.my_handler',
                    'once', 'once',
                    '[]', '{}', 'app.py:10', 'app'
                )
                """
            )
            conn.commit()

            cursor = conn.execute("SELECT trigger_label, trigger_detail FROM scheduled_jobs WHERE job_name = 'my_job'")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "once"
            assert row[1] is None
        finally:
            conn.close()

    def test_migration_002_rejects_unknown_trigger_type(self, tmp_path: Path) -> None:
        """Migration 002 CHECK constraint rejects trigger_type values not in the allowed set."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO scheduled_jobs (
                        app_key, instance_index, job_name, handler_method,
                        trigger_type, trigger_label,
                        args_json, kwargs_json, source_location, source_tier
                    ) VALUES (
                        'my_app', 0, 'bad_job', 'my_app.MyApp.my_handler',
                        'unknown_type', '',
                        '[]', '{}', 'app.py:10', 'app'
                    )
                    """
                )
        finally:
            conn.close()

    def test_migration_002_trigger_label_defaults_to_empty_string(self, tmp_path: Path) -> None:
        """trigger_label defaults to empty string when not supplied explicitly."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                INSERT INTO scheduled_jobs (
                    app_key, instance_index, job_name, handler_method,
                    args_json, kwargs_json, source_location, source_tier
                ) VALUES (
                    'my_app', 0, 'default_job', 'my_app.MyApp.my_handler',
                    '[]', '{}', 'app.py:20', 'app'
                )
                """
            )
            conn.commit()

            cursor = conn.execute("SELECT trigger_label FROM scheduled_jobs WHERE job_name = 'default_job'")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == ""
        finally:
            conn.close()
