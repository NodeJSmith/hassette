"""Shared seed helpers: the insert surface and scenario building blocks.

Scenario modules (siblings of this one) interact with the database exclusively through
``SeedContext`` and the ``seed_*`` helpers below -- they never write raw SQL. See the
package docstring in ``__init__.py`` for the duplicate-detector rationale behind the
``dup-ignore-file`` markers those modules carry.
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from whenever import Instant

from hassette.core.database_service import LOG_RECORD_COLUMNS
from hassette.core.execution_record import ExecutionRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry.repository import execution_insert_params, job_insert_params, listener_insert_params
from hassette.test_utils.factories import (
    make_execution_record,
    make_job_registration,
    make_listener_registration,
)
from hassette.types.types import LOG_LEVEL_TYPE, ExecutionStatus

REFERENCE_INSTANT = Instant.from_utc(2026, 1, 15, 12, 0)
"""Deterministic reference point. All scenario timestamps are fixed offsets from this
instant — never wall-clock — so re-running a scenario produces identical data."""

# Repeated seed-data conventions, named once instead of retyped at each scenario call site.
APP_TIME_SPACING_SECONDS = 3600.0
"""One hour of timeline separation between each fictional app within a scenario."""

HEARTBEAT_OFFSET_SECONDS = 1800.0
"""30-minute heartbeat offset used for a 'running' session's last_heartbeat_at."""

STATE_CHANGED_TOPIC = "hass.event.state_changed"
"""Canonical topic string for a state-change listener."""

WATCHDOG_TIER = "watchdog"
MONKEYPATCH_TIER = "monkeypatch"
"""The two ``blocking_events.tier`` values (see ``BlockingEvent`` in telemetry_models.py)."""

REASON_FRAMEWORK = "framework"
REASON_ATTRIBUTED = "attributed"
"""Two of the three ``blocking_events.reason`` values this seed script generates (the third,
"displaced", has no scenario call site today)."""

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
_LOG_INSERT_SQL = _build_insert_sql("log_records", LOG_RECORD_COLUMNS)
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
    """Binds a cursor for one scenario run's inserts.

    Scenario generators interact exclusively through these methods — they never write
    raw SQL. Each ``add_*`` method builds INSERT params, executes via ``insert_row``,
    and returns the inserted id; generators thread FK references through their own
    local variables (see e.g. ``scenario_large_volume``'s ``session_ids_by_app``).
    """

    cursor: sqlite3.Cursor

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
        """Insert a sessions row and return its id."""
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
        return insert_row(self.cursor, _SESSION_INSERT_SQL, params)

    def add_listener(
        self,
        registration: ListenerRegistration,
        *,
        retired_at: float | None = None,
        removed_at: float | None = None,
    ) -> int:
        """Insert a listeners row and return its id.

        ``retired_at``/``removed_at`` are not part of ``ListenerRegistration`` (they are
        post-registration lifecycle state) so they are accepted separately here — see the
        design doc's Lifecycle Field Contract for reachable combinations.
        """
        if not registration.name:
            raise ValueError("Seeded listeners must have a non-empty name (DB-registered listeners require name=)")
        params = listener_insert_params(registration)
        params["retired_at"] = retired_at
        params["removed_at"] = removed_at
        sql = _build_insert_sql("listeners", params, returning=True)
        return insert_row(self.cursor, sql, params)

    def add_job(
        self,
        registration: ScheduledJobRegistration,
        *,
        retired_at: float | None = None,
        removed_at: float | None = None,
    ) -> int:
        """Insert a scheduled_jobs row and return its id."""
        params = job_insert_params(registration)
        params["retired_at"] = retired_at
        params["removed_at"] = removed_at
        sql = _build_insert_sql("scheduled_jobs", params, returning=True)
        return insert_row(self.cursor, sql, params)

    def add_app_manifest(
        self,
        *,
        app_key: str,
        class_name: str,
        display_name: str | None = None,
        filename: str | None = None,
        enabled: bool = True,
        autostart: bool = True,
        auto_loaded: bool = False,
    ) -> int:
        """Insert an app_manifests row and return its id.

        Mirrors ``manifest_insert_params()`` (repository.py) field-for-field, but built from
        explicit kwargs rather than a real ``AppManifest`` instance -- seed scenarios have no
        live app config to construct one from. Boolean fields are stored as 0/1 integers,
        matching the SQLite column type in migrations_sql/011.sql.

        ``display_name`` defaults to ``class_name`` and ``filename`` defaults to
        ``f"{app_key}.py"`` -- the convention every scenario follows. Pass ``filename``
        explicitly to override it (e.g. when ``app_key`` isn't a valid filename, like the
        Unicode/emoji scenario).
        """
        display_name = display_name if display_name is not None else class_name
        filename = filename if filename is not None else f"{app_key}.py"
        params = {
            "app_key": app_key,
            "class_name": class_name,
            "display_name": display_name,
            "filename": filename,
            "enabled": 1 if enabled else 0,
            "autostart": 1 if autostart else 0,
            "auto_loaded": 1 if auto_loaded else 0,
        }
        sql = _build_insert_sql("app_manifests", params, returning=True)
        return insert_row(self.cursor, sql, params)

    def add_execution(self, record: ExecutionRecord) -> str:
        """Insert an executions row and return its execution_id.

        No RETURNING needed — the execution_id string is already known from ``record``
        and is what ``log_records``/``blocking_events`` correlate against.
        """
        if not record.execution_id:
            raise ValueError("Seeded executions must have a deterministic execution_id")
        params = execution_insert_params(record)
        sql = _build_insert_sql("executions", params)
        insert_row(self.cursor, sql, params)
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


