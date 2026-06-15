"""Tests for the migration runner and schema produced by 001.sql."""

import sqlite3
from pathlib import Path
from typing import get_args
from unittest.mock import MagicMock, patch

import pytest

from hassette.config.config import HassetteConfig
from hassette.core.database_service import DatabaseService
from hassette.core.migration_runner import run_migrations
from hassette.test_utils.config import TEST_TOKEN
from hassette.types.types import SourceTier


class TestSourceTierType:
    def test_source_tier_type_is_literal(self) -> None:
        """SourceTier must be Literal['app', 'framework']."""
        args = get_args(SourceTier)
        assert set(args) == {"app", "framework"}


class TestFreshMigration:
    def test_fresh_migration_creates_all_tables(self, tmp_path: Path) -> None:
        """Running the migration creates all required tables."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

        expected = {"sessions", "listeners", "scheduled_jobs", "executions", "log_records"}
        assert expected.issubset(tables)

    def test_all_tables_have_source_tier_column(self, tmp_path: Path) -> None:
        """listeners, scheduled_jobs, executions, log_records all have a source_tier column."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            for table in ("listeners", "scheduled_jobs", "executions"):
                cursor = conn.execute(f"PRAGMA table_info({table})")
                cols = {row[1] for row in cursor.fetchall()}
                assert "source_tier" in cols, f"source_tier missing from {table}"
        finally:
            conn.close()

    def test_executions_has_kind_column(self, tmp_path: Path) -> None:
        """executions table has kind column."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(executions)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "kind" in cols
        finally:
            conn.close()

    def test_executions_has_is_di_failure(self, tmp_path: Path) -> None:
        """executions table has is_di_failure column."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(executions)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "is_di_failure" in cols
        finally:
            conn.close()

    def test_check_constraints_reject_invalid_status(self, tmp_path: Path) -> None:
        """executions with invalid status raises IntegrityError."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
                " VALUES ('app', 0, 'my_listener', 'on_x', 'light.kitchen', 'app.py:1')"
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO executions "
                    "(kind, listener_id, session_id, execution_start_ts, duration_ms, status, source_tier) "
                    "VALUES ('handler', 1, 1, 1.0, 10.0, 'invalid', 'app')"
                )
        finally:
            conn.close()

    def test_check_constraints_reject_negative_duration(self, tmp_path: Path) -> None:
        """executions with negative duration_ms raises IntegrityError."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
                " VALUES ('app', 0, 'my_listener', 'on_x', 'light.kitchen', 'app.py:1')"
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO executions "
                    "(kind, listener_id, session_id, execution_start_ts, duration_ms, status, source_tier) "
                    "VALUES ('handler', 1, 1, 1.0, -1.0, 'success', 'app')"
                )
        finally:
            conn.close()

    def test_nullable_listener_id_allows_null(self, tmp_path: Path) -> None:
        """executions must allow NULL listener_id when job_id is set."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.execute(
                "INSERT INTO scheduled_jobs "
                "(app_key, instance_index, job_name, handler_method, source_location, source_tier)"
                " VALUES ('app', 0, 'my_job', 'on_x', 'app.py:1', 'app')"
            )
            conn.commit()
            conn.execute(
                "INSERT INTO executions "
                "(kind, job_id, session_id, execution_start_ts, duration_ms, status, source_tier) "
                "VALUES ('job', 1, 1, 1.0, 10.0, 'success', 'app')"
            )
            conn.commit()
            cursor = conn.execute("SELECT listener_id FROM executions WHERE id = 1")
            row = cursor.fetchone()
            assert row[0] is None
        finally:
            conn.close()

    def test_sessions_drop_counters_default_to_zero(self, tmp_path: Path) -> None:
        """sessions table defaults drop counters to 0."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.commit()
            cursor = conn.execute(
                "SELECT dropped_overflow, dropped_exhausted, dropped_shutdown FROM sessions WHERE id = 1"
            )
            row = cursor.fetchone()
            assert row == (0, 0, 0)
        finally:
            conn.close()

    def test_sessions_has_no_dropped_no_session_column(self, tmp_path: Path) -> None:
        """sessions table does NOT have dropped_no_session (removed in new schema)."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(sessions)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "dropped_no_session" not in cols
        finally:
            conn.close()

    def test_views_filter_by_tier(self, tmp_path: Path) -> None:
        """Views active_app_listeners and active_framework_listeners filter by source_tier."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO listeners "
                "(app_key, instance_index, name, handler_method, topic, source_location, source_tier) "
                "VALUES ('my_app', 0, 'app_listener', 'on_state', 'state_changed', 'app.py:10', 'app')"
            )
            conn.execute(
                "INSERT INTO listeners "
                "(app_key, instance_index, name, handler_method, topic, source_location, source_tier) "
                "VALUES ('__hassette__', 0, 'fw_listener', 'on_event', 'all', 'core.py:5', 'framework')"
            )
            conn.commit()

            cursor = conn.execute("SELECT source_tier FROM active_app_listeners")
            tiers = [row[0] for row in cursor.fetchall()]
            assert tiers == ["app"]

            cursor = conn.execute("SELECT source_tier FROM active_framework_listeners")
            tiers = [row[0] for row in cursor.fetchall()]
            assert tiers == ["framework"]

            cursor = conn.execute("SELECT source_tier FROM active_listeners ORDER BY source_tier")
            tiers = [row[0] for row in cursor.fetchall()]
            assert tiers == ["app", "framework"]
        finally:
            conn.close()

    def test_user_version_set_after_migration(self, tmp_path: Path) -> None:
        """PRAGMA user_version is 3 after all migrations run."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()

        assert version == 3

    def test_listeners_has_mode_column_default_single(self, tmp_path: Path) -> None:
        """003.sql adds a mode column to listeners defaulting to 'single'."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(listeners)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "mode" in cols

            conn.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
                " VALUES ('app', 0, 'my_listener', 'on_x', 'light.kitchen', 'app.py:1')"
            )
            conn.commit()
            row = conn.execute("SELECT mode FROM listeners WHERE name = 'my_listener'").fetchone()
            assert row[0] == "single"
        finally:
            conn.close()


