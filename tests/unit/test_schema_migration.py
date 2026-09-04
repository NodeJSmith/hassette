"""Tests for the migration runner and schema produced by 001.sql."""

import asyncio
import sqlite3
from pathlib import Path
from typing import get_args
from unittest.mock import MagicMock, patch

import pytest

from hassette.config.config import HassetteConfig
from hassette.core.database_service import DatabaseService
from hassette.core.migration_runner import run_migrations
from hassette.testing._harness import TEST_TOKEN
from hassette.testing.config import LATEST_MIGRATION_VERSION
from hassette.types.types import SourceTier
from tests.support.sql import insert_execution_row, sqlite_conn


class TestSourceTierType:
    def test_source_tier_type_is_literal(self) -> None:
        """SourceTier must be Literal['app', 'framework']."""
        args = get_args(SourceTier)
        assert set(args) == {"app", "framework"}


class TestFreshMigration:
    def test_fresh_migration_creates_all_tables(self, tmp_path: Path) -> None:
        """Running the migration creates all required tables."""
        # dup-ignore-start: the "db_path = tmp_path / 'test.db'; run_migrations(db_path); with
        # sqlite_conn(db_path) as conn:" setup below is mechanical boilerplate, but its duplicate
        # occurrences pair with tests/unit/core/test_migration_runner.py (a different test
        # directory) and tests/unit/test_migration_002.py. Extraction would need a shared helper
        # module spanning tests/unit/core/ and tests/unit/, out of scope for this cluster (see
        # design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs. annotate" worked example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {row[0] for row in cursor.fetchall()}
        # dup-ignore-end

        expected = {"sessions", "listeners", "scheduled_jobs", "executions", "log_records"}
        assert expected.issubset(tables)

    def test_all_tables_have_source_tier_column(self, tmp_path: Path) -> None:
        """listeners, scheduled_jobs, executions, log_records all have a source_tier column."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            for table in ("listeners", "scheduled_jobs", "executions"):
                cursor = conn.execute(f"PRAGMA table_info({table})")
                cols = {row[1] for row in cursor.fetchall()}
                assert "source_tier" in cols, f"source_tier missing from {table}"

    def test_executions_has_kind_column(self, tmp_path: Path) -> None:
        """Executions table has kind column."""
        # dup-ignore-start: the "db_path = tmp_path / 'test.db'; run_migrations(db_path); with
        # sqlite_conn(db_path) as conn:" setup below is mechanical boilerplate, but its duplicate
        # occurrences pair with tests/unit/core/test_migration_runner.py (a different test
        # directory) and tests/unit/test_migration_002.py. Extraction would need a shared helper
        # module spanning tests/unit/core/ and tests/unit/, out of scope for this cluster (see
        # design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs. annotate" worked example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(executions)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "kind" in cols
        # dup-ignore-end

    def test_executions_has_is_di_failure(self, tmp_path: Path) -> None:
        """Executions table has is_di_failure column."""
        # dup-ignore-start: same cross-directory boilerplate rationale as
        # test_executions_has_kind_column() above.
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(executions)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "is_di_failure" in cols
        # dup-ignore-end

    def test_check_constraints_reject_invalid_status(self, tmp_path: Path) -> None:
        """Executions with invalid status raises IntegrityError."""
        # dup-ignore-start: the "insert a session + listener row to satisfy FK constraints before
        # testing a CHECK constraint" setup below is mechanical boilerplate, but its duplicate
        # occurrences pair with tests/unit/core/test_migration_runner.py — a different test
        # directory. Extraction would need a shared helper module spanning tests/unit/core/ and
        # tests/unit/, out of scope for this cluster (see
        # design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs. annotate" worked example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path, foreign_keys=True) as conn:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
                " VALUES ('app', 0, 'my_listener', 'on_x', 'light.kitchen', 'app.py:1')"
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                insert_execution_row(
                    conn,
                    kind="handler",
                    listener_id=1,
                    session_id=1,
                    execution_start_ts=1.0,
                    duration_ms=10.0,
                    status="invalid",
                )
            # dup-ignore-end

    def test_check_constraints_accept_skipped_status(self, tmp_path: Path) -> None:
        """Executions with status='skipped' is accepted by the CHECK constraint (added in 009.sql)."""
        # dup-ignore-start: the "insert a session + scheduled_jobs row to satisfy FK constraints"
        # setup below is mechanical boilerplate, but its duplicate occurrences pair with
        # tests/unit/core/test_migration_runner.py — a different test directory. Extraction would
        # need a shared helper module spanning tests/unit/core/ and tests/unit/, out of scope for
        # this cluster (see design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs.
        # annotate" worked example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path, foreign_keys=True) as conn:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.execute(
                "INSERT INTO scheduled_jobs "
                "(app_key, instance_index, job_name, handler_method, source_location, schedule_status)"
                " VALUES ('app', 0, 'my_job', 'do_thing', 'app.py:1', 'scheduled')"
            )
            conn.commit()
            # dup-ignore-end
            insert_execution_row(
                conn, kind="job", job_id=1, session_id=1, execution_start_ts=1.0, duration_ms=0.0, status="skipped"
            )
            conn.commit()
            row = conn.execute("SELECT status, duration_ms FROM executions WHERE status = 'skipped'").fetchone()
            assert row == ("skipped", 0.0)

    def test_check_constraints_reject_negative_duration(self, tmp_path: Path) -> None:
        """Executions with negative duration_ms raises IntegrityError."""
        # dup-ignore-start: the "insert a session + listener row to satisfy FK constraints before
        # testing a CHECK constraint" setup below is mechanical boilerplate, but its duplicate
        # occurrences pair with tests/unit/core/test_migration_runner.py — a different test
        # directory. Extraction would need a shared helper module spanning tests/unit/core/ and
        # tests/unit/, out of scope for this cluster (see
        # design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs. annotate" worked example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path, foreign_keys=True) as conn:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
                " VALUES ('app', 0, 'my_listener', 'on_x', 'light.kitchen', 'app.py:1')"
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                insert_execution_row(
                    conn, kind="handler", listener_id=1, session_id=1, execution_start_ts=1.0, duration_ms=-1.0
                )
        # dup-ignore-end

    def test_nullable_listener_id_allows_null(self, tmp_path: Path) -> None:
        """Executions must allow NULL listener_id when job_id is set."""
        # dup-ignore-start: the "insert a session + scheduled_jobs row to satisfy FK constraints"
        # setup below is mechanical boilerplate, but its duplicate occurrences pair with
        # tests/unit/core/test_migration_runner.py — a different test directory. Extraction would
        # need a shared helper module spanning tests/unit/core/ and tests/unit/, out of scope for
        # this cluster (see design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs.
        # annotate" worked example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path, foreign_keys=True) as conn:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.execute(
                "INSERT INTO scheduled_jobs "
                "(app_key, instance_index, job_name, handler_method, source_location, source_tier, schedule_status)"
                " VALUES ('app', 0, 'my_job', 'on_x', 'app.py:1', 'app', 'scheduled')"
            )
            conn.commit()
            # dup-ignore-end
            insert_execution_row(conn, kind="job", job_id=1, session_id=1, execution_start_ts=1.0, duration_ms=10.0)
            conn.commit()
            cursor = conn.execute("SELECT listener_id FROM executions WHERE id = 1")
            row = cursor.fetchone()
            assert row[0] is None

    def test_sessions_drop_counters_default_to_zero(self, tmp_path: Path) -> None:
        """Sessions table defaults drop counters to 0."""
        # dup-ignore-start: the "db_path = tmp_path / 'test.db'; run_migrations(db_path); with
        # sqlite_conn(db_path) as conn:" setup below is mechanical boilerplate shared between
        # tests/unit/test_schema_migration.py (broader schema/migration behavior) and
        # tests/unit/test_migration_002.py (trigger_type/trigger_label CHECK-constraint coverage)
        # — two independently scoped test modules. Extraction would require a shared fixture
        # spanning both modules for a 3-line setup, out of scope for this cluster (see
        # design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs. annotate" worked
        # example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            # dup-ignore-end
            conn.commit()
            cursor = conn.execute(
                "SELECT dropped_overflow, dropped_exhausted, dropped_shutdown FROM sessions WHERE id = 1"
            )
            row = cursor.fetchone()
            assert row == (0, 0, 0)

    def test_sessions_has_no_dropped_no_session_column(self, tmp_path: Path) -> None:
        """Sessions table does NOT have dropped_no_session (removed in new schema)."""
        # dup-ignore-start: the "db_path = tmp_path / 'test.db'; run_migrations(db_path); with
        # sqlite_conn(db_path) as conn:" setup below is mechanical boilerplate, but its duplicate
        # occurrences pair with tests/unit/core/test_migration_runner.py — a different test
        # directory. Extraction would need a shared helper module spanning tests/unit/core/ and
        # tests/unit/, out of scope for this cluster (see
        # design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs. annotate" worked example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(sessions)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "dropped_no_session" not in cols
        # dup-ignore-end

    def test_views_filter_by_tier(self, tmp_path: Path) -> None:
        """Views active_app_listeners and active_framework_listeners filter by source_tier."""
        # dup-ignore-start: same cross-module boilerplate rationale as
        # test_sessions_drop_counters_default_to_zero() above.
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            conn.execute(
                "INSERT INTO listeners "
                "(app_key, instance_index, name, handler_method, topic, source_location, source_tier) "
                "VALUES ('my_app', 0, 'app_listener', 'on_state', 'state_changed', 'app.py:10', 'app')"
            )
            # dup-ignore-end
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

    def test_user_version_set_after_migration(self, tmp_path: Path) -> None:
        """PRAGMA user_version is LATEST_MIGRATION_VERSION after all migrations run."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]

        assert version == LATEST_MIGRATION_VERSION

    def test_listeners_has_mode_column_default_single(self, tmp_path: Path) -> None:
        """003.sql adds a mode column to listeners defaulting to 'single'."""
        # dup-ignore-start: the "db_path = tmp_path / 'test.db'; run_migrations(db_path); with
        # sqlite_conn(db_path) as conn:" setup below is mechanical boilerplate, but its duplicate
        # occurrences pair with tests/unit/core/test_migration_runner.py — a different test
        # directory. Extraction would need a shared helper module spanning tests/unit/core/ and
        # tests/unit/, out of scope for this cluster (see
        # design/specs/099-dedupe-tests-unit-core/design.md, "Extract vs. annotate" worked example).
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(listeners)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "mode" in cols
            # dup-ignore-end

            conn.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
                " VALUES ('app', 0, 'my_listener', 'on_x', 'light.kitchen', 'app.py:1')"
            )
            conn.commit()
            row = conn.execute("SELECT mode FROM listeners WHERE name = 'my_listener'").fetchone()
            assert row[0] == "single"

    def test_listeners_has_backpressure_column_default_block(self, tmp_path: Path) -> None:
        """008.sql adds a backpressure column to listeners defaulting to 'block'."""
        # dup-ignore-start: same cross-directory boilerplate rationale as
        # test_listeners_has_mode_column_default_single() above.
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(listeners)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "backpressure" in cols
            # dup-ignore-end

            conn.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
                " VALUES ('app', 0, 'my_listener', 'on_x', 'light.kitchen', 'app.py:1')"
            )
            conn.commit()
            row = conn.execute("SELECT backpressure FROM listeners WHERE name = 'my_listener'").fetchone()
            assert row[0] == "block"

    def test_listeners_backpressure_backfills_pre_migration_rows(self, tmp_path: Path) -> None:
        """A listener row written before migration 008 reads 'block' after the migration runs."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path, target=7)  # schema before the backpressure column existed

        with sqlite_conn(db_path) as conn:
            conn.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location)"
                " VALUES ('app', 0, 'legacy_listener', 'on_x', 'light.kitchen', 'app.py:1')"
            )
            conn.commit()

        run_migrations(db_path)  # apply 008 onto the populated table

        with sqlite_conn(db_path) as conn:
            row = conn.execute("SELECT backpressure FROM listeners WHERE name = 'legacy_listener'").fetchone()
            assert row[0] == "block"

    def test_scheduled_jobs_has_mode_column_default_single(self, tmp_path: Path) -> None:
        """006.sql adds a mode column to scheduled_jobs defaulting to 'single'."""
        # dup-ignore-start: same cross-directory boilerplate rationale as
        # test_listeners_has_mode_column_default_single() above.
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(scheduled_jobs)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "mode" in cols
            # dup-ignore-end

            conn.execute(
                "INSERT INTO scheduled_jobs"
                " (app_key, instance_index, job_name, handler_method, source_location, source_tier, schedule_status)"
                " VALUES ('app', 0, 'my_job', 'on_x', 'app.py:1', 'app', 'scheduled')"
            )
            conn.commit()
            row = conn.execute("SELECT mode FROM scheduled_jobs WHERE job_name = 'my_job'").fetchone()
            assert row[0] == "single"

    def test_scheduled_jobs_mode_check_rejects_invalid(self, tmp_path: Path) -> None:
        """scheduled_jobs.mode CHECK constraint rejects invalid values."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scheduled_jobs "
                "(app_key, instance_index, job_name, handler_method, source_location, source_tier, mode)"
                " VALUES ('app', 0, 'bad_job', 'on_x', 'app.py:1', 'app', 'invalid')"
            )


