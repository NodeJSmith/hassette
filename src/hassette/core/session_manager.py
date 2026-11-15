"""SessionManager — owns all session lifecycle logic for Hassette."""

import time
import typing
from collections.abc import Callable
from typing import ClassVar

from hassette_wire import LogLevel

from hassette.core.pipeline_counters import PipelineCounter
from hassette.core.telemetry.lifecycle_rows import LifecycleChange
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.utils.warn_pacer import WarnPacer

SESSION_STATUS_RUNNING = "running"
SESSION_STATUS_SUCCESS = "success"
SESSION_STATUS_FAILURE = "failure"
SESSION_STATUS_UNKNOWN = "unknown"

if typing.TYPE_CHECKING:
    from hassette import Hassette

    from .database_service import DatabaseService


class SessionManager(Resource):
    """Manages session lifecycle: creation, orphan cleanup, and finalization.

    This is a Resource (no background task).
    """

    shutdown_hook_timeout_applies: ClassVar[bool] = False
    """A foundation service: the root's foundation stage bounds its shutdown."""

    def __init__(
        self,
        hassette: "Hassette",
        *,
        database_service: "DatabaseService",
        parent: "Resource | None" = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self._database_service = database_service
        self._session_id: int | None = None
        self._repository = TelemetryRepository(database_service)
        self.lifecycle_drop_warn_pacer = WarnPacer()

    async def on_initialize(self) -> None:
        """Signal readiness."""
        mark_ready(self, reason="SessionManager initialized")

    @property
    def config_log_level(self) -> LogLevel:
        """Log level for this service, shared with the database via ``logging.database_service``."""
        return self.hassette.config.logging.database_service

    @property
    def session_id(self) -> int:
        """Return the current session ID.

        Raises:
            RuntimeError: If no session has been created.
        """
        if self._session_id is None:
            raise RuntimeError("Session ID is not initialized")
        return self._session_id

    def write_lifecycle_row(self, build: Callable[[], LifecycleChange]) -> None:
        """Build a change and queue its ``lifecycle_events`` row, stamped with this session and the current time.

        Never raises. Sync and enqueue-only, so sync callers (block reconciliation, the WebSocket receive task's
        done-callback) can call it at the moment of change. A row that never reaches the queue (no session, a
        failed build, a full queue or one yielding to a waiting ``submit()``, the queue not live) is counted under
        ``LIFECYCLE_ROWS_DROPPED`` with a paced WARNING. A queued row whose insert fails is logged by the insert,
        not counted.
        """
        try:
            if self._session_id is None:
                self.count_lifecycle_drop("no session")
                return
            change = build()
            insert_coro = self._repository.insert_lifecycle_event(
                change,
                session_id=self._session_id,
                details_json=change.details.model_dump_json(exclude_none=True),
                ts=time.time(),
            )
            try:
                queued = self._database_service.enqueue(insert_coro)
            except RuntimeError:
                # enqueue() closes the coroutine and raises RuntimeError only when the queue isn't live.
                self.count_lifecycle_drop("write queue not running")
                return
            if not queued:
                self.count_lifecycle_drop("write queue full or yielding to a waiting submit")
        except Exception:
            self.count_lifecycle_drop("unexpected error", exc_info=True)

    def count_lifecycle_drop(self, reason: str, *, exc_info: bool = False) -> None:
        """Count one dropped lifecycle row and log a WARNING, paced by its own ``WarnPacer``.

        Shares its interval setting, ``lifecycle.command_executor_capacity_warn_rate_limit_seconds``, with the
        other paced telemetry WARNINGs, but has its own ``WarnPacer``, so an API-write drop never suppresses a
        lifecycle WARNING.
        """
        self.hassette.pipeline_counters.increment(PipelineCounter.LIFECYCLE_ROWS_DROPPED)
        if not self.lifecycle_drop_warn_pacer.allow(
            self.hassette.config.lifecycle.command_executor_capacity_warn_rate_limit_seconds
        ):
            return
        self.logger.warning(
            "Could not queue lifecycle row (%s); dropping it (counted under %s)",
            reason,
            PipelineCounter.LIFECYCLE_ROWS_DROPPED.name,
            exc_info=exc_info,
        )

    async def mark_orphaned_sessions(self) -> None:
        """Mark sessions left with stopped_at NULL as orphaned, and earlier runs' pending API writes as unresolved."""
        await self._database_service.submit(self._do_mark_orphaned_sessions())

    async def create_session(self) -> None:
        """Insert a new session row and store the session ID."""
        self._session_id = await self._database_service.submit(self._do_create_session())
        self.logger.debug("Created session %d", self._session_id)

    async def cleanup_stale_once_listeners(self) -> None:
        """Delete stale once=True listeners from previous sessions.

        Must be called after CommandExecutor is ready, not during session creation,
        to avoid racing with unflushed invocation records from the previous session.
        """
        if self._session_id is not None:
            await self._database_service.submit(self._do_cleanup_once_listeners())

    async def finalize_session(
        self,
        *,
        drop_counters: tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        """Write final session status and drop counters before shutdown.

        Writes ``failure`` with the fatal reason as ``error_message`` when a fatal shutdown was
        recorded, otherwise ``success``.

        Args:
            drop_counters: (overflow, exhausted, shutdown) from CommandExecutor.
        """
        if self._session_id is None:
            return

        if not self._database_service.is_db_ready:
            self.logger.warning("Cannot finalize session — database not initialized")
            return

        await self._database_service.submit(self._do_finalize_session(drop_counters))

    async def _do_mark_orphaned_sessions(self) -> None:
        """Run the orphan-session and pending-write UPDATE statements; called by the write-queue worker.

        Matches any session left with stopped_at IS NULL from a previous process run —
        not just status='running'. A session already marked 'failure' that never got its
        stopped_at is just as orphaned as one still marked 'running'; both need stopped_at
        backfilled so downstream liveness checks (the once=True listener cleanup's session join,
        in particular) treat them as ended. Only rows still 'running' get their status
        overwritten to 'unknown' — a 'failure' row already recorded a real outcome and keeps it,
        gaining only the backfilled stopped_at.
        """
        db = self._database_service.db
        cursor = await db.execute(
            """
            UPDATE sessions
            SET
                status = CASE WHEN status = :old_status THEN :new_status ELSE status END,
                stopped_at = last_heartbeat_at
            WHERE stopped_at IS NULL
            """,
            {"new_status": SESSION_STATUS_UNKNOWN, "old_status": SESSION_STATUS_RUNNING},
        )
        if cursor.rowcount and cursor.rowcount > 0:
            self.logger.warning("Marked %d orphaned session(s) as ended", cursor.rowcount)
        # Runs before this process creates its session, so every pending write belongs to an earlier
        # process: nothing will resolve it now, whether that process ended cleanly or crashed.
        cursor = await db.execute("UPDATE api_writes SET outcome = 'unresolved' WHERE outcome = 'pending'")
        if cursor.rowcount and cursor.rowcount > 0:
            self.logger.info("Marked %d API write(s) left pending by an earlier run as unresolved", cursor.rowcount)
        await db.commit()

    async def _do_create_session(self) -> int:
        """Execute the session INSERT and return the new row ID; called by the write-queue worker."""
        db = self._database_service.db
        now = time.time()
        cursor = await db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, ?)",
            (now, now, SESSION_STATUS_RUNNING),
        )
        await db.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("INSERT INTO sessions returned no lastrowid")
        return cursor.lastrowid

    async def _do_cleanup_once_listeners(self) -> None:
        """Delete stale once=True listeners from previous sessions.

        Runs after session creation.  Removes ``once=True`` listener rows where:
        - The owning session has already stopped (``stopped_at IS NOT NULL``)
        - No invocation for this listener exists in the current session

        This prevents unbounded row growth from once=True listeners registered by
        long-running apps or framework components that restart across sessions.

        Implementation note: executions.listener_id has ON DELETE SET NULL, but the
        table CHECK requires exactly one of (listener_id, job_id) to be non-NULL.
        Deleting a listener would cascade to NULL out listener_id and break that
        constraint.  We therefore delete the executions rows for the stale listeners
        first (within the same transaction), then delete the listener rows.
        """
        try:
            db = self._database_service.db

            # Identify the stale once=True listener IDs up front.
            # A listener is stale when:
            #   - it fired at least once (an executions row exists for it), and
            #   - none of its executions belong to a still-running session.
            # The current session is running (stopped_at IS NULL), so a listener that
            # fired in it is excluded automatically. Checking every owning session avoids
            # the false positive an arbitrary single-row pick could produce.
            stale_cursor = await db.execute(
                """
                SELECT id FROM listeners
                WHERE once = 1
                  AND EXISTS (
                      SELECT 1 FROM executions WHERE listener_id = listeners.id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM executions
                      JOIN sessions ON sessions.id = executions.session_id
                      WHERE executions.listener_id = listeners.id
                        AND sessions.stopped_at IS NULL
                  )
                """,
            )
            stale_ids = [row[0] for row in await stale_cursor.fetchall()]

            if not stale_ids:
                return

            placeholders = ",".join("?" * len(stale_ids))

            # Explicit BEGIN — aiosqlite opens connections with isolation_level=None
            # (autocommit), so without this each DELETE commits on its own and a crash
            # between the two leaves listener rows whose executions are already gone.
            # The BEGIN makes both deletes one atomic transaction and lets rollback() work.
            await db.execute("BEGIN")

            # Step 1: delete executions referencing these listeners first.
            # executions.listener_id has ON DELETE SET NULL, but the table CHECK requires
            # exactly one of (listener_id, job_id) to be non-NULL.  Deleting the listener
            # would cascade-NULL listener_id and violate that constraint.  Removing the
            # executions rows first sidesteps the cascade entirely.
            await db.execute(
                f"DELETE FROM executions WHERE listener_id IN ({placeholders})",
                stale_ids,
            )

            # Step 2: delete the listener rows (no FK cascade to worry about now). Their listener_misses rows
            # cascade away with them on purpose: a once=True listener that already ran needs no near-miss history.
            await db.execute(
                f"DELETE FROM listeners WHERE id IN ({placeholders})",
                stale_ids,
            )

            await db.commit()
            self.logger.debug("Cleaned up %d stale once=True listener(s) from previous sessions", len(stale_ids))
        except Exception:
            await self._database_service.db.rollback()
            self.logger.exception("Failed to clean up stale once=True listeners")

    async def _do_finalize_session(self, drop_counters: tuple[int, int, int]) -> None:
        """Execute the finalize UPDATE; called by the write-queue worker."""
        overflow, exhausted, shutdown = drop_counters
        try:
            now = time.time()
            # The fatal reason is recorded in memory at the decision site, before any teardown, so
            # it is already set by the time the foundation stage gets here. It is None on a clean
            # shutdown, which leaves error_message NULL as the session INSERT wrote it.
            fatal_reason = self.hassette.fatal_shutdown_reason
            status = SESSION_STATUS_FAILURE if fatal_reason is not None else SESSION_STATUS_SUCCESS
            await self._database_service.db.execute(
                "UPDATE sessions SET status = ?, stopped_at = ?, last_heartbeat_at = ?,"
                " error_message = ?, dropped_overflow = ?, dropped_exhausted = ?, dropped_shutdown = ?"
                " WHERE id = ?",
                (status, now, now, fatal_reason, overflow, exhausted, shutdown, self._session_id),
            )
            await self._database_service.db.commit()
        except Exception:
            self.logger.exception("Failed to finalize session on shutdown")
