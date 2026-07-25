#!/usr/bin/env python3
"""Generate deterministic seed SQLite databases for hassette telemetry scenarios.

Creates a fresh SQLite database (schema applied via the real migration runner)
and populates it with hand-authored, fully deterministic data for a named
scenario. Useful for frontend QA, CLI doc generation, visual regression
screenshots, and demos that need the monitoring dashboard in a specific state
without waiting on a live Home Assistant instance.

Usage::

    python scripts/seed_db.py --scenario healthy
    python scripts/seed_db.py --scenario degraded --output /tmp/hassette-degraded.db
"""

import argparse
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whenever import Instant

from hassette.core.execution_record import ExecutionRecord
from hassette.core.migration_runner import run_migrations
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry.repository import execution_insert_params, job_insert_params, listener_insert_params

REFERENCE_INSTANT = Instant.from_utc(2026, 1, 15, 12, 0)
"""Deterministic reference point. All scenario timestamps are fixed offsets from this
instant — never wall-clock — so re-running a scenario produces identical data."""

# SQLite reserved words that appear as column names and must be quoted when building
# dynamic INSERT statements. Only "group" (scheduled_jobs.group) needs this today.
_RESERVED_COLUMNS = frozenset({"group"})

# sessions table columns (see migrations_sql/001.sql), excluding the autoincrement id.
_SESSION_COLUMNS = (
    "started_at",
    "stopped_at",
    "last_heartbeat_at",
    "status",
    "error_type",
    "error_message",
    "error_traceback",
    "dropped_overflow",
    "dropped_exhausted",
    "dropped_shutdown",
)

# log_records table columns (see migrations_sql/001.sql), excluding the autoincrement id.
# 13 columns — not to be confused with the 7-ish shape of other event tables.
# NOTE: this tuple is a hand-kept duplicate of `_LOG_COLUMNS` in
# src/hassette/core/database_service.py:53. That copy is underscore-prefixed (private) and
# out of this script's read-only scope, so it can't be imported directly. If a migration
# changes log_records' columns, update both copies — a mismatch here won't be caught by a
# column-count check, only by the post-seed integrity checks (and only if the drift also
# breaks a constraint).
_LOG_COLUMNS = (
    "seq",
    "timestamp",
    "level",
    "logger_name",
    "func_name",
    "lineno",
    "message",
    "exc_info",
    "app_key",
    "instance_name",
    "instance_index",
    "execution_id",
    "source_tier",
)

# blocking_events table columns (see migrations_sql/005.sql, 007.sql), excluding the
# autoincrement id.
_BLOCKING_EVENT_COLUMNS = (
    "session_id",
    "app_key",
    "instance_name",
    "instance_index",
    "execution_id",
    "tier",
    "primitive",
    "source_location",
    "stall_duration_ms",
    "detected_ts",
    "source_tier",
    "reason",
)

_SUMMARY_TABLES = ("sessions", "listeners", "scheduled_jobs", "executions", "log_records", "blocking_events")

_DANGLING_EXECUTION_ID_QUERY = """
    SELECT t.execution_id
    FROM {table} t
    LEFT JOIN executions e ON t.execution_id = e.execution_id
    WHERE t.execution_id IS NOT NULL AND e.execution_id IS NULL
"""


class SeedIntegrityError(Exception):
    """Raised when a post-seed integrity check (FK check or consistency assertion) fails."""


def make_execution_id(scenario: str, app_key: str, index: int) -> str:
    """Build a deterministic, reproducible execution_id string.

    Not a real UUID — just unique and stable across runs, matching the
    ``{scenario}_{app_key}_{index:04d}`` convention.
    """
    return f"{scenario}_{app_key}_{index:04d}"


def make_instance_name(class_name: str, instance_index: int) -> str:
    """Build the display instance name, matching the production default fallback."""
    return f"{class_name}.{instance_index}"


def _quote_column(name: str) -> str:
    """Quote a column name if it collides with a SQLite reserved word."""
    return f'"{name}"' if name in _RESERVED_COLUMNS else name


