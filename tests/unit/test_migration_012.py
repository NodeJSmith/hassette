"""Tests for migration 012: cancelled_at -> removed_at, schedule_status/schedule_status_reason.

The scheduled_jobs rebuild is an FK-parent rebuild (executions.job_id references
scheduled_jobs.id), so id preservation is verified with PRAGMA foreign_key_check in
addition to schema/CHECK-constraint assertions.
"""

import sqlite3
from pathlib import Path

import pytest

from hassette.core.migration_runner import run_migrations
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.test_utils.sql_helpers import insert_execution_row, sqlite_conn


def _pre_migration_db(tmp_path: Path) -> Path:
    """Build a DB at migration 011 (pre-012) with one session, listener, and scheduled_job."""
    db_path = tmp_path / "test.db"
    run_migrations(db_path, target=11)

    with sqlite_conn(db_path) as conn:
        conn.execute("INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1.0, 1.0, 'running')")
        conn.execute(
            "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, source_location) "
            "VALUES ('my_app', 0, 'my_listener', 'on_x', 'light.kitchen', ?)",
            (TEST_SOURCE_LOCATION,),
        )
        conn.execute(
            "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, source_location) "
            "VALUES ('my_app', 0, 'my_job', 'do_thing', ?)",
            (TEST_SOURCE_LOCATION,),
        )
        conn.commit()
        insert_execution_row(conn, kind="job", job_id=1, session_id=1, execution_start_ts=1.0, duration_ms=5.0)
        insert_execution_row(conn, kind="handler", listener_id=1, session_id=1, execution_start_ts=2.0, duration_ms=3.0)
        conn.commit()

    return db_path


class TestIdPreservationAndForeignKeys:
    def test_foreign_key_check_passes_after_migration(self, tmp_path: Path) -> None:
        """PRAGMA foreign_key_check reports no violations after the scheduled_jobs rebuild."""
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path, foreign_keys=True) as conn:
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            assert violations == [], f"Unexpected FK violations after migration 012: {violations}"

    def test_executions_job_id_still_resolves(self, tmp_path: Path) -> None:
        """executions.job_id inserted before the migration still resolves to the same job row."""
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            row = conn.execute(
                "SELECT sj.job_name FROM executions e JOIN scheduled_jobs sj ON sj.id = e.job_id WHERE e.kind = 'job'"
            ).fetchone()
            assert row == ("my_job",), "executions.job_id no longer resolves to the pre-migration job row"

    def test_executions_listener_id_still_resolves(self, tmp_path: Path) -> None:
        """executions.listener_id inserted before the migration still resolves after the listeners rename."""
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            row = conn.execute(
                "SELECT l.name FROM executions e JOIN listeners l ON l.id = e.listener_id WHERE e.kind = 'handler'"
            ).fetchone()
            assert row == ("my_listener",)


class TestRemovedAtRename:
    def test_scheduled_jobs_has_removed_at_not_cancelled_at(self, tmp_path: Path) -> None:
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(scheduled_jobs)")}
            assert "removed_at" in cols
            assert "cancelled_at" not in cols

    def test_listeners_has_removed_at_not_cancelled_at(self, tmp_path: Path) -> None:
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(listeners)")}
            assert "removed_at" in cols
            assert "cancelled_at" not in cols

    def test_cancelled_at_timestamp_preserved_as_removed_at(self, tmp_path: Path) -> None:
        """A cancelled_at value written before the migration survives as removed_at."""
        db_path = _pre_migration_db(tmp_path)

        with sqlite_conn(db_path) as conn:
            conn.execute("UPDATE scheduled_jobs SET cancelled_at = 999.5 WHERE job_name = 'my_job'")
            conn.execute("UPDATE listeners SET cancelled_at = 888.5 WHERE name = 'my_listener'")
            conn.commit()

        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            job_removed_at = conn.execute("SELECT removed_at FROM scheduled_jobs WHERE job_name = 'my_job'").fetchone()[
                0
            ]
            listener_removed_at = conn.execute(
                "SELECT removed_at FROM listeners WHERE name = 'my_listener'"
            ).fetchone()[0]

        assert job_removed_at == 999.5
        assert listener_removed_at == 888.5


class TestLegacyBackfill:
    def test_existing_rows_backfill_scheduled_legacy_unknown(self, tmp_path: Path) -> None:
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            row = conn.execute(
                "SELECT schedule_status, schedule_status_reason FROM scheduled_jobs WHERE job_name = 'my_job'"
            ).fetchone()

        assert row == ("scheduled", "legacy_unknown")


class TestRemovedRowsExcludedFromActiveViews:
    def test_removed_legacy_row_excluded_from_active_scheduled_jobs(self, tmp_path: Path) -> None:
        db_path = _pre_migration_db(tmp_path)

        with sqlite_conn(db_path) as conn:
            conn.execute("UPDATE scheduled_jobs SET cancelled_at = 500.0 WHERE job_name = 'my_job'")
            conn.commit()

        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            active = conn.execute("SELECT * FROM active_scheduled_jobs").fetchall()
            active_app = conn.execute("SELECT * FROM active_app_scheduled_jobs").fetchall()

        assert active == []
        assert active_app == []

    def test_removed_listener_excluded_from_active_listeners(self, tmp_path: Path) -> None:
        db_path = _pre_migration_db(tmp_path)

        with sqlite_conn(db_path) as conn:
            conn.execute("UPDATE listeners SET cancelled_at = 500.0 WHERE name = 'my_listener'")
            conn.commit()

        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            active = conn.execute("SELECT * FROM active_listeners").fetchall()
            active_app = conn.execute("SELECT * FROM active_app_listeners").fetchall()

        assert active == []
        assert active_app == []

    def test_non_removed_row_still_active(self, tmp_path: Path) -> None:
        """A row that was never removed remains in the active views after migration."""
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            active_jobs = conn.execute("SELECT job_name FROM active_scheduled_jobs").fetchall()
            active_listeners = conn.execute("SELECT name FROM active_listeners").fetchall()

        assert active_jobs == [("my_job",)]
        assert active_listeners == [("my_listener",)]


