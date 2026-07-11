import asyncio
import sqlite3
import time
import typing
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import aiosqlite

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.migration_runner import _collect_migrations, _read_user_version, run_migrations
from hassette.exceptions import SchemaVersionError
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.types.enums import RestartType
from hassette.types.types import LOG_LEVEL_TYPE

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.config import HassetteConfig
    from hassette.resources.base import Resource

_WriteQueueItem = tuple[Coroutine[Any, Any, Any], asyncio.Future[Any] | None]
"""Type alias for items placed on the DB write queue."""

# Heartbeat interval: 5 minutes
_HEARTBEAT_INTERVAL_SECONDS = 300

# Retention cleanup interval: 1 hour
_RETENTION_INTERVAL_SECONDS = 3600

# Size failsafe interval: 1 hour (same as retention)
_SIZE_FAILSAFE_INTERVAL_SECONDS = 3600

# Maximum iterations per size failsafe invocation
_SIZE_FAILSAFE_MAX_ITERATIONS = 10

# Records to delete per iteration in the size failsafe
_SIZE_FAILSAFE_DELETE_BATCH = 1000

# Pages to free per incremental_vacuum call
_SIZE_FAILSAFE_VACUUM_PAGES = 100

# Raise from serve() after this many consecutive heartbeat failures
_MAX_CONSECUTIVE_HEARTBEAT_FAILURES = 3

_BUSY_TIMEOUT_MS = 5000
"""SQLite busy_timeout (ms) applied to both read and write connections."""

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
_LOG_INSERT_SQL = (
    f"INSERT INTO log_records ({', '.join(_LOG_COLUMNS)}) VALUES ({', '.join(':' + c for c in _LOG_COLUMNS)})"
)


@dataclass(frozen=True)
class RetentionTarget:
    """Declarative specification for a table managed by retention cleanup and size failsafe."""

    table: str
    timestamp_col: str
    priority: int
    retention_days_getter: Callable[["HassetteConfig"], int]
    failsafe_label: str


_RETENTION_TABLES: list[RetentionTarget] = [
    RetentionTarget(
        table="log_records",
        timestamp_col="timestamp",
        priority=0,
        retention_days_getter=lambda cfg: cfg.logging.log_retention_days,
        failsafe_label="log pre-pass",
    ),
    RetentionTarget(
        table="executions",
        timestamp_col="execution_start_ts",
        priority=1,
        retention_days_getter=lambda cfg: cfg.database.retention_days,
        failsafe_label="execution records",
    ),
    RetentionTarget(
        table="blocking_events",
        timestamp_col="detected_ts",
        priority=2,
        retention_days_getter=lambda cfg: cfg.database.retention_days,
        failsafe_label="blocking events",
    ),
]


async def _connect_daemon(database: str | Path, **kwargs: Any) -> aiosqlite.Connection:
    """Open an aiosqlite connection whose worker thread is a daemon.

    aiosqlite creates a non-daemon background thread per connection. If the connection
    is not closed cleanly (e.g. CancelledError during shutdown), the thread blocks
    interpreter exit indefinitely. Setting daemon=True before start() lets the interpreter
    exit even if the thread is still alive.
    """
    conn = aiosqlite.connect(database, **kwargs)
    # No public API exists for this — see aiosqlite#299.
    # Verified against aiosqlite 0.20-0.22.x; re-check on version bumps.
    conn._thread.daemon = True
    return await conn