def ts(offset_seconds: float) -> float:
    """Epoch-seconds float at ``REFERENCE_INSTANT + offset_seconds`` (offset may be negative).

    Every scenario timestamp is built through this helper so nothing ever reads the wall clock.
    """
    return float(REFERENCE_INSTANT.add(seconds=offset_seconds).timestamp())


def add_running_session(ctx: SeedContext, base: float) -> int:
    """Insert a ``sessions`` row in the default 'running' state starting at ``base``."""
    return ctx.add_session(started_at=ts(base), last_heartbeat_at=ts(base + HEARTBEAT_OFFSET_SECONDS))


def seed_executions(
    ctx: SeedContext,
    *,
    scenario: str,
    app_key: str,
    session_id: int,
    count: int,
    kind: Literal["handler", "job"] = "handler",
    listener_id: int | None = None,
    job_id: int | None = None,
    n_di_failures: int = 0,
    n_errors: int = 0,
    n_thread_leaked: int = 0,
    start_index: int = 0,
    base_offset: float = 0.0,
    interval_seconds: float = 60.0,
    duration_ms: float = 120.0,
    error_type: str = "RuntimeError",
    error_message: str = "Simulated failure for seed data",
) -> None:
    """Insert ``count`` executions for one listener/job in three contiguous bands: DI
    failures, plain errors, then thread-leaked timeouts, with any remainder as successes.

    Band sizes are exact counts (not fractions) so callers can compute the precise error
    count needed to land an app's health status on a specific side of a threshold. DI
    failures also count as ``status='error'`` (a DependencyError is still an execution
    error) — only thread-leaked executions get ``status='timed_out'``, matching
    ``ExecutionRecord.thread_leaked``'s docstring contract.
    """
    di_end = n_di_failures
    error_end = di_end + n_errors
    leaked_end = error_end + n_thread_leaked
    for i in range(count):
        index = start_index + i
        if i < di_end:
            status, is_di, is_leaked = ExecutionStatus.ERROR, True, False
        elif i < error_end:
            status, is_di, is_leaked = ExecutionStatus.ERROR, False, False
        elif i < leaked_end:
            status, is_di, is_leaked = ExecutionStatus.TIMED_OUT, False, True
        else:
            status, is_di, is_leaked = ExecutionStatus.SUCCESS, False, False
        ctx.add_execution(
            make_execution_record(
                kind=kind,
                execution_id=make_execution_id(scenario, app_key, index),
                session_id=session_id,
                listener_id=listener_id,
                job_id=job_id,
                app_key=app_key,
                status=status,
                execution_start_ts=ts(base_offset + index * interval_seconds),
                duration_ms=duration_ms,
                error_type=error_type if status == ExecutionStatus.ERROR else None,
                error_message=error_message if status == ExecutionStatus.ERROR else None,
                is_di_failure=is_di,
                thread_leaked=is_leaked,
            )
        )


def seed_log_records(
    ctx: SeedContext,
    *,
    start_seq: int,
    count: int,
    app_key: str,
    class_name: str,
    base_offset: float,
    instance_index: int = 0,
    interval_seconds: float = 60.0,
    level: LOG_LEVEL_TYPE = "INFO",
    message_prefix: str = "log entry",
    logger_name: str | None = None,
) -> int:
    """Insert ``count`` log records at ``interval_seconds`` spacing. Returns the next unused
    seq value so callers can thread a running counter across multiple calls within a scenario.

    The log record's ``instance_name`` is computed internally from ``class_name``/``instance_index``
    rather than accepted as a parameter, since every caller was building it the same way.
    """
    logger_name = logger_name or f"hassette.apps.{app_key}"
    instance_name = make_instance_name(class_name, instance_index)
    for i in range(count):
        seq = start_seq + i
        ctx.add_log_record(
            seq=seq,
            timestamp=ts(base_offset + i * interval_seconds),
            level=level,
            logger_name=logger_name,
            message=f"{message_prefix} #{i + 1}",
            app_key=app_key,
            instance_name=instance_name,
            instance_index=instance_index,
            source_tier="app",
        )
    return start_seq + count


