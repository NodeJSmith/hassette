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

Scenario functions call into shared seed helpers (``_seed_listener``, ``_seed_job``,
``_seed_app_blocking_event``, etc.) repeatedly with the same call shape, differing only in
literal ``app_key``/``class_name``/offset arguments. PMD's clone detector treats these calls
as duplicate fragments, so each occurrence is wrapped in a ``dup-ignore-start``/``dup-ignore-end``
pair (see ``tools/check_duplicate_code.py``) rather than forced into a data-driven loop, which
would obscure the per-app literal values scenario authors need to read and edit directly.
"""

import argparse
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from whenever import Instant

from hassette.core.database_service import LOG_RECORD_COLUMNS
from hassette.core.execution_record import ExecutionRecord
from hassette.core.migration_runner import run_migrations
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


def scenario_empty(_ctx: SeedContext) -> None:
    """Trivial baseline: bare schema, zero rows in every table. Uses no app keys."""


def ts(offset_seconds: float) -> float:
    """Epoch-seconds float at ``REFERENCE_INSTANT + offset_seconds`` (offset may be negative).

    Every scenario timestamp is built through this helper so nothing ever reads the wall clock.
    """
    return float(REFERENCE_INSTANT.add(seconds=offset_seconds).timestamp())


def _add_running_session(ctx: SeedContext, base: float) -> int:
    """Insert a ``sessions`` row in the default 'running' state starting at ``base``."""
    return ctx.add_session(started_at=ts(base), last_heartbeat_at=ts(base + HEARTBEAT_OFFSET_SECONDS))


def _seed_executions(
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


def _seed_log_records(
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


def _seed_simple_app(
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
    listener_id = _seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_state_change",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_state_listener",
        source_location=f"{app_key}.py:12",
    )
    job_id = _seed_job(
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
    _seed_executions(
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
    _seed_executions(
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


def _seed_listener(
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


def _seed_job(
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


def _seed_app_blocking_event(
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


def scenario_healthy(ctx: SeedContext) -> None:
    """5 fictional apps with normal activity and excellent/good health — no failures beyond
    an occasional handled error, comfortably above the 95% "good" success-rate threshold.

    A single minimal blocking event is included (see the comment below) so this scenario
    still populates all 6 telemetry tables without undermining the "healthy install" narrative.
    """
    apps = [
        ("weather_watcher", "WeatherWatcher", 0),
        ("garage_door", "GarageDoor", 1),
        ("plant_monitor", "PlantMonitor", 0),
        ("media_controller", "MediaController", 1),
        ("pet_feeder", "PetFeeder", 0),
    ]
    seq = 1
    for i, (app_key, class_name, n_errors) in enumerate(apps):
        base = i * APP_TIME_SPACING_SECONDS
        ctx.add_app_manifest(app_key=app_key, class_name=class_name)
        _seed_simple_app(
            ctx,
            scenario="healthy",
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            exec_count=20,
            n_errors=n_errors,
        )
        # Second listener per app, for the "2-3 listeners" spread called for in the design doc.
        _seed_listener(
            ctx,
            app_key=app_key,
            handler_method=f"{class_name}.on_call_service",
            topic="hass.event.call_service",
            name=f"{app_key}_service_listener",
            source_location=f"{app_key}.py:24",
        )
        seq = _seed_log_records(
            ctx,
            start_seq=seq,
            count=3,
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            message_prefix=f"{class_name} processed update",
        )

    # See docstring: populates the blocking_events table without affecting health scoring
    # (blocking events don't factor into compute_error_rate/classify_health_bar).
    ctx.add_blocking_event(
        tier=WATCHDOG_TIER,
        reason=REASON_FRAMEWORK,
        session_id=None,
        app_key=None,
        instance_name=None,
        instance_index=None,
        detected_ts=ts(60.0),
        source_tier="framework",
        stall_duration_ms=120.0,
    )


def scenario_degraded(ctx: SeedContext) -> None:
    """Mixed health: 2 apps healthy, 2 apps in the "warning" band, 1 app with boot issues.

    Health-threshold margin note: ``classify_health_bar`` (telemetry_helpers.py) treats
    success_rate in [90, 95) as "warning". The two elevated-error apps below target a 7.5%
    error rate (92.5% success) — solidly centered in that band, 2.5 points from each boundary.
    """
    seq = 1

    for i, (app_key, class_name, n_errors) in enumerate(
        [("weather_watcher", "WeatherWatcher", 0), ("garage_door", "GarageDoor", 0)]
    ):
        base = i * APP_TIME_SPACING_SECONDS
        ctx.add_app_manifest(app_key=app_key, class_name=class_name)
        # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
        _seed_simple_app(
            ctx,
            scenario="degraded",
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            exec_count=20,
            n_errors=n_errors,
        )
        seq = _seed_log_records(
            ctx,
            start_seq=seq,
            count=2,
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
        )
        # dup-ignore-end

    # leaky_faucet_monitor and hallway_thermostat are seeded individually (not in a loop) so
    # hallway_thermostat's session_id is captured directly, for the blocking event below.
    base = 2 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key="leaky_faucet_monitor", class_name="LeakyFaucetMonitor")
    _seed_simple_app(
        ctx,
        scenario="degraded",
        app_key="leaky_faucet_monitor",
        class_name="LeakyFaucetMonitor",
        base_offset=base,
        exec_count=40,
        n_errors=3,
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key="leaky_faucet_monitor",
        class_name="LeakyFaucetMonitor",
        base_offset=base,
        level="ERROR",
        message_prefix="Repeated connection failures",
    )

    hallway_base = 3 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key="hallway_thermostat", class_name="HallwayThermostat")
    hallway_session_id, _listener_id, _job_id = _seed_simple_app(
        ctx,
        scenario="degraded",
        app_key="hallway_thermostat",
        class_name="HallwayThermostat",
        base_offset=hallway_base,
        exec_count=40,
        n_errors=3,
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key="hallway_thermostat",
        class_name="HallwayThermostat",
        base_offset=hallway_base,
        level="ERROR",
        message_prefix="Repeated connection failures",
    )

    # Boot-issue app: first boot fails outright, second boot recovers to 'running'.
    app_key, class_name = "boiler_controller", "BoilerController"
    base = 4 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    failed_session_id = ctx.add_session(
        started_at=ts(base),
        last_heartbeat_at=ts(base + 5.0),
        stopped_at=ts(base + 5.0),
        status="failure",
        error_type="ConnectionError",
        error_message="Could not reach Home Assistant",
    )
    running_session_id = ctx.add_session(
        started_at=ts(base + 60.0), last_heartbeat_at=ts(base + HEARTBEAT_OFFSET_SECONDS)
    )
    listener_id = _seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_temperature_change",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_temp_listener",
        source_location=f"{app_key}.py:20",
    )
    job_id = _seed_job(
        ctx,
        app_key=app_key,
        job_name=f"{app_key}_recalibrate",
        handler_method=f"{class_name}.recalibrate",
        trigger_type="interval",
        trigger_label="every 30 minutes",
        source_location=f"{app_key}.py:30",
    )
    # DI failure during the failed boot attempt — the dependency never came up in time.
    ctx.add_execution(
        make_execution_record(
            kind="handler",
            execution_id=make_execution_id("degraded", app_key, 0),
            session_id=failed_session_id,
            listener_id=listener_id,
            app_key=app_key,
            status=ExecutionStatus.ERROR,
            execution_start_ts=ts(base + 2.0),
            duration_ms=15.0,
            error_type="DependencyError",
            error_message="Api dependency not ready",
            is_di_failure=True,
        )
    )
    _seed_executions(
        ctx,
        scenario="degraded",
        app_key=app_key,
        session_id=running_session_id,
        listener_id=listener_id,
        count=6,
        n_errors=1,
        start_index=1,
        base_offset=base + 120.0,
    )
    # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
    _seed_executions(
        ctx,
        scenario="degraded",
        app_key=app_key,
        session_id=running_session_id,
        kind="job",
        job_id=job_id,
        count=4,
        start_index=7,
        base_offset=base + 400.0,
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=1,
        app_key=app_key,
        class_name=class_name,
        base_offset=base + 1.0,
        level="ERROR",
        message_prefix="Failed to connect to Home Assistant on boot",
    )
    # dup-ignore-end

    _seed_app_blocking_event(
        ctx,
        session_id=hallway_session_id,
        app_key="hallway_thermostat",
        class_name="HallwayThermostat",
        detected_ts=ts(hallway_base + 500.0),
        stall_duration_ms=1800.0,
    )


def scenario_error(ctx: SeedContext) -> None:
    """5 fictional apps all failing hard: 85% error rates (success rate 15% — comfortably
    past the <90% "critical" boundary), crashed and boot-failed sessions, a thread-leaked
    execution, error/critical log records, and one blocking event per app.
    """
    apps = [
        ("smoke_alarm_bridge", "SmokeAlarmBridge"),
        ("leak_detector", "LeakDetector"),
        ("irrigation_controller", "IrrigationController"),
        ("camera_relay", "CameraRelay"),
        ("door_lock_sync", "DoorLockSync"),
    ]
    seq = 1
    for i, (app_key, class_name) in enumerate(apps):
        base = i * APP_TIME_SPACING_SECONDS
        ctx.add_app_manifest(app_key=app_key, class_name=class_name)
        if i == 0:
            # Boot failure followed by a crash on the retry -- the worst-case narrative.
            ctx.add_session(
                started_at=ts(base),
                last_heartbeat_at=ts(base + 5.0),
                stopped_at=ts(base + 5.0),
                status="failure",
                error_type="ConnectionError",
                error_message="Could not reach Home Assistant",
            )
            session_id = ctx.add_session(
                started_at=ts(base + 30.0),
                last_heartbeat_at=ts(base + 90.0),
                stopped_at=ts(base + 90.0),
                status="crashed",
                error_type="RuntimeError",
                error_message="Unhandled exception in bus dispatch",
                error_traceback=(
                    "Traceback (most recent call last):\n  ...\nRuntimeError: Unhandled exception in bus dispatch"
                ),
            )
        else:
            session_id = ctx.add_session(
                started_at=ts(base),
                last_heartbeat_at=ts(base + 90.0),
                stopped_at=ts(base + 90.0),
                status="crashed",
                error_type="RuntimeError",
                error_message=f"{class_name} crashed during startup",
                error_traceback=(
                    f"Traceback (most recent call last):\n  ...\nRuntimeError: {class_name} crashed during startup"
                ),
            )

        listener_id = _seed_listener(
            ctx,
            app_key=app_key,
            handler_method=f"{class_name}.on_state_change",
            topic=STATE_CHANGED_TOPIC,
            name=f"{app_key}_state_listener",
            source_location=f"{app_key}.py:10",
        )
        job_id = _seed_job(
            ctx,
            app_key=app_key,
            job_name=f"{app_key}_health_check",
            handler_method=f"{class_name}.health_check",
            trigger_type="interval",
            trigger_label="every 5 minutes",
            source_location=f"{app_key}.py:25",
        )

        # 20 executions total (15 handler + 5 job), 17 errors (85%) -- deep in "critical".
        _seed_executions(
            ctx,
            scenario="error",
            app_key=app_key,
            session_id=session_id,
            listener_id=listener_id,
            count=15,
            n_errors=13,
            n_thread_leaked=(1 if i == 1 else 0),
            base_offset=base + 100.0,
            error_message=f"{class_name} handler failed",
        )
        _seed_executions(
            ctx,
            scenario="error",
            app_key=app_key,
            session_id=session_id,
            kind="job",
            job_id=job_id,
            count=5,
            n_errors=4,
            start_index=15,
            base_offset=base + 2000.0,
            error_message=f"{class_name} job failed",
        )

        seq = _seed_log_records(
            ctx,
            start_seq=seq,
            count=3,
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            level="ERROR",
            message_prefix=f"{class_name} handler error",
        )
        ctx.add_log_record(
            seq=seq,
            timestamp=ts(base + 95.0),
            level="CRITICAL",
            logger_name=f"hassette.apps.{app_key}",
            message=f"{class_name} session crashed",
            app_key=app_key,
            instance_name=make_instance_name(class_name, 0),
            instance_index=0,
            source_tier="app",
        )
        seq += 1

        # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
        _seed_app_blocking_event(
            ctx,
            session_id=session_id,
            app_key=app_key,
            class_name=class_name,
            detected_ts=ts(base + 50.0),
            stall_duration_ms=3000.0,
        )
        # dup-ignore-end


def scenario_large_volume(ctx: SeedContext) -> None:
    """8-10 fictional apps producing 1000+ executions total, to exercise frontend pagination.

    Error rates vary per app for a mix of health statuses -- exact rates don't need the same
    over-seeded boundary margins used in the degraded/error scenarios below.
    """
    apps = [
        ("hvac_zone_a", "HvacZoneA", 0),
        ("hvac_zone_b", "HvacZoneB", 3),
        ("hvac_zone_c", "HvacZoneC", 8),
        ("hvac_zone_d", "HvacZoneD", 15),
        ("hvac_zone_e", "HvacZoneE", 25),
        ("hvac_zone_f", "HvacZoneF", 40),
        ("hvac_zone_g", "HvacZoneG", 60),
        ("hvac_zone_h", "HvacZoneH", 90),
        ("network_monitor", "NetworkMonitor", 5),
        ("backup_scheduler", "BackupScheduler", 20),
    ]
    exec_count = 120
    seq = 1
    session_ids_by_app: dict[str, int] = {}
    for i, (app_key, class_name, error_pct) in enumerate(apps):
        base = i * APP_TIME_SPACING_SECONDS
        ctx.add_app_manifest(app_key=app_key, class_name=class_name)
        session_id, listener_id, _job_id = _seed_simple_app(
            ctx,
            scenario="large-volume",
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            exec_count=15,
        )
        session_ids_by_app[app_key] = session_id
        remaining = exec_count - 15
        n_errors = min(round(exec_count * error_pct / 100), remaining)
        _seed_executions(
            ctx,
            scenario="large-volume",
            app_key=app_key,
            session_id=session_id,
            listener_id=listener_id,
            count=remaining,
            n_errors=n_errors,
            start_index=15,
            base_offset=base + 900.0,
            interval_seconds=30.0,
        )
        seq = _seed_log_records(
            ctx,
            start_seq=seq,
            count=20,
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            interval_seconds=45.0,
        )

    _seed_app_blocking_event(
        ctx,
        session_id=session_ids_by_app["hvac_zone_g"],
        app_key="hvac_zone_g",
        class_name="HvacZoneG",
        detected_ts=ts(6 * APP_TIME_SPACING_SECONDS + 500.0),
        stall_duration_ms=1500.0,
    )


def scenario_lifecycle(ctx: SeedContext) -> None:
    """4 apps covering all four retired/cancelled combinations from the design doc's
    Lifecycle Field Contract, multi-session apps (crashed + restarted), and a multi-instance
    app (instance_index 0 and 1).
    """
    seq = 1

    # -- sprinkler_controller: one active listener, one retired-only listener --
    app_key, class_name = "sprinkler_controller", "SprinklerController"
    base = 0.0
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    _seed_simple_app(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
        exec_count=10,
    )
    # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
    _seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_legacy_trigger",
        topic="hass.event.legacy_trigger",
        name=f"{app_key}_legacy_listener",
        source_location=f"{app_key}.py:50",
        retired_at=ts(base + 7200.0),
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )
    # dup-ignore-end

    # -- alarm_system: active listener, a cancelled-only job, crashed session then a restart --
    app_key, class_name = "alarm_system", "AlarmSystem"
    base = APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    ctx.add_session(
        started_at=ts(base),
        last_heartbeat_at=ts(base + 30.0),
        stopped_at=ts(base + 30.0),
        status="crashed",
        error_type="RuntimeError",
        error_message="Unhandled exception in event loop",
        error_traceback="Traceback (most recent call last):\n  ...\nRuntimeError: Unhandled exception in event loop",
    )
    running_session_id = ctx.add_session(
        started_at=ts(base + 90.0), last_heartbeat_at=ts(base + HEARTBEAT_OFFSET_SECONDS)
    )
    listener_id = _seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_motion",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_motion_listener",
        source_location=f"{app_key}.py:15",
    )
    _seed_job(
        ctx,
        app_key=app_key,
        job_name=f"{app_key}_nightly_test",
        handler_method=f"{class_name}.nightly_test",
        trigger_type="cron",
        trigger_label="nightly at 02:00",
        source_location=f"{app_key}.py:40",
        removed_at=ts(base + 200.0),
    )
    # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
    _seed_executions(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        session_id=running_session_id,
        listener_id=listener_id,
        count=8,
        base_offset=base + 100.0,
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
        level="ERROR",
        message_prefix="Recovered after crash",
    )
    # dup-ignore-end

    # -- camera_array: multi-instance app; instance 1 has a retired+cancelled listener --
    app_key, class_name = "camera_array", "CameraArray"
    base = 2 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    session_id_0 = _add_running_session(ctx, base)
    listener_id_0 = _seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_motion",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_motion_listener",
        source_location=f"{app_key}.py:18",
    )
    session_id_1 = _add_running_session(ctx, base)
    listener_id_1 = _seed_listener(
        ctx,
        app_key=app_key,
        instance_index=1,
        handler_method=f"{class_name}.on_motion",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_motion_listener",
        source_location=f"{app_key}.py:18",
    )
    # removed during runtime, then retired on the next startup reconciliation -- both set.
    _seed_listener(
        ctx,
        app_key=app_key,
        instance_index=1,
        handler_method=f"{class_name}.on_old_event",
        topic="hass.event.old_topic",
        name=f"{app_key}_old_listener",
        source_location=f"{app_key}.py:60",
        removed_at=ts(base + 1800.0),
        retired_at=ts(base + 3600.0),
    )
    _seed_executions(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        session_id=session_id_0,
        listener_id=listener_id_0,
        count=6,
        base_offset=base,
    )
    # start_index=6 avoids an execution_id collision with instance 0's executions above --
    # both instances share the same app_key by design (that's the point of "multi-instance").
    # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
    _seed_executions(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        session_id=session_id_1,
        listener_id=listener_id_1,
        count=6,
        start_index=6,
        base_offset=base + 400.0,
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        instance_index=1,
        base_offset=base + 400.0,
    )
    # dup-ignore-end

    # -- mail_notifier: normal app, carries the scenario's one blocking event --
    app_key, class_name = "mail_notifier", "MailNotifier"
    base = 3 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
    session_id, _listener_id, _job_id = _seed_simple_app(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
        exec_count=8,
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )
    _seed_app_blocking_event(
        ctx,
        session_id=session_id,
        app_key=app_key,
        class_name=class_name,
        detected_ts=ts(base + 500.0),
        stall_duration_ms=900.0,
    )
    # dup-ignore-end


def scenario_adversarial(ctx: SeedContext) -> None:
    """3 fictional apps that stress UI rendering: 100+ character handler/topic strings, a
    100+ listener fan-out on one app, and Unicode identifiers -- plus DI failures, a
    thread-leaked execution, and both blocking-event tiers.
    """
    seq = 1

    # -- long_handler_names_app: 100+ character handler names, long nested-predicate topics --
    app_key, class_name = "long_handler_names_app", "LongHandlerNamesApp"
    base = 0.0
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    session_id = _add_running_session(ctx, base)
    long_handler = (
        f"{class_name}.on_extremely_verbose_state_change_handler_that_describes_"
        "exactly_what_it_does_in_the_method_name_itself_for_maximum_clarity_and_length"
    )
    long_topic = (
        "hass.event.state_changed.binary_sensor.upstairs_hallway_motion_sensor_near_"
        "the_guest_bedroom_door[state == 'on' and attributes.battery_level > 20 and not context.user_id]"
    )
    listener_id = _seed_listener(
        ctx,
        app_key=app_key,
        handler_method=long_handler,
        topic=long_topic,
        name=f"{app_key}_verbose_listener",
        predicate_description=(
            "lambda e: e.payload.data.new_state.state == 'on' and "
            "e.payload.data.new_state.attributes.get('battery_level', 0) > 20"
        ),
        human_description="battery above 20% and state is on, nested three predicates deep",
        source_location=f"{app_key}.py:200",
    )
    # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
    _seed_executions(
        ctx,
        scenario="adversarial",
        app_key=app_key,
        session_id=session_id,
        listener_id=listener_id,
        count=10,
        n_di_failures=1,
        n_thread_leaked=1,
        base_offset=base,
        error_type="DependencyError",
        error_message="Api dependency not ready during long-running handler",
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )
    # dup-ignore-end

    # -- many_listeners_app: 120 listeners on one app --
    app_key, class_name = "many_listeners_app", "ManyListenersApp"
    base = APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    session_id = _add_running_session(ctx, base)
    n_listeners = 120
    listener_ids = [
        _seed_listener(
            ctx,
            app_key=app_key,
            handler_method=f"{class_name}.on_sensor_{i:03d}",
            topic=f"hass.event.state_changed.sensor.sensor_{i:03d}",
            name=f"{app_key}_listener_{i:03d}",
            source_location=f"{app_key}.py:{10 + i}",
        )
        for i in range(n_listeners)
    ]
    # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
    _seed_executions(
        ctx,
        scenario="adversarial",
        app_key=app_key,
        session_id=session_id,
        listener_id=listener_ids[0],
        count=5,
        base_offset=base,
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )
    # dup-ignore-end

    # -- Unicode app key, listener name, and job name (Japanese + emoji) --
    app_key, class_name = "モーションセンサー_\U0001f3e0", "MotionSensor"
    base = 2 * APP_TIME_SPACING_SECONDS
    # filename override: app_key is Unicode/emoji, not a valid filename on most filesystems.
    ctx.add_app_manifest(app_key=app_key, class_name=class_name, filename=f"{class_name}.py")
    session_id = _add_running_session(ctx, base)
    listener_id = _seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_motion_detected",
        topic=STATE_CHANGED_TOPIC,
        name="動作検知リスナー_\U0001f6b6",
        source_location=f"{class_name}.py:5",
    )
    job_id = _seed_job(
        ctx,
        app_key=app_key,
        job_name="毎日の点検_☀️",
        handler_method=f"{class_name}.daily_check",
        trigger_type="cron",
        trigger_label="毎日午前6時",
        source_location=f"{class_name}.py:20",
    )
    _seed_executions(
        ctx,
        scenario="adversarial",
        app_key=app_key,
        session_id=session_id,
        listener_id=listener_id,
        count=5,
        base_offset=base,
    )
    # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
    _seed_executions(
        ctx,
        scenario="adversarial",
        app_key=app_key,
        session_id=session_id,
        kind="job",
        job_id=job_id,
        count=3,
        start_index=5,
        base_offset=base + 400.0,
    )
    seq = _seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
        message_prefix="動作を検知しました",
    )
    # dup-ignore-end

    # -- Blocking events: both tiers -- one attributed to the Unicode app, one unresolved --
    # dup-ignore-start: scenario boilerplate -- see module docstring for rationale
    _seed_app_blocking_event(
        ctx,
        session_id=session_id,
        app_key=app_key,
        class_name=class_name,
        detected_ts=ts(base + 500.0),
        stall_duration_ms=2500.0,
    )
    # dup-ignore-end
    ctx.add_blocking_event(
        tier=MONKEYPATCH_TIER,
        reason=REASON_FRAMEWORK,
        session_id=None,
        app_key=None,
        instance_name=None,
        instance_index=None,
        primitive="time.sleep",
        source_location="hassette/core/executor.py:88",
        detected_ts=ts(base + 600.0),
        source_tier="framework",
        stall_duration_ms=None,
    )


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
    except (sqlite3.OperationalError, RuntimeError) as exc:
        # A same-path collision most often surfaces during run_migrations(), which wraps any
        # sqlite3.Error (migration_runner.py) in a RuntimeError -- check the cause chain, not
        # just the raised type, and narrow to OperationalError specifically so an unrelated
        # migration bug still propagates with its real traceback instead of this friendlier
        # message.
        cause = exc if isinstance(exc, sqlite3.OperationalError) else exc.__cause__
        if not isinstance(cause, sqlite3.OperationalError):
            raise
        raise SystemExit(
            f"Database error while seeding {output_path}: {cause}\n"
            f"Another seed_db.py run may be writing to this path — wait for it to finish and retry."
        ) from exc

    _print_summary(args.scenario, output_path, summary)


if __name__ == "__main__":
    main()
