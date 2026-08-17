"""Smoke test for scheduled_jobs schema in 001.sql.

Migration 002 (trigger_label/trigger_detail/trigger_type CHECK) is now part of
the initial 001.sql schema. These tests verify the corresponding schema behaviour.
"""

import sqlite3
from pathlib import Path

import pytest

from hassette.core.migration_runner import run_migrations
from hassette.test_utils.sql_helpers import sqlite_conn


class TestScheduledJobsSchema:
    def test_migration_creates_trigger_columns(self, tmp_path: Path) -> None:
        """001.sql includes trigger_label and trigger_detail columns in scheduled_jobs."""
        # dup-ignore-start: the "db_path = tmp_path / 'test.db'; run_migrations(db_path); with
        # sqlite_conn(db_path) as conn:" setup below is mechanical boilerplate, but its duplicate
        # occurrences pair with tests/unit/core/test_migration_runner.py and
        # tests/unit/test_schema_migration.py — different test directories. Extraction would need
        # a shared helper module spanning tests/unit/core/ and tests/unit/, out of scope for this
        # cluster (see design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs. annotate"
        # worked example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(scheduled_jobs)")
            # dup-ignore-end
            columns = {row[1] for row in cursor.fetchall()}
            assert "trigger_label" in columns, "trigger_label column missing from scheduled_jobs"
            assert "trigger_detail" in columns, "trigger_detail column missing from scheduled_jobs"

    def test_insert_with_known_trigger_type_succeeds(self, tmp_path: Path) -> None:
        """INSERT with a known trigger_type value must succeed."""
        # dup-ignore-start: the "db_path = tmp_path / 'test.db'; run_migrations(db_path); with
        # sqlite_conn(db_path) as conn:" setup below is mechanical boilerplate shared between
        # tests/unit/test_migration_002.py (trigger_type/trigger_label CHECK-constraint coverage)
        # and tests/unit/test_schema_migration.py (broader schema/migration behavior) — two
        # independently scoped test modules. Extraction would require a shared fixture spanning
        # both modules for a 3-line setup, out of scope for this cluster (see
        # design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs. annotate" worked
        # example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_jobs (
                    app_key, instance_index, job_name, handler_method,
                    trigger_type, trigger_label,
                    args_json, kwargs_json, source_location, source_tier, schedule_status
                ) VALUES (
                    'my_app', 0, 'my_job', 'my_app.MyApp.my_handler',
                    'once', 'once',
                    '[]', '{}', 'app.py:10', 'app', 'scheduled'
                )
                """
            )
            # dup-ignore-end
            conn.commit()

            cursor = conn.execute("SELECT trigger_label, trigger_detail FROM scheduled_jobs WHERE job_name = 'my_job'")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "once"
            assert row[1] is None

    def test_rejects_unknown_trigger_type(self, tmp_path: Path) -> None:
        """CHECK constraint on trigger_type rejects unknown values."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_jobs (
                    app_key, instance_index, job_name, handler_method,
                    trigger_type, trigger_label,
                    args_json, kwargs_json, source_location, source_tier, schedule_status
                ) VALUES (
                    'my_app', 0, 'bad_job', 'my_app.MyApp.my_handler',
                    'unknown_type', '',
                    '[]', '{}', 'app.py:10', 'app', 'scheduled'
                )
                """
            )

    def test_trigger_label_defaults_to_empty_string(self, tmp_path: Path) -> None:
        """trigger_label defaults to empty string when not supplied explicitly."""
        # dup-ignore-start: same cross-module boilerplate rationale as
        # test_insert_with_known_trigger_type_succeeds() above.
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_jobs (
                    app_key, instance_index, job_name, handler_method,
                    args_json, kwargs_json, source_location, source_tier, schedule_status
                ) VALUES (
                    'my_app', 0, 'default_job', 'my_app.MyApp.my_handler',
                    '[]', '{}', 'app.py:20', 'app', 'scheduled'
                )
                """
            )
            # dup-ignore-end
            conn.commit()

            cursor = conn.execute("SELECT trigger_label FROM scheduled_jobs WHERE job_name = 'default_job'")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == ""