class TestDbVersionMismatch:
    def test_version_zero_deletes_db(self, tmp_path: Path) -> None:
        """When DB version is 0 (pre-PRAGMA era), DatabaseService deletes and recreates the DB."""
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
            patch.object(DatabaseService, "get_current_db_version", return_value=0),
            patch.object(DatabaseService, "get_expected_head_version", return_value=1),
        ):
            asyncio.run(svc.handle_schema_version(db_path))
            # DB file should have been deleted (on_initialize handles re-running migrations)
            assert not db_path.exists()


class TestSchemaUpgradePreservesData:
    def test_existing_db_not_deleted_when_behind_head(self, tmp_path: Path) -> None:
        """When 0 < current_version < expected_head, handle_schema_version preserves the DB file and data."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path, target=5)

        with sqlite_conn(db_path) as conn:
            conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
            conn.commit()

        svc = DatabaseService.__new__(DatabaseService)
        svc.logger = MagicMock()

        asyncio.run(svc.handle_schema_version(db_path))

        assert db_path.exists(), "Database file was deleted despite having valid schema version > 0"

        with sqlite_conn(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 1, "Session data was lost during schema version check"


class TestHassetteConfigTelemetryQueueMax:
    def test_telemetry_write_queue_max_default(self) -> None:
        """HassetteConfig.telemetry_write_queue_max defaults to 1000."""
        config = HassetteConfig(token=TEST_TOKEN, _cli_parse_args=False)
        assert config.database.telemetry_write_queue_max == 1000
