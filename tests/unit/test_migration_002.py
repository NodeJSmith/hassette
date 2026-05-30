"""Smoke test for scheduled_jobs schema in 001.sql.

Migration 002 (trigger_label/trigger_detail/trigger_type CHECK) is now part of
the initial 001.sql schema. These tests verify the corresponding schema behaviour.
"""

import sqlite3
from pathlib import Path

import pytest

from hassette.core.migration_runner import run_migrations


class TestScheduledJobsSchema:
    def test_migration_creates_trigger_columns(self, tmp_path: Path) -> None:
        """001.sql includes trigger_label and trigger_detail columns in scheduled_jobs."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(scheduled_jobs)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "trigger_label" in columns, "trigger_label column missing from scheduled_jobs"
            assert "trigger_detail" in columns, "trigger_detail column missing from scheduled_jobs"
        finally:
            conn.close()

    def test_insert_with_known_trigger_type_succeeds(self, tmp_path: Path) -> None:
        """INSERT with a known trigger_type value must succeed."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
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

    def test_rejects_unknown_trigger_type(self, tmp_path: Path) -> None:
        """CHECK constraint on trigger_type rejects unknown values."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

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

    def test_trigger_label_defaults_to_empty_string(self, tmp_path: Path) -> None:
        """trigger_label defaults to empty string when not supplied explicitly."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

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
