import asyncio
import sqlite3
import time
import typing
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import aiosqlite
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from hassette.resources.base import Service
from hassette.types.types import LOG_LEVEL_TYPE

if typing.TYPE_CHECKING:
    from hassette import Hassette
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


class DatabaseService(Service):
    """Manages the SQLite database for operational telemetry.

    Handles Alembic migrations, heartbeat updates, and retention cleanup
    of old execution records.
    """

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
        """Return the log level from the config for this resource."""
        return self.hassette.config.database_service_log_level

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
        self._db_path = self._resolve_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        await self._handle_schema_version(self._db_path)

        self.logger.info("Running database migrations for %s", self._db_path)
        timeout = self.hassette.config.db_migration_timeout_seconds
        await asyncio.wait_for(asyncio.to_thread(self._run_migrations), timeout=timeout)

        self._db = await aiosqlite.connect(self._db_path, isolation_level=None)
        self._db.row_factory = aiosqlite.Row

        # Open a dedicated read connection on a separate WAL snapshot (F1).
        # This ensures read queries never block the write worker.
        self._read_db = await aiosqlite.connect(self._db_path, isolation_level=None)
        self._read_db.row_factory = aiosqlite.Row
        await self._read_db.execute("PRAGMA query_only = ON")
        await self._read_db.execute("PRAGMA busy_timeout = 5000")

        await self._set_pragmas()
        try:
            await self._check_size_failsafe()
        except Exception:
            self.logger.warning("Startup size failsafe check failed; continuing without cleanup", exc_info=True)

        self._db_write_queue = asyncio.Queue(maxsize=self.hassette.config.db_write_queue_max)
        self._db_worker_task = asyncio.create_task(self._db_write_worker())

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

            await self._update_heartbeat()

            if self._consecutive_heartbeat_failures >= _MAX_CONSECUTIVE_HEARTBEAT_FAILURES:
                raise RuntimeError(f"Heartbeat failed {self._consecutive_heartbeat_failures} consecutive times")

            elapsed = time.monotonic() - last_retention_run
            if elapsed >= _RETENTION_INTERVAL_SECONDS:
                await self._run_retention_cleanup()
                last_retention_run = time.monotonic()

            elapsed_size = time.monotonic() - last_size_failsafe_run
            if elapsed_size >= _SIZE_FAILSAFE_INTERVAL_SECONDS:
                await self._run_size_failsafe()
                last_size_failsafe_run = time.monotonic()

    async def on_shutdown(self) -> None:
        """Drain the write queue, cancel the worker, then close the database connection."""
        if self._db_worker_task is not None:
            queue, self._db_write_queue = self._db_write_queue, None
            if queue is not None:
                await queue.join()
            self._db_worker_task.cancel()
            await asyncio.gather(self._db_worker_task, return_exceptions=True)
            self._db_worker_task = None

        if self._read_db is not None:
            try:
                await self._read_db.close()
            except Exception:
                self.logger.exception("Failed to close read database connection")
            finally:
                self._read_db = None

        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                self.logger.exception("Failed to close database connection")
            finally:
                self._db = None

    async def _db_write_worker(self) -> None:
        """Drain _db_write_queue sequentially.

        Each item is a (coroutine, future) pair. If future is not None, the
        coroutine's result (or exception) is delivered through it. If future is
        None, any exception is logged and the worker continues.

        The loop runs until cancelled by on_shutdown().
        """
        if self._db_write_queue is None:
            raise RuntimeError("_db_write_worker() started before on_initialize() set _db_write_queue")
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
        await self._db_write_queue.put((coro, future))
        return await future

    def enqueue(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Submit a coroutine for fire-and-forget execution.

        Returns immediately. The coroutine is placed on the write queue and
        executed by the single-writer worker. Any exception is logged; the worker
        continues processing subsequent items.

        Args:
            coro: The coroutine to execute.
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
            return
        qsize = self._db_write_queue.qsize()
        if qsize > 0 and qsize % 100 == 0:
            self.logger.warning("DB write queue depth at %d items — potential backlog", qsize)

    def _resolve_db_path(self) -> Path:
        """Resolve the database path from config or use default."""
        if self.hassette.config.db_path is not None:
            return self.hassette.config.db_path.resolve()
        return self.hassette.config.data_dir / "hassette.db"

    def _get_expected_head_revision(self) -> str:
        """Return the Alembic head revision this code expects (synchronous).

        Reads the head from Alembic's migration scripts rather than hard-coding,
        so future migrations automatically update the expectation.

        Validates that the revision ID is a zero-padded numeric string (project convention).
        This assertion prevents future contributors from using Alembic's default hex IDs,
        which would break the lexicographic ahead-check in _handle_schema_version.
        """
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        if len(heads) != 1:
            raise RuntimeError(f"Expected exactly one Alembic head, got: {heads}")
        head = heads[0]
        if not head.isdigit() or len(head) < 3:
            raise RuntimeError(
                f"Alembic revision ID {head!r} is not a zero-padded numeric string (≥3 digits). "
                "This project uses numeric revision IDs (e.g. '001') for lexicographic comparison. "
                "Use 'alembic revision --rev-id NNN' to generate correctly formatted IDs."
            )
        return head

    def _get_current_db_revision(self, db_path: Path) -> str | None:
        """Return the current Alembic revision in the on-disk DB, or None if none (synchronous)."""
        engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                return ctx.get_current_revision()
        finally:
            engine.dispose()

    async def _handle_schema_version(self, db_path: Path) -> None:
        """Check schema version and handle mismatches.

        If the DB file does not exist yet, does nothing (migrations will create it).
        If the DB version matches the expected head, does nothing.
        If the DB version is older than head, logs a WARNING and deletes the DB file
        so that migrations recreate it cleanly.
        If the DB version is *ahead* of head (newer DB on older binary), logs an ERROR
        and raises RuntimeError — auto-delete is refused in this case.

        Args:
            db_path: Path to the SQLite database file.

        Raises:
            RuntimeError: When the DB version is ahead of the expected head revision.
            RuntimeError: When the DB file cannot be deleted due to permissions.
        """
        if not db_path.exists():
            return

        expected_head = await asyncio.to_thread(self._get_expected_head_revision)
        current_rev = await asyncio.to_thread(self._get_current_db_revision, db_path)

        if current_rev == expected_head:
            return

        if current_rev is None:
            # No alembic_version table — treat as stale schema needing recreation
            self.logger.warning(
                "Database has no schema version (expected %s) — recreating database (no production data to preserve).",
                expected_head,
            )
        else:
            # Compare revision strings lexicographically as a heuristic for ahead-check.
            # A proper check compares against all known revisions; here we use the
            # convention that revision IDs are padded numeric prefixes (e.g. "001").
            if current_rev > expected_head:
                self.logger.error(
                    "Database schema version %r is ahead of the code's expected head %r. "
                    "This usually means a newer binary created this database. "
                    "Refusing to auto-delete — upgrade the binary or remove the database manually.",
                    current_rev,
                    expected_head,
                )
                raise RuntimeError(
                    f"Database schema version {current_rev!r} is ahead of expected head "
                    f"{expected_head!r}. Cannot start safely."
                )

            self.logger.warning(
                "Database schema version mismatch (current=%r, expected=%r) — "
                "recreating database (no production data to preserve).",
                current_rev,
                expected_head,
            )

        try:
            db_path.unlink(missing_ok=True)
            # Also remove WAL and SHM side-car files if present
            for suffix in ("-wal", "-shm"):
                Path(str(db_path) + suffix).unlink(missing_ok=True)
        except PermissionError as exc:
            raise RuntimeError(
                f"Cannot delete stale database file {db_path}: {exc}. Please remove it manually and restart."
            ) from exc

    def _run_migrations(self) -> None:
        """Run Alembic migrations to HEAD (synchronous, called via to_thread).

        Sets auto_vacuum = INCREMENTAL before Alembic creates any tables. This must
        happen before the first CREATE TABLE (including alembic_version), because
        SQLite requires VACUUM to change auto_vacuum on a database with existing pages.
        """
        conn = sqlite3.connect(self._db_path)
        try:
            current_mode = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
            if current_mode != 2:
                conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
                # On a fresh (zero-page) DB this takes effect immediately.
                # On an existing DB, this is a no-op without VACUUM — acceptable
                # since _handle_schema_version deletes stale DBs before we get here.
        finally:
            conn.close()

        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self._db_path.as_posix()}")
        command.upgrade(config, "head")

    async def _set_pragmas(self) -> None:
        """Configure SQLite PRAGMAs for performance and safety."""
        db = self.db
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA wal_autocheckpoint = 1000")
        # NORMAL is an intentional performance tradeoff: in WAL mode, the last committed
        # writes before an OS crash (not app crash) may be lost if not yet checkpointed.
        # This is acceptable for operational telemetry — the orphan-session mechanism
        # compensates for session rows but not for individual telemetry records.
        await db.execute("PRAGMA synchronous = NORMAL")
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.execute("PRAGMA foreign_keys = ON")
        # Intentionally a no-op — auto_vacuum is set via the Alembic migration before table creation.
        # This line documents intent only.
        await db.execute("PRAGMA auto_vacuum = INCREMENTAL")

    async def _update_heartbeat(self) -> None:
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

    async def _run_retention_cleanup(self) -> None:
        """Enqueue a retention cleanup; fire-and-forget via enqueue()."""
        if self._db is None:
            return
        if self._db_write_queue is None:
            return
        self.enqueue(self._do_run_retention_cleanup())

    async def _do_run_retention_cleanup(self) -> None:
        """Execute the retention DELETE queries; called by the write-queue worker."""
        try:
            retention_days = self.hassette.config.db_retention_days
            cutoff = time.time() - (retention_days * 86400)
            cursor_hi = await self.db.execute("DELETE FROM handler_invocations WHERE execution_start_ts < ?", (cutoff,))
            cursor_je = await self.db.execute("DELETE FROM job_executions WHERE execution_start_ts < ?", (cutoff,))
            # Only delete retired listeners when ALL their child invocations have also aged out.
            # This prevents orphaning recent handler_invocations whose parent row would be
            # deleted because retired_at (set at restart time) diverges from last invocation time.
            cursor_rl = await self.db.execute(
                """
                DELETE FROM listeners
                WHERE retired_at IS NOT NULL AND retired_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM handler_invocations
                      WHERE listener_id = listeners.id
                        AND execution_start_ts >= ?
                  )
                """,
                (cutoff, cutoff),
            )
            # Same guard for scheduled_jobs / job_executions.
            cursor_rj = await self.db.execute(
                """
                DELETE FROM scheduled_jobs
                WHERE retired_at IS NOT NULL AND retired_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM job_executions
                      WHERE job_id = scheduled_jobs.id
                        AND execution_start_ts >= ?
                  )
                """,
                (cutoff, cutoff),
            )
            await self.db.commit()
            hi_deleted = cursor_hi.rowcount or 0
            je_deleted = cursor_je.rowcount or 0
            rl_deleted = cursor_rl.rowcount or 0
            rj_deleted = cursor_rj.rowcount or 0
            if hi_deleted or je_deleted:
                self.logger.info(
                    "Retention cleanup: deleted %d handler_invocations, %d job_executions",
                    hi_deleted,
                    je_deleted,
                )
            if rl_deleted or rj_deleted:
                self.logger.info(
                    "Retention cleanup: deleted %d retired listeners, %d retired scheduled_jobs",
                    rl_deleted,
                    rj_deleted,
                )
        except Exception:
            await self.db.rollback()
            self.logger.exception("Failed to run retention cleanup")

    def _get_db_size_mb(self) -> float:
        """Return total database size (main + WAL + SHM) in megabytes."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self._db_path) + suffix)
            if path.exists():
                total += path.stat().st_size
        return total / (1024 * 1024)

    async def _check_size_failsafe(self) -> None:
        """Delete oldest execution records if database exceeds the configured size limit.

        Skips the sessions table. Loops up to _SIZE_FAILSAFE_MAX_ITERATIONS times,
        deleting _SIZE_FAILSAFE_DELETE_BATCH oldest records per iteration from
        handler_invocations and job_executions, then running incremental_vacuum
        and wal_checkpoint to reclaim disk space.
        """
        max_size_mb = self.hassette.config.db_max_size_mb
        if max_size_mb == 0:
            return

        current_size = self._get_db_size_mb()
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
        total_hi_deleted = 0
        total_je_deleted = 0

        for iteration in range(_SIZE_FAILSAFE_MAX_ITERATIONS):
            cursor_hi = await db.execute(
                "DELETE FROM handler_invocations WHERE id IN "
                "(SELECT id FROM handler_invocations ORDER BY execution_start_ts ASC LIMIT ?)",
                (_SIZE_FAILSAFE_DELETE_BATCH,),
            )
            cursor_je = await db.execute(
                "DELETE FROM job_executions WHERE id IN "
                "(SELECT id FROM job_executions ORDER BY execution_start_ts ASC LIMIT ?)",
                (_SIZE_FAILSAFE_DELETE_BATCH,),
            )
            await db.commit()

            total_hi_deleted += cursor_hi.rowcount or 0
            total_je_deleted += cursor_je.rowcount or 0

            vacuum_cursor = await db.execute(f"PRAGMA incremental_vacuum({_SIZE_FAILSAFE_VACUUM_PAGES})")
            await vacuum_cursor.close()
            await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

            current_size = self._get_db_size_mb()
            if current_size <= max_size_mb:
                break

            if iteration == _SIZE_FAILSAFE_MAX_ITERATIONS - 1:
                self.logger.warning(
                    "Size failsafe loop capped at %d iterations; database still %.1f MB (limit %.1f MB)",
                    _SIZE_FAILSAFE_MAX_ITERATIONS,
                    current_size,
                    max_size_mb,
                )

        if total_hi_deleted or total_je_deleted:
            self.logger.info(
                "Size failsafe: deleted %d handler_invocations, %d job_executions (%.1f MB remaining)",
                total_hi_deleted,
                total_je_deleted,
                current_size,
            )

    async def _run_size_failsafe(self) -> None:
        """Enqueue a size failsafe check; fire-and-forget via enqueue()."""
        if self._db is None:
            return
        if self._db_write_queue is None:
            return
        self.enqueue(self._check_size_failsafe())