class DatabaseService(Service):
    """Manages the SQLite database for operational telemetry.

    Handles PRAGMA user_version migrations, heartbeat updates, and retention cleanup
    of old execution records.
    """

    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=120,
        fatal_error_names=("SchemaVersionError",),
    )

    _db: aiosqlite.Connection | None
    """The aiosqlite write connection, set during on_initialize."""

    _read_db: aiosqlite.Connection | None
    """Dedicated read-only connection for TelemetryQueryService. Opened on a separate
    WAL snapshot so reads never block the write worker."""

    _db_path: Path
    """Resolved path to the SQLite database file."""

    _consecutive_heartbeat_failures: int
    """Counter for consecutive heartbeat failures; triggers RuntimeError after threshold."""

    _db_write_queue: asyncio.Queue[_WriteQueueItem] | None
    """Bounded queue of pending write coroutines; each paired with an optional Future for result delivery."""

    _db_worker_task: asyncio.Task[None] | None
    """Background task that drains _db_write_queue sequentially."""

    _consecutive_size_triggers: int
    """Counter for consecutive hourly size failsafe triggers; logged as a warning."""

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._db = None
        self._read_db = None
        self._db_path = Path()
        self._consecutive_heartbeat_failures = 0
        self._consecutive_size_triggers = 0
        self._db_write_queue = None
        self._db_worker_task = None

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.database_service

    @property
    def is_db_ready(self) -> bool:
        """Whether the write database connection is open and usable."""
        return self._db is not None

    @property
    def is_accepting_writes(self) -> bool:
        """Whether the write queue is live and accepting submissions.

        False before ``on_initialize()`` creates the queue and after shutdown drains it.
        """
        return self._db_write_queue is not None

    @property
    def db(self) -> aiosqlite.Connection:
        """Return the active write database connection.

        Raises:
            RuntimeError: If the database connection is not initialized.
        """
        if self._db is None:
            raise RuntimeError("Database connection is not initialized")
        return self._db

    @property
    def read_db(self) -> aiosqlite.Connection:
        """Return the dedicated read-only database connection.

        Uses a separate WAL snapshot so reads never block the write worker.

        Raises:
            RuntimeError: If the read connection is not initialized.
        """
        if self._read_db is None:
            raise RuntimeError("Read database connection is not initialized")
        return self._read_db

    async def on_initialize(self) -> None:
        """Set up the database: check schema version, run migrations and open connection."""
        self._consecutive_heartbeat_failures = 0
        self._consecutive_size_triggers = 0
        self._db_path = self.resolve_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        await self.handle_schema_version(self._db_path)

        self.logger.info("Running database migrations for %s", self._db_path)
        timeout = self.hassette.config.database.migration_timeout_seconds
        await asyncio.wait_for(asyncio.to_thread(self.run_migrations), timeout=timeout)

        self._db = await _connect_daemon(self._db_path, isolation_level=None)
        self._db.row_factory = aiosqlite.Row

        # Open a dedicated read connection on a separate WAL snapshot (F1).
        # This ensures read queries never block the write worker.
        self._read_db = await _connect_daemon(self._db_path, isolation_level=None)
        self._read_db.row_factory = aiosqlite.Row
        await self._read_db.execute("PRAGMA query_only = ON")
        await self._read_db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")

        await self.set_pragmas()
        try:
            await self._check_size_failsafe()
        except Exception:
            self.logger.warning("Startup size failsafe check failed; continuing without cleanup", exc_info=True)

        self._db_write_queue = asyncio.Queue(maxsize=self.hassette.config.database.write_queue_max)
        self._db_worker_task = asyncio.create_task(self.db_write_worker())

    async def serve(self) -> None:
        """Run the heartbeat, retention, and size failsafe loop until shutdown."""
        self.mark_ready(reason="Database service started")

        last_retention_run = time.monotonic()
        last_size_failsafe_run = time.monotonic()

        while True:
            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=_HEARTBEAT_INTERVAL_SECONDS)
                # shutdown_event was set — exit
                self.mark_not_ready(reason="Shutting down")
                return
            except TimeoutError:
                pass

            await self.update_heartbeat()

            if self._consecutive_heartbeat_failures >= _MAX_CONSECUTIVE_HEARTBEAT_FAILURES:
                raise RuntimeError(f"Heartbeat failed {self._consecutive_heartbeat_failures} consecutive times")

            time_since_retention = time.monotonic() - last_retention_run
            if time_since_retention >= _RETENTION_INTERVAL_SECONDS:
                await self.run_retention_cleanup()
                last_retention_run = time.monotonic()

            time_since_size_failsafe = time.monotonic() - last_size_failsafe_run
            if time_since_size_failsafe >= _SIZE_FAILSAFE_INTERVAL_SECONDS:
                await self.run_size_failsafe()
                last_size_failsafe_run = time.monotonic()

    async def on_shutdown(self) -> None:
        """Drain the write queue, cancel the worker, then close the database connection."""
        queue: asyncio.Queue[_WriteQueueItem] | None = None
        try:
            if self._db_worker_task is not None:
                queue, self._db_write_queue = self._db_write_queue, None
                if queue is not None:
                    await queue.join()
                self._db_worker_task.cancel()
                await asyncio.gather(self._db_worker_task, return_exceptions=True)
                self._db_worker_task = None
        except Exception:
            self.logger.exception("Error draining write queue during shutdown")
        finally:
            if self._db_worker_task is not None:
                self._db_worker_task.cancel()
                await asyncio.gather(self._db_worker_task, return_exceptions=True)
                self._db_worker_task = None
            self.close_remaining_queue_items(queue)
            await self.close_connections()

    def close_remaining_queue_items(self, queue: asyncio.Queue[_WriteQueueItem] | None) -> None:
        """Close any coroutines left on the write queue without executing them.

        Called during shutdown to prevent unawaited-coroutine warnings from GC.
        """
        if queue is None:
            return
        closed = 0
        while True:
            try:
                coro, future = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            coro.close()
            if future is not None and not future.done():
                future.cancel()
            queue.task_done()
            closed += 1
        if closed:
            self.logger.debug("Closed %d remaining coroutine(s) from write queue during shutdown", closed)

    async def close_connections(self) -> None:
        """Close both database connections. Idempotent — safe to call multiple times.

        Always attempts both connections even if the first close raises CancelledError.
        aiosqlite's worker threads are set to daemon in on_initialize() as a safety net,
        but this method still does a best-effort close to avoid resource warnings and
        ensure clean WAL checkpoints.
        """
        first_cancel: BaseException | None = None
        for attr in ("_read_db", "_db"):
            conn: aiosqlite.Connection | None = getattr(self, attr)
            if conn is None:
                continue
            try:
                await conn.close()
            except asyncio.CancelledError as exc:  # noqa: ASYNC103 — re-raised after both connections are handled
                conn.stop()
                if first_cancel is None:
                    first_cancel = exc
            except Exception:
                self.logger.exception("Failed to close %s — falling back to sync stop()", attr)
                conn.stop()
            finally:
                thread = getattr(conn, "_thread", None)
                if thread is not None and thread.is_alive():
                    await asyncio.to_thread(thread.join, 5.0)
                    if thread.is_alive():
                        self.logger.warning("aiosqlite background thread for %s did not exit within 5s", attr)
                setattr(self, attr, None)
        if first_cancel is not None:
            raise first_cancel

    async def cleanup(self, timeout: int | None = None) -> None:
        """Close database connections if on_shutdown was interrupted or never ran."""
        await self.close_connections()
        await super().cleanup(timeout)

    async def db_write_worker(self) -> None:
        """Drain _db_write_queue sequentially.

        Each item is a (coroutine, future) pair. If future is not None, the
        coroutine's result (or exception) is delivered through it. If future is
        None, any exception is logged and the worker continues.

        The loop runs until cancelled by on_shutdown().
        """
        if self._db_write_queue is None:
            raise RuntimeError("db_write_worker() started before on_initialize() set _db_write_queue")
        queue = self._db_write_queue
        while True:
            coro, future = await queue.get()
            try:
                result = await coro
                if future is not None and not future.done():
                    future.set_result(result)
            except Exception as exc:
                if future is not None and not future.done():
                    future.set_exception(exc)
                else:
                    self.logger.exception("Unhandled error in enqueued DB write")
            finally:
                queue.task_done()

    async def submit(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Submit a coroutine for serialized execution and await its result.

        The coroutine is placed on the write queue and executed by the single-writer
        worker. The caller is suspended until the coroutine completes.

        Args:
            coro: The coroutine to execute.

        Returns:
            The return value of the coroutine.

        Raises:
            Exception: Whatever exception the coroutine raises.
        """
        if self._db_write_queue is None:
            coro.close()
            raise RuntimeError("DatabaseService.submit() called before on_initialize()")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        try:
            await self._db_write_queue.put((coro, future))
        except BaseException:
            coro.close()
            future.cancel()
            raise
        return await future

    def enqueue(self, coro: Coroutine[Any, Any, Any]) -> bool:
        """Submit a coroutine for fire-and-forget execution.

        Returns immediately. The coroutine is placed on the write queue and
        executed by the single-writer worker. Any exception is logged; the worker
        continues processing subsequent items.

        Args:
            coro: The coroutine to execute.

        Returns:
            True if enqueued successfully, False if dropped due to a full queue.
        """
        if self._db_write_queue is None:
            coro.close()
            raise RuntimeError("DatabaseService.enqueue() called before on_initialize()")
        try:
            self._db_write_queue.put_nowait((coro, None))
        except asyncio.QueueFull:
            coro.close()
            self.logger.error(
                "DB write queue full (%d items) — dropping fire-and-forget task",
                self._db_write_queue.qsize(),
            )
            return False
        qsize = self._db_write_queue.qsize()
        if qsize > 0 and qsize % 100 == 0:
            self.logger.warning("DB write queue depth at %d items — potential backlog", qsize)
        return True

    def resolve_db_path(self) -> Path:
        """Resolve the database path from config or use default."""
        if self.hassette.config.database.path is not None:
            return self.hassette.config.database.path.resolve()
        return self.hassette.config.data_dir / "hassette.db"

    def get_expected_head_version(self) -> int:
        """Return the highest migration version number from migrations_sql/ (synchronous).

        Scans the migrations_sql/ directory for *.sql files with numeric stems
        and returns the largest version number found.
        """
        sql_files = _collect_migrations(None)
        if not sql_files:
            raise RuntimeError("No migration files found in migrations_sql/")
        return max(sql_files)

    def get_current_db_version(self, db_path: Path) -> int:
        """Return PRAGMA user_version from the on-disk DB (synchronous). Returns 0 for fresh databases."""
        return _read_user_version(db_path)

    async def handle_schema_version(self, db_path: Path) -> None:
        """Check schema version and handle mismatches.

        If the DB file does not exist yet, does nothing (migrations will create it).
        If the DB version matches the expected head, does nothing.
        If the DB version is behind head (0 < current < head), does nothing —
        run_migrations() will apply pending migrations incrementally, preserving data.
        If the DB version is 0 on an existing file (pre-PRAGMA-era or fresh DB with
        no migrations applied), deletes the file so migrations recreate it cleanly.
        If the DB version is *ahead* of head (newer DB on older binary), logs an ERROR
        and raises SchemaVersionError — auto-delete is refused in this case.

        Args:
            db_path: Path to the SQLite database file.

        Raises:
            SchemaVersionError: When the DB version is ahead of the expected head version.
            RuntimeError: When the DB file cannot be deleted due to permissions.
        """
        if not db_path.exists():
            return

        expected_head = await asyncio.to_thread(self.get_expected_head_version)
        current_version = await asyncio.to_thread(self.get_current_db_version, db_path)

        if current_version == expected_head:
            return

        if current_version > expected_head:
            self.logger.error(
                "Database schema version %d is ahead of the code's expected head %d. "
                "This usually means a newer binary created this database. "
                "Refusing to auto-delete — upgrade the binary or remove the database manually.",
                current_version,
                expected_head,
            )
            raise SchemaVersionError(
                f"Database schema version {current_version} is ahead of expected head "
                f"{expected_head}. Cannot start safely."
            )

        if current_version > 0:
            self.logger.info(
                "Database schema version %d is behind head %d — pending migrations will be applied.",
                current_version,
                expected_head,
            )
            return

        if current_version == 0:
            self.logger.warning(
                "Database has no schema version (expected %d) — recreating database (no production data to preserve).",
                expected_head,
            )
            try:
                db_path.unlink(missing_ok=True)
                for suffix in ("-wal", "-shm"):
                    Path(str(db_path) + suffix).unlink(missing_ok=True)
            except PermissionError as exc:
                raise RuntimeError(
                    f"Cannot delete stale database file {db_path}: {exc}. Please remove it manually and restart."
                ) from exc

    def run_migrations(self) -> None:
        """Run PRAGMA user_version migrations to the latest version (synchronous, called via to_thread).

        auto_vacuum = INCREMENTAL is set by the runner before any tables are created.
        """
        run_migrations(self._db_path)

    async def set_pragmas(self) -> None:
        """Configure SQLite PRAGMAs for performance and safety."""
        db = self.db
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA wal_autocheckpoint = 1000")
        # NORMAL is an intentional performance tradeoff: in WAL mode, the last committed
        # writes before an OS crash (not app crash) may be lost if not yet checkpointed.
        # This is acceptable for operational telemetry — the orphan-session mechanism
        # compensates for session rows but not for individual telemetry records.
        await db.execute("PRAGMA synchronous = NORMAL")
        await db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        await db.execute("PRAGMA foreign_keys = ON")
        # Intentionally a no-op — auto_vacuum is set by the migration runner before table creation.
        # This line documents intent only.
        await db.execute("PRAGMA auto_vacuum = INCREMENTAL")

    async def update_heartbeat(self) -> None:
        """Await a heartbeat update for the current session.

        Early-return guards run inline; the DB write is awaited via submit()
        so that _consecutive_heartbeat_failures is updated before returning.
        """
        if self._db is None:
            return
        if self._db_write_queue is None:
            return
        try:
            _ = self.hassette.session_id
        except RuntimeError:
            return
        await self.submit(self._do_update_heartbeat())

    async def _do_update_heartbeat(self) -> None:
        """Execute the heartbeat DB write; called by the write-queue worker."""
        try:
            session_id = self.hassette.session_id
            now = time.time()
            await self.db.execute(
                "UPDATE sessions SET last_heartbeat_at = ? WHERE id = ?",
                (now, session_id),
            )
            await self.db.commit()
            self.logger.debug("Heartbeat updated for session %d", session_id)
            if self._consecutive_heartbeat_failures > 0:
                self.logger.info("Heartbeat recovered after %d failure(s)", self._consecutive_heartbeat_failures)
                self._consecutive_heartbeat_failures = 0
        except (sqlite3.Error, OSError, ValueError):
            self._consecutive_heartbeat_failures += 1
            self.logger.exception(
                "Failed to update heartbeat (failure %d/%d)",
                self._consecutive_heartbeat_failures,
                _MAX_CONSECUTIVE_HEARTBEAT_FAILURES,
            )

    async def run_retention_cleanup(self) -> None:
        """Enqueue a retention cleanup; fire-and-forget via enqueue()."""
        if self._db is None:
            return
        if self._db_write_queue is None:
            return
        self.enqueue(self._do_run_retention_cleanup())

    async def _do_run_retention_cleanup(self) -> None:
        """Execute the retention DELETE queries; called by the write-queue worker.

        Iterates _RETENTION_TABLES for simple age-based deletes, then applies
        NOT EXISTS guard deletes for parent tables (listeners, scheduled_jobs).
        """
        try:
            config = self.hassette.config
            now = time.time()
            deleted_by_table: dict[str, int] = {}

            # Explicit BEGIN — aiosqlite opens connections with isolation_level=None (autocommit),
            # so without this BEGIN each DELETE commits individually and the rollback() in the
            # except clause is a no-op. The BEGIN makes the whole cleanup one atomic transaction.
            await self.db.execute("BEGIN")

            for target in _RETENTION_TABLES:
                cutoff = now - (target.retention_days_getter(config) * SECONDS_PER_DAY)
                cursor = await self.db.execute(
                    f"DELETE FROM {target.table} WHERE {target.timestamp_col} < ?",
                    (cutoff,),
                )
                deleted_by_table[target.table] = cursor.rowcount or 0

            # Use the standard retention window for parent-guard deletes.
            cutoff = now - (config.database.retention_days * SECONDS_PER_DAY)

            # Only delete retired listeners when ALL their child executions have also aged out.
            # This prevents orphaning recent executions whose parent row would be
            # deleted because retired_at (set at restart time) diverges from last execution time.
            cursor_rl = await self.db.execute(
                """
                DELETE FROM listeners
                WHERE retired_at IS NOT NULL AND retired_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM executions
                      WHERE listener_id = listeners.id
                        AND execution_start_ts >= ?
                  )
                """,
                (cutoff, cutoff),
            )
            # Same guard for scheduled_jobs.
            cursor_rj = await self.db.execute(
                """
                DELETE FROM scheduled_jobs
                WHERE retired_at IS NOT NULL AND retired_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM executions
                      WHERE job_id = scheduled_jobs.id
                        AND execution_start_ts >= ?
                  )
                """,
                (cutoff, cutoff),
            )
            await self.db.commit()

            listeners_deleted = cursor_rl.rowcount or 0
            jobs_deleted = cursor_rj.rowcount or 0

            deleted_summary = {table: count for table, count in deleted_by_table.items() if count > 0}
            if deleted_summary:
                parts = ", ".join(f"{count} {table}" for table, count in deleted_summary.items())
                self.logger.info("Retention cleanup: deleted %s", parts)
            if listeners_deleted or jobs_deleted:
                self.logger.info(
                    "Retention cleanup: deleted %d retired listeners, %d retired scheduled_jobs",
                    listeners_deleted,
                    jobs_deleted,
                )
        except Exception:
            await self.db.rollback()
            self.logger.exception("Failed to run retention cleanup")

    def get_db_size_mb(self) -> float:
        """Return total database size (main + WAL + SHM) in megabytes."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self._db_path) + suffix)
            if path.exists():
                total += path.stat().st_size
        return total / (1024 * 1024)

    async def _check_size_failsafe(self) -> None:
        """Delete oldest records if database exceeds the configured size limit.

        Iterates _RETENTION_TABLES grouped by priority (lower priority number = deleted
        first). Within each priority tier, all tables in the group are deleted together
        per iteration. After each iteration a vacuum+checkpoint reclaims disk space.
        The process stops as soon as the database falls within the size limit.
        """
        max_size_mb = self.hassette.config.database.max_size_mb
        if max_size_mb == 0:
            return

        current_size = self.get_db_size_mb()
        if current_size <= max_size_mb:
            self._consecutive_size_triggers = 0
            return

        self._consecutive_size_triggers += 1
        if self._consecutive_size_triggers > 1:
            self.logger.warning(
                "Size failsafe triggered %d consecutive times (%.1f MB > %.1f MB limit)",
                self._consecutive_size_triggers,
                current_size,
                max_size_mb,
            )

        db = self.db
        total_deleted_by_table: dict[str, int] = {t.table: 0 for t in _RETENTION_TABLES}

        priorities = sorted({t.priority for t in _RETENTION_TABLES})
        for priority in priorities:
            group = [t for t in _RETENTION_TABLES if t.priority == priority]
            group_label = ", ".join(t.failsafe_label for t in group)

            for iteration in range(_SIZE_FAILSAFE_MAX_ITERATIONS):
                group_deleted = 0
                for target in group:
                    cursor = await db.execute(
                        f"DELETE FROM {target.table} WHERE id IN "
                        f"(SELECT id FROM {target.table} ORDER BY {target.timestamp_col} ASC LIMIT ?)",
                        (_SIZE_FAILSAFE_DELETE_BATCH,),
                    )
                    n = cursor.rowcount or 0
                    total_deleted_by_table[target.table] += n
                    group_deleted += n
                # Commit the batch before vacuuming. PRAGMA wal_checkpoint(TRUNCATE) below
                # cannot run while the delete statements hold a write lock — without this
                # commit it fails with "database table is locked".
                await db.commit()

                if group_deleted == 0:
                    break

                vacuum_cursor = await db.execute(f"PRAGMA incremental_vacuum({_SIZE_FAILSAFE_VACUUM_PAGES})")
                await vacuum_cursor.close()
                await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

                current_size = self.get_db_size_mb()
                if current_size <= max_size_mb:
                    break

                if iteration == _SIZE_FAILSAFE_MAX_ITERATIONS - 1:
                    self.logger.warning(
                        "Size failsafe %s capped at %d iterations; database still %.1f MB (limit %.1f MB)",
                        group_label,
                        _SIZE_FAILSAFE_MAX_ITERATIONS,
                        current_size,
                        max_size_mb,
                    )

            current_size = self.get_db_size_mb()
            if current_size <= max_size_mb:
                break

        deleted_summary = {table: count for table, count in total_deleted_by_table.items() if count > 0}
        if deleted_summary:
            parts = ", ".join(f"{count} {table}" for table, count in deleted_summary.items())
            self.logger.info("Size failsafe: deleted %s (%.1f MB remaining)", parts, current_size)

    async def run_size_failsafe(self) -> None:
        """Enqueue a size failsafe check; fire-and-forget via enqueue()."""
        if self._db is None:
            return
        if self._db_write_queue is None:
            return
        self.enqueue(self._check_size_failsafe())

    async def _insert_log_records(self, records: list[dict]) -> None:
        """Batch-insert log records into the log_records table.

        Must only be called via enqueue() — never await directly.
        """
        if not records:
            return
        db = self.db
        try:
            await db.execute("BEGIN")
            await db.executemany(_LOG_INSERT_SQL, records)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