def _build_insert_sql(table: str, columns: Iterable[str], *, returning: bool = False) -> str:
    """Build a plain INSERT statement from a table name and column names.

    Column order matches the order of ``columns`` (dict key order, for callers that pass
    ``tuple(params)``). Deriving the column list from the same dict used for parameter
    binding keeps the seed script from drifting out of sync with param builder changes.
    """
    columns = tuple(columns)
    col_list = ", ".join(_quote_column(c) for c in columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"  # noqa: S608 — table/columns are static literals
    if returning:
        sql += " RETURNING id"
    return sql


_SESSION_INSERT_SQL = _build_insert_sql("sessions", _SESSION_COLUMNS, returning=True)
_LOG_INSERT_SQL = _build_insert_sql("log_records", _LOG_COLUMNS)
_BLOCKING_EVENT_INSERT_SQL = _build_insert_sql("blocking_events", _BLOCKING_EVENT_COLUMNS)


def insert_row(cursor: sqlite3.Cursor, sql: str, params: dict[str, Any]) -> int:
    """Execute an INSERT and return the new row's integer id.

    Uses the ``RETURNING id`` result when the statement has one; falls back to
    ``cursor.lastrowid`` for tables without RETURNING (log_records, blocking_events).

    Args:
        cursor: An open sqlite3 cursor, inside an active transaction.
        sql: The INSERT statement to execute.
        params: Named parameters matching the statement's ``:name`` placeholders.

    Returns:
        The integer id of the inserted row.

    Raises:
        RuntimeError: If a RETURNING clause yields no row, or lastrowid is unavailable.
    """
    cursor.execute(sql, params)
    if "RETURNING" in sql:
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"INSERT with RETURNING produced no row: {sql}")
        return row[0]
    if cursor.lastrowid is None:
        raise RuntimeError(f"INSERT produced no lastrowid: {sql}")
    return cursor.lastrowid


