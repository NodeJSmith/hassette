"""Tests for the schema migration (001_initial_schema) and related components."""

import asyncio
import sqlite3
from pathlib import Path
from typing import get_args
from unittest.mock import MagicMock, patch

import pytest

from hassette.config.config import HassetteConfig
from hassette.core.database_service import DatabaseService
from hassette.types.types import SourceTier

# ---------------------------------------------------------------------------
# SourceTier type tests
# ---------------------------------------------------------------------------


class TestSourceTierType:
    def test_source_tier_type_is_literal(self) -> None:
        """SourceTier must be Literal['app', 'framework']."""
        args = get_args(SourceTier)
        assert set(args) == {"app", "framework"}


# ---------------------------------------------------------------------------
# Helpers for running the migration against in-memory / temp DBs
# ---------------------------------------------------------------------------


def _run_migrations_to_head(db_path: str) -> None:
    """Run Alembic migrations to HEAD against the given DB path."""
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).parent.parent.parent / "src" / "hassette" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")


def _get_db_version(db_path: str) -> str | None:
    """Return the current Alembic version from the DB, or None if not set."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            return ctx.get_current_revision()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Migration schema tests
# ---------------------------------------------------------------------------


class TestFreshMigration:
    def test_fresh_migration_creates_all_tables(self, tmp_path: Path) -> None:
        """Running the migration creates all 5 required tables."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {row[0] for row in cursor.fetchall() if not row[0].startswith("alembic")}
        finally:
            conn.close()

        expected = {"sessions", "listeners", "scheduled_jobs", "handler_invocations", "job_executions"}
        assert expected.issubset(tables)

    def test_all_tables_have_source_tier_column(self, tmp_path: Path) -> None:
        """All 5 tables must have a source_tier column."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            for table in ("sessions", "listeners", "scheduled_jobs", "handler_invocations", "job_executions"):
                cursor = conn.execute(f"PRAGMA table_info({table})")
                cols = {row[1] for row in cursor.fetchall()}
                assert "source_tier" in cols, f"source_tier missing from {table}"
        finally:
            conn.close()

    def test_handler_invocations_has_is_di_failure(self, tmp_path: Path) -> None:
        """handler_invocations must have is_di_failure column."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(handler_invocations)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "is_di_failure" in cols
        finally:
            conn.close()

    def test_job_executions_has_is_di_failure(self, tmp_path: Path) -> None:
        """job_executions must have is_di_failure column."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(job_executions)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "is_di_failure" in cols
        finally:
            conn.close()

    def test_check_constraints_reject_invalid_status_handler_invocations(self, tmp_path: Path) -> None:
        """handler_invocations with invalid status raises IntegrityError."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            # Insert a valid session first
            conn.execute(
                "INSERT INTO sessions (started_at, last_heartbeat_at, status, source_tier) "
                "VALUES (1.0, 1.0, 'running', 'framework')"
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO handler_invocations "
                    "(session_id, execution_start_ts, duration_ms, status, source_tier) "
                    "VALUES (1, 1.0, 10.0, 'invalid', 'app')"
                )
        finally:
            conn.close()

    def test_check_constraints_reject_negative_duration(self, tmp_path: Path) -> None:
        """handler_invocations with negative duration_ms raises IntegrityError."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO sessions (started_at, last_heartbeat_at, status, source_tier) "
                "VALUES (1.0, 1.0, 'running', 'framework')"
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO handler_invocations "
                    "(session_id, execution_start_ts, duration_ms, status, source_tier) "
                    "VALUES (1, 1.0, -1.0, 'success', 'app')"
                )
        finally:
            conn.close()

    def test_check_constraints_reject_invalid_source_tier(self, tmp_path: Path) -> None:
        """handler_invocations with invalid source_tier raises IntegrityError."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO sessions (started_at, last_heartbeat_at, status, source_tier) "
                "VALUES (1.0, 1.0, 'running', 'framework')"
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO handler_invocations "
                    "(session_id, execution_start_ts, duration_ms, status, source_tier) "
                    "VALUES (1, 1.0, 10.0, 'success', 'invalid')"
                )
        finally:
            conn.close()

    def test_nullable_listener_id_allows_null(self, tmp_path: Path) -> None:
        """handler_invocations must allow NULL listener_id."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO sessions (started_at, last_heartbeat_at, status, source_tier) "
                "VALUES (1.0, 1.0, 'running', 'framework')"
            )
            conn.commit()
            conn.execute(
                "INSERT INTO handler_invocations "
                "(listener_id, session_id, execution_start_ts, duration_ms, status, source_tier) "
                "VALUES (NULL, 1, 1.0, 10.0, 'success', 'framework')"
            )
            conn.commit()
            cursor = conn.execute("SELECT listener_id FROM handler_invocations WHERE id = 1")
            row = cursor.fetchone()
            assert row[0] is None
        finally:
            conn.close()

    def test_views_filter_by_tier(self, tmp_path: Path) -> None:
        """Views active_app_listeners and active_framework_listeners filter by source_tier."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            # Insert one app-tier listener and one framework-tier listener
            conn.execute(
                "INSERT INTO listeners "
                "(app_key, instance_index, handler_method, topic, source_location, source_tier) "
                "VALUES ('my_app', 0, 'on_state', 'state_changed', 'app.py:10', 'app')"
            )
            conn.execute(
                "INSERT INTO listeners "
                "(app_key, instance_index, handler_method, topic, source_location, source_tier) "
                "VALUES ('framework', 0, 'on_event', 'all', 'core.py:5', 'framework')"
            )
            conn.commit()

            # active_app_listeners should only have the app-tier one
            cursor = conn.execute("SELECT source_tier FROM active_app_listeners")
            tiers = [row[0] for row in cursor.fetchall()]
            assert tiers == ["app"]

            # active_framework_listeners should only have the framework-tier one
            cursor = conn.execute("SELECT source_tier FROM active_framework_listeners")
            tiers = [row[0] for row in cursor.fetchall()]
            assert tiers == ["framework"]

            # active_listeners (backward compat) should have both
            cursor = conn.execute("SELECT source_tier FROM active_listeners ORDER BY source_tier")
            tiers = [row[0] for row in cursor.fetchall()]
            assert tiers == ["app", "framework"]
        finally:
            conn.close()

    def test_sessions_defaults_source_tier_to_framework(self, tmp_path: Path) -> None:
        """sessions table should default source_tier to 'framework'."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.commit()
            cursor = conn.execute("SELECT source_tier FROM sessions WHERE id = 1")
            row = cursor.fetchone()
            assert row[0] == "framework"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# DatabaseService version mismatch tests
# ---------------------------------------------------------------------------


class TestDbVersionMismatch:
    def test_db_version_mismatch_recreates(self, tmp_path: Path) -> None:
        """When DB version != expected head, DatabaseService deletes and recreates the DB."""
        db_path = tmp_path / "test.db"
        db_path.touch()  # Simulate existing DB file

        hassette_mock = MagicMock()
        hassette_mock.config.db_path = db_path
        hassette_mock.config.data_dir = tmp_path
        hassette_mock.config.database_service_log_level = "INFO"
        hassette_mock.config.db_migration_timeout_seconds = 30

        svc = DatabaseService.__new__(DatabaseService)
        svc._db = None
        svc._db_path = db_path
        svc._consecutive_heartbeat_failures = 0
        svc._consecutive_size_triggers = 0
        svc._db_write_queue = None
        svc._db_worker_task = None
        svc.hassette = hassette_mock
        svc.logger = MagicMock()

        with (
            patch.object(DatabaseService, "_get_current_db_revision", return_value="000"),
            patch.object(DatabaseService, "_get_expected_head_revision", return_value="001"),
        ):
            asyncio.run(svc._handle_schema_version(db_path))
            # DB file should have been deleted (on_initialize handles re-running migrations)
            assert not db_path.exists()

    def test_db_version_ahead_halts_startup(self, tmp_path: Path) -> None:
        """When DB version is ahead of head, startup raises RuntimeError."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        hassette_mock = MagicMock()
        hassette_mock.config.db_path = db_path
        hassette_mock.config.data_dir = tmp_path
        hassette_mock.config.database_service_log_level = "INFO"

        svc = DatabaseService.__new__(DatabaseService)
        svc._db = None
        svc._db_path = db_path
        svc._consecutive_heartbeat_failures = 0
        svc._consecutive_size_triggers = 0
        svc._db_write_queue = None
        svc._db_worker_task = None
        svc.hassette = hassette_mock
        svc.logger = MagicMock()

        # DB has revision 002, but code only knows about 001
        with (
            patch.object(DatabaseService, "_get_current_db_revision", return_value="002"),
            patch.object(DatabaseService, "_get_expected_head_revision", return_value="001"),
            pytest.raises(RuntimeError, match="ahead"),
        ):
            asyncio.run(svc._handle_schema_version(db_path))


# ---------------------------------------------------------------------------
# Config field test
# ---------------------------------------------------------------------------


class TestHassetteConfigTelemetryQueueMax:
    def test_telemetry_write_queue_max_default(self) -> None:
        """HassetteConfig.telemetry_write_queue_max defaults to 1000."""
        config = HassetteConfig(token="test-token", _cli_parse_args=False)
        assert config.telemetry_write_queue_max == 1000