class TestReRegistrationClearsLegacyUnknown:
    def test_upsert_clears_legacy_unknown_reason(self, tmp_path: Path) -> None:
        """Re-registering via the same ON CONFLICT upsert shape as repository.register_job()
        overwrites schedule_status and schedule_status_reason, clearing the legacy placeholder.
        """
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            before = conn.execute(
                "SELECT schedule_status, schedule_status_reason FROM scheduled_jobs WHERE job_name = 'my_job'"
            ).fetchone()
            assert before == ("scheduled", "legacy_unknown")

            # Mirrors TelemetryRepository.register_job()'s ON CONFLICT DO UPDATE shape: live
            # re-registration always supplies schedule_status/schedule_status_reason explicitly,
            # which is what actually clears the migration's legacy_unknown placeholder.
            conn.execute(
                """
                INSERT INTO scheduled_jobs (
                    app_key, instance_index, job_name, handler_method, source_location,
                    schedule_status, schedule_status_reason
                ) VALUES (
                    'my_app', 0, 'my_job', 'do_thing', ?, 'manual', NULL
                )
                ON CONFLICT(app_key, instance_index, job_name)
                DO UPDATE SET
                    schedule_status = excluded.schedule_status,
                    schedule_status_reason = excluded.schedule_status_reason
                """,
                (TEST_SOURCE_LOCATION,),
            )
            conn.commit()

            after = conn.execute(
                "SELECT schedule_status, schedule_status_reason FROM scheduled_jobs WHERE job_name = 'my_job'"
            ).fetchone()

        assert after == ("manual", None)


class TestCheckConstraints:
    def test_rejects_invalid_schedule_status(self, tmp_path: Path) -> None:
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scheduled_jobs "
                "(app_key, instance_index, job_name, handler_method, source_location, schedule_status) "
                "VALUES ('my_app', 0, 'bad_status_job', 'do_thing', ?, 'not_a_real_status')",
                (TEST_SOURCE_LOCATION,),
            )

    def test_rejects_invalid_schedule_status_reason(self, tmp_path: Path) -> None:
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scheduled_jobs "
                "(app_key, instance_index, job_name, handler_method, source_location, "
                "schedule_status, schedule_status_reason) "
                "VALUES ('my_app', 0, 'bad_reason_job', 'do_thing', ?, 'scheduled', 'not_a_real_reason')",
                (TEST_SOURCE_LOCATION,),
            )

    def test_null_schedule_status_reason_is_accepted(self, tmp_path: Path) -> None:
        """schedule_status_reason is nullable -- a fresh manual registration has no reason."""
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            conn.execute(
                "INSERT INTO scheduled_jobs "
                "(app_key, instance_index, job_name, handler_method, source_location, "
                "trigger_type, schedule_status, schedule_status_reason) "
                "VALUES ('my_app', 0, 'clean_job', 'do_thing', ?, 'manual', 'manual', NULL)",
                (TEST_SOURCE_LOCATION,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT schedule_status_reason FROM scheduled_jobs WHERE job_name = 'clean_job'"
            ).fetchone()

        assert row == (None,)

    def test_missing_schedule_status_rejected_as_not_null(self, tmp_path: Path) -> None:
        """schedule_status has no DEFAULT -- every insert must supply it explicitly."""
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, source_location) "
                "VALUES ('my_app', 0, 'no_status_job', 'do_thing', ?)",
                (TEST_SOURCE_LOCATION,),
            )


class TestManualTriggerType:
    def test_trigger_type_manual_is_accepted(self, tmp_path: Path) -> None:
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            conn.execute(
                "INSERT INTO scheduled_jobs "
                "(app_key, instance_index, job_name, handler_method, source_location, "
                "trigger_type, schedule_status) "
                "VALUES ('my_app', 0, 'manual_job', 'do_thing', ?, 'manual', 'manual')",
                (TEST_SOURCE_LOCATION,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT trigger_type, schedule_status FROM scheduled_jobs WHERE job_name = 'manual_job'"
            ).fetchone()

        assert row == ("manual", "manual")

    def test_other_trigger_types_still_accepted(self, tmp_path: Path) -> None:
        """The pre-existing trigger_type values are still valid after extending the CHECK."""
        db_path = _pre_migration_db(tmp_path)
        run_migrations(db_path)

        with sqlite_conn(db_path) as conn:
            for trigger_type in ("interval", "cron", "once", "after", "custom"):
                conn.execute(
                    "INSERT INTO scheduled_jobs "
                    "(app_key, instance_index, job_name, handler_method, source_location, "
                    "trigger_type, schedule_status) "
                    "VALUES ('my_app', 0, ?, 'do_thing', ?, ?, 'scheduled')",
                    (f"job_{trigger_type}", TEST_SOURCE_LOCATION, trigger_type),
                )
            conn.commit()