@dataclass
class SeedContext:
    """Owns cross-table ID bookkeeping and insert ordering for one scenario run.

    Scenario generators interact exclusively through these methods — they never write
    raw SQL. Each ``add_*`` method builds INSERT params, executes via ``insert_row``,
    and tracks the returned id in the appropriate dict/list for later FK references.
    """

    cursor: sqlite3.Cursor
    session_ids: list[int] = field(default_factory=list)
    listener_ids: dict[tuple[str, int, str], int] = field(default_factory=dict)
    job_ids: dict[tuple[str, int, str], int] = field(default_factory=dict)
    execution_ids: list[str] = field(default_factory=list)

    def add_session(
        self,
        *,
        started_at: float,
        last_heartbeat_at: float,
        status: str = "running",
        stopped_at: float | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        error_traceback: str | None = None,
        dropped_overflow: int = 0,
        dropped_exhausted: int = 0,
        dropped_shutdown: int = 0,
    ) -> int:
        """Insert a sessions row and track its id in ``session_ids``."""
        params = {
            "started_at": started_at,
            "stopped_at": stopped_at,
            "last_heartbeat_at": last_heartbeat_at,
            "status": status,
            "error_type": error_type,
            "error_message": error_message,
            "error_traceback": error_traceback,
            "dropped_overflow": dropped_overflow,
            "dropped_exhausted": dropped_exhausted,
            "dropped_shutdown": dropped_shutdown,
        }
        session_id = insert_row(self.cursor, _SESSION_INSERT_SQL, params)
        self.session_ids.append(session_id)
        return session_id

    def add_listener(
        self,
        registration: ListenerRegistration,
        *,
        retired_at: float | None = None,
        cancelled_at: float | None = None,
    ) -> int:
        """Insert a listeners row and track its id under (app_key, instance_index, name).

        ``retired_at``/``cancelled_at`` are not part of ``ListenerRegistration`` (they are
        post-registration lifecycle state) so they are accepted separately here — see the
        design doc's Lifecycle Field Contract for reachable combinations.
        """
        if not registration.name:
            raise ValueError("Seeded listeners must have a non-empty name (DB-registered listeners require name=)")
        params = listener_insert_params(registration)
        params["retired_at"] = retired_at
        params["cancelled_at"] = cancelled_at
        sql = _build_insert_sql("listeners", params, returning=True)
        listener_id = insert_row(self.cursor, sql, params)
        self.listener_ids[(registration.app_key, registration.instance_index, registration.name)] = listener_id
        return listener_id

    def add_job(
        self,
        registration: ScheduledJobRegistration,
        *,
        retired_at: float | None = None,
        cancelled_at: float | None = None,
    ) -> int:
        """Insert a scheduled_jobs row and track its id under (app_key, instance_index, job_name)."""
        params = job_insert_params(registration)
        params["retired_at"] = retired_at
        params["cancelled_at"] = cancelled_at
        sql = _build_insert_sql("scheduled_jobs", params, returning=True)
        job_id = insert_row(self.cursor, sql, params)
        self.job_ids[(registration.app_key, registration.instance_index, registration.job_name)] = job_id
        return job_id

    def add_execution(self, record: ExecutionRecord) -> str:
        """Insert an executions row and track its execution_id in ``execution_ids``.

        No RETURNING needed — the execution_id string is already known from ``record``
        and is what ``log_records``/``blocking_events`` correlate against.
        """
        if not record.execution_id:
            raise ValueError("Seeded executions must have a deterministic execution_id")
        params = execution_insert_params(record)
        sql = _build_insert_sql("executions", params)
        insert_row(self.cursor, sql, params)
        self.execution_ids.append(record.execution_id)
        return record.execution_id

    def add_log_record(
        self,
        *,
        seq: int,
        timestamp: float,
        level: str,
        logger_name: str,
        message: str,
        func_name: str | None = None,
        lineno: int | None = None,
        exc_info: str | None = None,
        app_key: str | None = None,
        instance_name: str | None = None,
        instance_index: int | None = None,
        execution_id: str | None = None,
        source_tier: str | None = None,
    ) -> None:
        """Insert a log_records row. ``execution_id`` may be None (framework logs)."""
        params = {
            "seq": seq,
            "timestamp": timestamp,
            "level": level,
            "logger_name": logger_name,
            "func_name": func_name,
            "lineno": lineno,
            "message": message,
            "exc_info": exc_info,
            "app_key": app_key,
            "instance_name": instance_name,
            "instance_index": instance_index,
            "execution_id": execution_id,
            "source_tier": source_tier,
        }
        insert_row(self.cursor, _LOG_INSERT_SQL, params)

    def add_blocking_event(
        self,
        *,
        tier: str,
        detected_ts: float,
        source_tier: str,
        session_id: int | None = None,
        app_key: str | None = None,
        instance_name: str | None = None,
        instance_index: int | None = None,
        execution_id: str | None = None,
        primitive: str | None = None,
        source_location: str | None = None,
        stall_duration_ms: float | None = None,
        reason: str | None = None,
    ) -> None:
        """Insert a blocking_events row. ``execution_id`` and ``session_id`` may be None."""
        params = {
            "session_id": session_id,
            "app_key": app_key,
            "instance_name": instance_name,
            "instance_index": instance_index,
            "execution_id": execution_id,
            "tier": tier,
            "primitive": primitive,
            "source_location": source_location,
            "stall_duration_ms": stall_duration_ms,
            "detected_ts": detected_ts,
            "source_tier": source_tier,
            "reason": reason,
        }
        insert_row(self.cursor, _BLOCKING_EVENT_INSERT_SQL, params)


def scenario_empty(_ctx: SeedContext) -> None:
    """Trivial baseline: bare schema, zero rows in every table. Uses no app keys."""


def scenario_healthy(_ctx: SeedContext) -> None:
    raise NotImplementedError("TODO: T03")


def scenario_degraded(_ctx: SeedContext) -> None:
    raise NotImplementedError("TODO: T03")


def scenario_error(_ctx: SeedContext) -> None:
    raise NotImplementedError("TODO: T03")


def scenario_large_volume(_ctx: SeedContext) -> None:
    raise NotImplementedError("TODO: T03")


def scenario_lifecycle(_ctx: SeedContext) -> None:
    raise NotImplementedError("TODO: T03")


def scenario_adversarial(_ctx: SeedContext) -> None:
    raise NotImplementedError("TODO: T03")


SCENARIOS: dict[str, Callable[[SeedContext], None]] = {
    "healthy": scenario_healthy,
    "empty": scenario_empty,
    "degraded": scenario_degraded,
    "error": scenario_error,
    "large-volume": scenario_large_volume,
    "lifecycle": scenario_lifecycle,
    "adversarial": scenario_adversarial,
}