class TestDbVersionMismatch:
    def test_db_version_mismatch_recreates(self, tmp_path: Path) -> None:
        """When DB version != expected head, DatabaseService deletes and recreates the DB."""
        import asyncio

        db_path = tmp_path / "test.db"
        db_path.touch()  # Simulate existing DB file

        hassette_mock = MagicMock()
        hassette_mock.config.database.path = db_path
        hassette_mock.config.data_dir = tmp_path
        hassette_mock.config.logging.database_service = "INFO"
        hassette_mock.config.database.migration_timeout_seconds = 30

        svc = DatabaseService.__new__(DatabaseService)
        svc._db = None
        svc._read_db = None
        svc._db_path = db_path
        svc._consecutive_heartbeat_failures = 0
        svc._consecutive_size_triggers = 0
        svc._db_write_queue = None
        svc._db_worker_task = None
        svc.hassette = hassette_mock
        svc.logger = MagicMock()

        with (
            patch.object(DatabaseService, "_get_current_db_version", return_value=0),
            patch.object(DatabaseService, "_get_expected_head_version", return_value=1),
        ):
            asyncio.run(svc._handle_schema_version(db_path))
            # DB file should have been deleted (on_initialize handles re-running migrations)
            assert not db_path.exists()


class TestHassetteConfigTelemetryQueueMax:
    def test_telemetry_write_queue_max_default(self) -> None:
        """HassetteConfig.telemetry_write_queue_max defaults to 1000."""
        config = HassetteConfig(token=TEST_TOKEN, _cli_parse_args=False)
        assert config.database.telemetry_write_queue_max == 1000
