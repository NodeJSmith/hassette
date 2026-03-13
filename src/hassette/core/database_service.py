import asyncio
import time
import typing
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import aiosqlite
from alembic import command
from alembic.config import Config

from hassette.resources.base import Service

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.resources.base import Resource

_WriteQueueItem = tuple[Coroutine[Any, Any, Any], asyncio.Future[Any] | None]
"""Type alias for items placed on the DB write queue."""

# Heartbeat interval: 5 minutes
_HEARTBEAT_INTERVAL_SECONDS = 300

# Retention cleanup interval: 1 hour
_RETENTION_INTERVAL_SECONDS = 3600

# Raise from serve() after this many consecutive heartbeat failures
_MAX_CONSECUTIVE_HEARTBEAT_FAILURES = 3


class DatabaseService(Service):
    """Manages the SQLite database for operational telemetry.

    Handles Alembic migrations, heartbeat updates, and retention cleanup
    of old execution records.
    """

    _db: aiosqlite.Connection | None
    """The aiosqlite connection, set during on_initialize."""

    _db_path: Path
    """Resolved path to the SQLite database file."""

    _consecutive_heartbeat_failures: int
    """Counter for consecutive heartbeat failures; triggers RuntimeError after threshold."""

    _db_write_queue: asyncio.Queue[_WriteQueueItem] | None
    """Queue of pending write coroutines; each paired with an optional Future for result delivery."""

    _db_worker_task: asyncio.Task[None] | None
    """Background task that drains _db_write_queue sequentially."""

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._db = None
        self._db_path = Path()
        self._consecutive_heartbeat_failures = 0
        self._db_write_queue = None
        self._db_worker_task = None

    @property
    def config_log_level(self) -> str:
        """Return the log level from the config for this resource."""
        return self.hassette.config.database_service_log_level

    @property
    def db(self) -> aiosqlite.Connection:
        """Return the active database connection.

        Raises:
            RuntimeError: If the database connection is not initialized.
        """
        if self._db is None:
            raise RuntimeError("Database connection is not initialized")
        return self._db

    async def on_initialize(self) -> None:
        """Set up the database: run migrations and open connection."""
        self._consecutive_heartbeat_failures = 0
        self._db_path = self._resolve_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info("Running database migrations for %s", self._db_path)
        await asyncio.to_thread(self._run_migrations)

        self._db = await aiosqlite.connect(self._db_path)

        await self._set_pragmas()

        self._db_write_queue = asyncio.Queue()
        self._db_worker_task = asyncio.create_task(self._db_write_worker())

    async def serve(self) -> None:
        """Run the heartbeat and retention loop until shutdown."""
        self.mark_ready(reason="Database service started")

        last_retention_run = time.monotonic()

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

    async def on_shutdown(self) -> None:
        """Drain the write queue, cancel the worker, then close the database connection."""
        if self._db_worker_task is not None:
            if self._db_write_queue is not None:
                await self._db_write_queue.join()
            self._db_worker_task.cancel()
            await asyncio.gather(self._db_worker_task, return_exceptions=True)
            self._db_worker_task = None

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
                if future is not None:
                    future.set_result(result)
            except Exception as exc:
                if future is not None:
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
            raise RuntimeError("DatabaseService.enqueue() called before on_initialize()")
        self._db_write_queue.put_nowait((coro, None))

    def _resolve_db_path(self) -> Path:
        """Resolve the database path from config or use default."""
        if self.hassette.config.db_path is not None:
            return self.hassette.config.db_path.resolve()
        return self.hassette.config.data_dir / "hassette.db"

    def _run_migrations(self) -> None:
        """Run Alembic migrations to HEAD (synchronous, called via to_thread)."""
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self._db_path.as_posix()}")
        command.upgrade(config, "head")

    async def _set_pragmas(self) -> None:
        """Configure SQLite PRAGMAs for performance and safety."""
        db = self.db
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA wal_autocheckpoint = 1000")
        await db.execute("PRAGMA synchronous = NORMAL")
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.execute("PRAGMA foreign_keys = ON")

    async def _update_heartbeat(self) -> None:
        """Enqueue a heartbeat update for the current session.

        Early-return guards run inline; the DB write is submitted fire-and-forget
        via enqueue(). The caller (serve()) checks _consecutive_heartbeat_failures
        after queue.join() to decide whether to raise RuntimeError.
        """
        if self._db is None:
            return
        try:
            _ = self.hassette.session_id
        except RuntimeError:
            return
        self.enqueue(self._do_update_heartbeat())

    async def _do_update_heartbeat(self) -> None:
        """Execute the heartbeat DB write; called by the write-queue worker."""
        try:
            session_id = self.hassette.session_id
            now = time.time()
            await self._db.execute(  # type: ignore[union-attr]
                "UPDATE sessions SET last_heartbeat_at = ? WHERE id = ?",
                (now, session_id),
            )
            await self._db.commit()  # type: ignore[union-attr]
            self.logger.debug("Heartbeat updated for session %d", session_id)
            if self._consecutive_heartbeat_failures > 0:
                self.logger.info("Heartbeat recovered after %d failure(s)", self._consecutive_heartbeat_failures)
                self._consecutive_heartbeat_failures = 0
        except Exception:
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
        self.enqueue(self._do_run_retention_cleanup())

    async def _do_run_retention_cleanup(self) -> None:
        """Execute the retention DELETE queries; called by the write-queue worker."""
        try:
            retention_days = self.hassette.config.db_retention_days
            cutoff = time.time() - (retention_days * 86400)
            cursor_hi = await self._db.execute(  # type: ignore[union-attr]
                "DELETE FROM handler_invocations WHERE execution_start_ts < ?", (cutoff,)
            )
            cursor_je = await self._db.execute(  # type: ignore[union-attr]
                "DELETE FROM job_executions WHERE execution_start_ts < ?", (cutoff,)
            )
            await self._db.commit()  # type: ignore[union-attr]
            hi_deleted = cursor_hi.rowcount or 0
            je_deleted = cursor_je.rowcount or 0
            if hi_deleted or je_deleted:
                self.logger.info(
                    "Retention cleanup: deleted %d handler_invocations, %d job_executions",
                    hi_deleted,
                    je_deleted,
                )
        except Exception:
            self.logger.exception("Failed to run retention cleanup")
