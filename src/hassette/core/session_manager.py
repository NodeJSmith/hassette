"""SessionManager — owns all session lifecycle logic for Hassette."""

import asyncio
import time
import typing

from hassette.bus import Bus
from hassette.event_handling.accessors import get_path
from hassette.event_handling.predicates import ValueIs
from hassette.events import HassetteServiceEvent
from hassette.resources.base import Resource
from hassette.types import Topic
from hassette.types.enums import ResourceStatus
from hassette.types.types import LOG_LEVEL_TYPE

SESSION_STATUS_RUNNING = "running"
SESSION_STATUS_SUCCESS = "success"
SESSION_STATUS_FAILURE = "failure"
SESSION_STATUS_UNKNOWN = "unknown"

if typing.TYPE_CHECKING:
    from hassette import Hassette

    from .database_service import DatabaseService


class SessionManager(Resource):
    """Manages session lifecycle: creation, orphan cleanup, crash recording, and finalization.

    This is a Resource (no background task). It extracts session CRUD logic that
    was previously inline on ``Hassette``.
    """

    bus: Bus

    def __init__(
        self,
        hassette: "Hassette",
        *,
        database_service: "DatabaseService",
        parent: "Resource | None" = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self._database_service = database_service
        self.bus = self.add_child(Bus)
        self._session_id: int | None = None
        self._session_error: bool = False
        self._session_lock = asyncio.Lock()

    async def on_initialize(self) -> None:
        """Register crash listener and signal readiness."""
        await self.bus.on(
            topic=str(Topic.HASSETTE_EVENT_SERVICE_STATUS),
            handler=self.on_service_crashed,
            name="hassette.session_manager.on_service_crashed",
            where=ValueIs(source=get_path("payload.data.status"), condition=ResourceStatus.CRASHED),
        )
        self.mark_ready(reason="SessionManager initialized")

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
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

    async def mark_orphaned_sessions(self) -> None:
        """Mark any sessions left in 'running' status as 'unknown'."""
        await self._database_service.submit(self._do_mark_orphaned_sessions())

    async def create_session(self) -> None:
        """Insert a new session row and store the session ID."""
        self._session_id = await self._database_service.submit(self._do_create_session())
        self.logger.info("Created session %d", self._session_id)

    async def cleanup_stale_once_listeners(self) -> None:
        """Delete stale once=True listeners from previous sessions.

        Must be called after CommandExecutor is ready, not during session creation,
        to avoid racing with unflushed invocation records from the previous session.
        """
        session_id = self._session_id
        if session_id is not None:
            await self._database_service.submit(self._do_cleanup_once_listeners(session_id))

    async def on_service_crashed(self, event: HassetteServiceEvent) -> None:
        """Record service crash details in the session row.

        Called via Bus subscription when any service reaches CRASHED status.
        Sets ``_session_error`` so ``finalize_session()`` preserves the failure status.
        Acquires ``_session_lock`` to coordinate with ``finalize_session()``.
        """
        async with self._session_lock:
            data = event.payload.data
            if self._session_id is None:
                self.logger.warning("Cannot record crash — no active session")
                return

            try:
                _ = self._database_service.db
            except RuntimeError:
                self.logger.warning("Cannot record crash — database not initialized")
                return

            if self._database_service._db_write_queue is None:
                self.logger.warning("Cannot record crash — database write queue shut down")
                return

            self._session_error = True
            self.logger.info("Recorded service crash: %s (%s)", data.resource_name, data.exception_type)
            await self._database_service.submit(self._do_on_service_crashed(event))

    async def finalize_session(
        self,
        *,
        drop_counters: tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        """Write final session status and drop counters before shutdown.

        If ``_session_error`` is True, a CRASHED event already wrote failure
        details — only set timestamps.  Otherwise write ``success``.
        Acquires ``_session_lock`` to coordinate with ``on_service_crashed()``.

        Args:
            drop_counters: (overflow, exhausted, shutdown) from CommandExecutor.
        """
        async with self._session_lock:
            if self._session_id is None:
                return

            try:
                _ = self._database_service.db
            except RuntimeError:
                self.logger.warning("Cannot finalize session — database not initialized")
                return

            await self._database_service.submit(self._do_finalize_session(drop_counters))

    async def _do_mark_orphaned_sessions(self) -> None:
        """Execute the orphan-session UPDATE; called by the write-queue worker."""
        db = self._database_service.db
        cursor = await db.execute(
            "UPDATE sessions SET status = :new_status, stopped_at = last_heartbeat_at WHERE status = :old_status",
            {"new_status": SESSION_STATUS_UNKNOWN, "old_status": SESSION_STATUS_RUNNING},
        )
        if cursor.rowcount and cursor.rowcount > 0:
            self.logger.warning("Marked %d orphaned session(s) as 'unknown'", cursor.rowcount)
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

    async def _do_on_service_crashed(self, event: HassetteServiceEvent) -> None:
        """Execute the crash UPDATE; called by the write-queue worker."""
        data = event.payload.data
        try:
            now = time.time()
            await self._database_service.db.execute(
                "UPDATE sessions SET status = ?, last_heartbeat_at = ?,"
                " error_type = ?, error_message = ?, error_traceback = ? WHERE id = ?",
                (
                    SESSION_STATUS_FAILURE,
                    now,
                    data.exception_type,
                    data.exception,
                    data.exception_traceback,
                    self._session_id,
                ),
            )
            await self._database_service.db.commit()
        except Exception:
            await self._database_service.db.rollback()
            self.logger.exception("Failed to record service crash for session %d", self._session_id)

    async def _do_cleanup_once_listeners(self, current_session_id: int) -> None:
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
            #   - it fired at least once (executions row exists for it)
            #   - the session that owns that execution has stopped
            #   - it has NOT fired in the current session
            stale_cursor = await db.execute(
                """
                SELECT id FROM listeners
                WHERE once = 1
                  AND NOT EXISTS (
                      SELECT 1 FROM executions
                      WHERE listener_id = listeners.id AND session_id = ?
                  )
                  AND EXISTS (
                      SELECT 1 FROM sessions
                      WHERE id = (
                          SELECT session_id FROM executions
                          WHERE listener_id = listeners.id
                          LIMIT 1
                      )
                      AND stopped_at IS NOT NULL
                  )
                """,
                (current_session_id,),
            )
            stale_ids = [row[0] for row in await stale_cursor.fetchall()]

            if not stale_ids:
                return

            placeholders = ",".join("?" * len(stale_ids))

            # Step 1: delete executions referencing these listeners first.
            # executions.listener_id has ON DELETE SET NULL, but the table CHECK requires
            # exactly one of (listener_id, job_id) to be non-NULL.  Deleting the listener
            # would cascade-NULL listener_id and violate that constraint.  Removing the
            # executions rows first sidesteps the cascade entirely.
            await db.execute(
                f"DELETE FROM executions WHERE listener_id IN ({placeholders})",
                stale_ids,
            )

            # Step 2: delete the listener rows (no FK cascade to worry about now).
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
            if self._session_error:
                # CRASHED event already wrote failure details — just set timestamps + counters
                await self._database_service.db.execute(
                    "UPDATE sessions SET stopped_at = ?, last_heartbeat_at = ?,"
                    " dropped_overflow = ?, dropped_exhausted = ?, dropped_shutdown = ?"
                    " WHERE id = ?",
                    (now, now, overflow, exhausted, shutdown, self._session_id),
                )
            else:
                await self._database_service.db.execute(
                    "UPDATE sessions SET status = ?, stopped_at = ?, last_heartbeat_at = ?,"
                    " dropped_overflow = ?, dropped_exhausted = ?, dropped_shutdown = ?"
                    " WHERE id = ?",
                    (SESSION_STATUS_SUCCESS, now, now, overflow, exhausted, shutdown, self._session_id),
                )
            await self._database_service.db.commit()
        except Exception:
            self.logger.exception("Failed to finalize session on shutdown")