def _remove_sqlite_files(db_path: Path) -> None:
    """Remove a SQLite main file and its -wal/-shm siblings, if present."""
    db_path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _assert_foreign_keys_clean(conn: sqlite3.Connection) -> None:
    """Run PRAGMA foreign_key_check and abort with details on any violation."""
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        details = "\n".join(f"  table={row[0]} rowid={row[1]} parent={row[2]} fkid={row[3]}" for row in violations)
        raise SeedIntegrityError(f"Foreign key violations detected:\n{details}")


def _assert_no_dangling_execution_ids(conn: sqlite3.Connection, table: str) -> None:
    """Abort if ``table`` has non-null execution_id values with no matching executions row.

    ``table`` is always one of our own two literal call sites ("log_records",
    "blocking_events") — never user input.
    """
    sql = _DANGLING_EXECUTION_ID_QUERY.format(table=table)
    rows = conn.execute(sql).fetchall()
    if rows:
        ids = ", ".join(row[0] for row in rows)
        raise SeedIntegrityError(f"{table} has execution_id value(s) with no matching executions row: {ids}")


def _collect_summary(conn: sqlite3.Connection) -> dict[str, int]:
    """Return row counts for all 6 telemetry tables plus a distinct-app-key count."""
    summary = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 — table is a static literal
        for table in _SUMMARY_TABLES
    }
    apps_row = conn.execute(
        "SELECT COUNT(*) FROM (SELECT app_key FROM listeners UNION SELECT app_key FROM scheduled_jobs)"
    ).fetchone()
    summary["apps"] = apps_row[0]
    return summary


def generate_scenario(scenario: str, output_path: Path, tmp_path: Path) -> dict[str, int]:
    """Generate one scenario to ``tmp_path`` and atomically swap it into ``output_path``.

    Applies migrations, runs the scenario generator inside a single BEGIN IMMEDIATE /
    COMMIT transaction, verifies referential integrity, then swaps the file into place.
    On any failure, the temp file is removed and the exception propagates — the
    destination path is left untouched.
    """
    _remove_sqlite_files(tmp_path)

    try:
        run_migrations(tmp_path)

        conn = sqlite3.connect(tmp_path, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            ctx = SeedContext(cursor=cursor)

            try:
                cursor.execute("BEGIN IMMEDIATE")
                SCENARIOS[scenario](ctx)
            except Exception:
                conn.rollback()
                raise
            conn.commit()

            _assert_foreign_keys_clean(conn)
            _assert_no_dangling_execution_ids(conn, "log_records")
            _assert_no_dangling_execution_ids(conn, "blocking_events")

            summary = _collect_summary(conn)
        finally:
            conn.close()

        for suffix in ("-wal", "-shm"):
            Path(f"{output_path}{suffix}").unlink(missing_ok=True)
        tmp_path.replace(output_path)
    except Exception:
        _remove_sqlite_files(tmp_path)
        raise

    return summary


def _print_summary(scenario: str, output_path: Path, summary: dict[str, int]) -> None:
    print(f"Seeded scenario '{scenario}' -> {output_path}")
    print(f"  apps:            {summary['apps']}")
    print(f"  listeners:       {summary['listeners']}")
    print(f"  scheduled_jobs:  {summary['scheduled_jobs']}")
    print(f"  executions:      {summary['executions']}")
    print(f"  log_records:     {summary['log_records']}")
    print(f"  blocking_events: {summary['blocking_events']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic seed SQLite database for a named hassette telemetry scenario."
    )
    parser.add_argument(
        "--scenario",
        required=True,
        choices=sorted(SCENARIOS),
        help="Which scenario to generate.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output SQLite file path (default: ./hassette-{scenario}.db)",
    )
    args = parser.parse_args()

    output_path: Path = (args.output or Path(f"hassette-{args.scenario}.db")).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + ".tmp")

    try:
        summary = generate_scenario(args.scenario, output_path, tmp_path)
    except SeedIntegrityError as exc:
        raise SystemExit(f"Seed integrity check failed: {exc}") from exc

    _print_summary(args.scenario, output_path, summary)


if __name__ == "__main__":
    main()