def seed_simple_app(
    ctx: SeedContext,
    *,
    scenario: str,
    app_key: str,
    class_name: str,
    base_offset: float,
    exec_count: int,
    n_errors: int = 0,
    n_di_failures: int = 0,
    n_thread_leaked: int = 0,
) -> tuple[int, int, int]:
    """Seed one 'normal shape' app: a running session, one state-change listener, one
    interval job, and executions split roughly 2:1 between the listener and the job.

    Returns ``(session_id, listener_id, job_id)`` so callers can layer scenario-specific
    extras (more listeners, log records, blocking events) on top. Errors are packed into
    the listener's slice first, spilling into the job's slice only once the listener slice
    is exhausted — the total error count is what matters for health computation, not which
    slice they land in.
    """
    session_id = ctx.add_session(
        started_at=ts(base_offset), last_heartbeat_at=ts(base_offset + HEARTBEAT_OFFSET_SECONDS)
    )
    listener_id = seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_state_change",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_state_listener",
        source_location=f"{app_key}.py:12",
    )
    job_id = seed_job(
        ctx,
        app_key=app_key,
        job_name=f"{app_key}_periodic_check",
        handler_method=f"{class_name}.periodic_check",
        trigger_type="interval",
        trigger_label="every 15 minutes",
        source_location=f"{app_key}.py:30",
    )

    n_listener_execs = max(1, exec_count * 2 // 3)
    n_job_execs = max(0, exec_count - n_listener_execs)
    listener_errors = min(n_errors, n_listener_execs)
    job_errors = min(max(0, n_errors - n_listener_execs), n_job_execs)
    seed_executions(
        ctx,
        scenario=scenario,
        app_key=app_key,
        session_id=session_id,
        kind="handler",
        listener_id=listener_id,
        count=n_listener_execs,
        n_errors=listener_errors,
        n_di_failures=n_di_failures,
        n_thread_leaked=n_thread_leaked,
        base_offset=base_offset,
    )
    seed_executions(
        ctx,
        scenario=scenario,
        app_key=app_key,
        session_id=session_id,
        kind="job",
        job_id=job_id,
        count=n_job_execs,
        n_errors=job_errors,
        start_index=n_listener_execs,
        base_offset=base_offset + n_listener_execs * 60.0,
    )
    return session_id, listener_id, job_id


def seed_listener(
    ctx: SeedContext,
    *,
    app_key: str,
    instance_index: int = 0,
    retired_at: float | None = None,
    removed_at: float | None = None,
    **kwargs: Any,
) -> int:
    """Insert a listener via ``make_listener_registration``, forwarding scenario-specific fields.

    Every scenario call site shares the ``app_key``/``instance_index`` shape; only
    ``handler_method``/``topic``/``name``/``source_location`` (and occasionally
    ``predicate_description``/``human_description``) vary per listener.
    """
    return ctx.add_listener(
        make_listener_registration(app_key=app_key, instance_index=instance_index, **kwargs),
        retired_at=retired_at,
        removed_at=removed_at,
    )


def seed_job(
    ctx: SeedContext,
    *,
    app_key: str,
    instance_index: int = 0,
    retired_at: float | None = None,
    removed_at: float | None = None,
    **kwargs: Any,
) -> int:
    """Insert a scheduled job via ``make_job_registration``, forwarding scenario-specific fields."""
    return ctx.add_job(
        make_job_registration(app_key=app_key, instance_index=instance_index, **kwargs),
        retired_at=retired_at,
        removed_at=removed_at,
    )


def seed_app_blocking_event(
    ctx: SeedContext,
    *,
    session_id: int | None,
    app_key: str,
    class_name: str,
    detected_ts: float,
    stall_duration_ms: float,
    instance_index: int = 0,
    tier: str = WATCHDOG_TIER,
    reason: str = REASON_ATTRIBUTED,
) -> None:
    """Insert a blocking event attributed to one running app instance.

    This is the shape every non-framework blocking event in these scenarios shares --
    the framework-tier events (``session_id``/``app_key``/``instance_name`` all ``None``)
    are seeded directly via ``ctx.add_blocking_event`` instead.
    """
    ctx.add_blocking_event(
        tier=tier,
        reason=reason,
        session_id=session_id,
        app_key=app_key,
        instance_name=make_instance_name(class_name, instance_index),
        instance_index=instance_index,
        detected_ts=detected_ts,
        source_tier="app",
        stall_duration_ms=stall_duration_ms,
    )
