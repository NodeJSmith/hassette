import asyncio
import time
import typing
from pathlib import Path

import aiosqlite
from alembic import command
from alembic.config import Config

from hassette.resources.base import Service

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.resources.base import Resource

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

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._db = None
        self._db_path = Path()
        self._consecutive_heartbeat_failures = 0

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
        """Close the database connection."""
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

    async def _update_heartbeat(self) -> None:
        """Update the heartbeat timestamp for the current session.

        Tracks consecutive failures. The caller (serve()) checks the failure
        count and raises RuntimeError to trigger ServiceWatcher restart.
        """
        if self._db is None:
            return
        try:
            session_id = self.hassette.session_id
        except RuntimeError:
            return
        try:
            now = time.time()
            await self._db.execute(
                "UPDATE sessions SET last_heartbeat_at = ? WHERE id = ?",
                (now, session_id),
            )
            await self._db.commit()
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
