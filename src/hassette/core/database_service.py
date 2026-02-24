import asyncio
import time
import typing
from pathlib import Path

import aiosqlite
from alembic import command
from alembic.config import Config

from hassette.bus import Bus
from hassette.events import HassetteServiceEvent
from hassette.resources.base import Service
from hassette.types import ResourceStatus

if typing.TYPE_CHECKING:
    from hassette import Hassette

# Heartbeat interval: 5 minutes
_HEARTBEAT_INTERVAL_SECONDS = 300

# Retention cleanup interval: 1 hour
_RETENTION_INTERVAL_SECONDS = 3600

# Raise from serve() after this many consecutive heartbeat failures
_MAX_CONSECUTIVE_HEARTBEAT_FAILURES = 3


class DatabaseService(Service):
    """Manages the SQLite database for operational telemetry.

    Handles Alembic migrations, session lifecycle tracking, heartbeat updates,
    and retention cleanup of old execution records.
    """

    _db: aiosqlite.Connection | None
    """The aiosqlite connection, set during on_initialize."""

    _session_id: int | None
    """The current session row ID, set during on_initialize."""

    _db_path: Path
    """Resolved path to the SQLite database file."""

    _consecutive_heartbeat_failures: int
    """Counter for consecutive heartbeat failures; triggers RuntimeError after threshold."""

    _bus: Bus
    """Event bus for subscribing to service lifecycle events."""

    _session_error: bool
    """Whether a service crash has been recorded for this session."""

    @classmethod
    def create(cls, hassette: "Hassette") -> "DatabaseService":
        inst = cls(hassette, parent=hassette)
        inst._db = None
        inst._session_id = None
        inst._db_path = Path()
        inst._consecutive_heartbeat_failures = 0
        inst._session_error = False
        return inst

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

    @property
    def session_id(self) -> int:
        """Return the current session ID.

        Raises:
            RuntimeError: If no session has been created.
        """
        if self._session_id is None:
            raise RuntimeError("Session ID is not initialized")
        return self._session_id

    async def on_initialize(self) -> None:
        """Set up the database: run migrations, open connection, create session."""
        self._consecutive_heartbeat_failures = 0
        self._session_error = False
        self._bus = self.add_child(Bus)
        self._db_path = self._resolve_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info("Running database migrations for %s", self._db_path)
        await asyncio.to_thread(self._run_migrations)

        self._db = await aiosqlite.connect(self._db_path)

        await self._set_pragmas()
        await self._mark_orphaned_sessions()
        await self._create_session()

        self._bus.on_hassette_service_crashed(handler=self._on_service_crashed)

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
        """Finalize the session and close the database connection.

        Session status logic:
        - ``_session_error`` is True → a CRASHED event was recorded, keep ``failure``
        - ``self.status`` is FAILED → DatabaseService itself failed (e.g. heartbeat),
          write ``failure`` with no error details (will be restarted)
        - Otherwise → clean shutdown, write ``success``
        """
        self._bus.remove_all_listeners()

        if self._db is not None and self._session_id is not None:
            try:
                now = time.time()
                if self._session_error:
                    # CRASHED event already wrote failure details — just set timestamps
                    await self._db.execute(
                        "UPDATE sessions SET stopped_at = ?, last_heartbeat_at = ? WHERE id = ?",
                        (now, now, self._session_id),
                    )
                elif self.status == ResourceStatus.FAILED:
                    await self._db.execute(
                        "UPDATE sessions SET status = ?, stopped_at = ?, last_heartbeat_at = ? WHERE id = ?",
                        ("failure", now, now, self._session_id),
                    )
                else:
                    await self._db.execute(
                        "UPDATE sessions SET status = ?, stopped_at = ?, last_heartbeat_at = ? WHERE id = ?",
                        ("success", now, now, self._session_id),
                    )
                await self._db.commit()
            except Exception:
                self.logger.exception("Failed to update session on shutdown")

        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                self.logger.exception("Failed to close database connection")
            finally:
                self._db = None

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

    async def _mark_orphaned_sessions(self) -> None:
        """Mark any sessions left in 'running' status as 'unknown'."""
        db = self.db
        cursor = await db.execute(
            "UPDATE sessions SET status = 'unknown', stopped_at = last_heartbeat_at WHERE status = 'running'"
        )
        if cursor.rowcount and cursor.rowcount > 0:
            self.logger.warning("Marked %d orphaned session(s) as 'unknown'", cursor.rowcount)
        await db.commit()

    async def _create_session(self) -> None:
        """Insert a new session row and store the session ID."""
        db = self.db
        now = time.time()
        cursor = await db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (now, now),
        )
        self._session_id = cursor.lastrowid
        await db.commit()
        self.logger.info("Created session %d", self._session_id)

    async def _update_heartbeat(self) -> None:
        """Update the heartbeat timestamp for the current session.

        Tracks consecutive failures. The caller (serve()) checks the failure
        count and raises RuntimeError to trigger ServiceWatcher restart.
        """
        if self._db is None or self._session_id is None:
            return
        try:
            now = time.time()
            await self._db.execute(
                "UPDATE sessions SET last_heartbeat_at = ? WHERE id = ?",
                (now, self._session_id),
            )
            await self._db.commit()
            self.logger.debug("Heartbeat updated for session %d", self._session_id)
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

    async def _on_service_crashed(self, event: HassetteServiceEvent) -> None:
        """Record service crash details in the session row.

        Called via Bus subscription when any service reaches CRASHED status.
        Sets ``_session_error`` so ``on_shutdown()`` preserves the failure status.
        """
        data = event.payload.data
        if self._db is None or self._session_id is None:
            self.logger.warning("Cannot record crash — database not initialized")
            return

        try:
            now = time.time()
            await self._db.execute(
                "UPDATE sessions SET status = 'failure', last_heartbeat_at = ?,"
                " error_type = ?, error_message = ?, error_traceback = ? WHERE id = ?",
                (now, data.exception_type, data.exception, data.exception_traceback, self._session_id),
            )
            await self._db.commit()
            self._session_error = True
            self.logger.info("Recorded service crash: %s (%s)", data.resource_name, data.exception_type)
        except Exception:
            self.logger.exception("Failed to record service crash for session %d", self._session_id)

    async def _run_retention_cleanup(self) -> None:
        """Delete execution records older than the retention window."""
        if self._db is None:
            return
        try:
            retention_days = self.hassette.config.db_retention_days
            cutoff = time.time() - (retention_days * 86400)
            cursor_hi = await self._db.execute(
                "DELETE FROM handler_invocations WHERE execution_start_ts < ?", (cutoff,)
            )
            cursor_je = await self._db.execute("DELETE FROM job_executions WHERE execution_start_ts < ?", (cutoff,))
            await self._db.commit()
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
