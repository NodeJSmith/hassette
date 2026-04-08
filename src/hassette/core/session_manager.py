"""SessionManager — owns all session lifecycle logic for Hassette."""

import asyncio
import time
import typing

from hassette.events import HassetteServiceEvent
from hassette.resources.base import Resource
from hassette.types.types import LOG_LEVEL_TYPE

if typing.TYPE_CHECKING:
    from hassette import Hassette

    from .database_service import DatabaseService


class SessionManager(Resource):
    """Manages session lifecycle: creation, orphan cleanup, crash recording, and finalization.

    This is a Resource (no background task). It extracts session CRUD logic that
    was previously inline on ``Hassette``.
    """

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
        self._session_error: bool = False
        self._session_lock = asyncio.Lock()

    async def on_initialize(self) -> None:
        """Signal readiness — session creation happens later in run_forever()."""
        self.mark_ready(reason="SessionManager initialized")

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.database_service_log_level

    @property
    def session_id(self) -> int:
        """Return the current session ID.

        Raises:
            RuntimeError: If no session has been created.
        """
        if self._session_id is None:
            raise RuntimeError("Session ID is not initialized")
        return self._session_id

    # ------------------------------------------------------------------
    # Public API (called by Hassette)
    # ------------------------------------------------------------------

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

            self._session_error = True
            self.logger.info("Recorded service crash: %s (%s)", data.resource_name, data.exception_type)
            await self._database_service.submit(self._do_on_service_crashed(event))

    async def finalize_session(self) -> None:
        """Write final session status before shutdown.

        If ``_session_error`` is True, a CRASHED event already wrote failure
        details — only set timestamps.  Otherwise write ``success``.
        Acquires ``_session_lock`` to coordinate with ``on_service_crashed()``.
        """
        async with self._session_lock:
            if self._session_id is None:
                return

            try:
                _ = self._database_service.db
            except RuntimeError:
                self.logger.warning("Cannot finalize session — database not initialized")
                return

            await self._database_service.submit(self._do_finalize_session())

    # ------------------------------------------------------------------
    # DB-worker callables (executed by the single-writer queue)
    # ------------------------------------------------------------------

    async def _do_mark_orphaned_sessions(self) -> None:
        """Execute the orphan-session UPDATE; called by the write-queue worker."""
        db = self._database_service.db
        cursor = await db.execute(
            "UPDATE sessions SET status = 'unknown', stopped_at = last_heartbeat_at WHERE status = 'running'"
        )
        if cursor.rowcount and cursor.rowcount > 0:
            self.logger.warning("Marked %d orphaned session(s) as 'unknown'", cursor.rowcount)
        await db.commit()

    async def _do_create_session(self) -> int:
        """Execute the session INSERT and return the new row ID; called by the write-queue worker."""
        db = self._database_service.db
        now = time.time()
        cursor = await db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (now, now),
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
                "UPDATE sessions SET status = 'failure', last_heartbeat_at = ?,"
                " error_type = ?, error_message = ?, error_traceback = ? WHERE id = ?",
                (now, data.exception_type, data.exception, data.exception_traceback, self._session_id),
            )
            await self._database_service.db.commit()
        except Exception:
            self.logger.exception("Failed to record service crash for session %d", self._session_id)

    async def _do_cleanup_once_listeners(self, current_session_id: int) -> None:
        """Delete stale once=True app listeners from previous sessions.

        Runs after session creation.  Removes ``once=True`` listener rows where:
        - ``source_tier = 'app'`` (framework once=True listeners are preserved)
        - The owning session has already stopped (``stopped_at IS NOT NULL``)
        - No invocation for this listener exists in the current session

        This prevents unbounded row growth from once=True listeners registered by
        long-running apps that restart across sessions.
        """
        try:
            await self._database_service.db.execute(
                """
                DELETE FROM listeners
                WHERE once = 1
                  AND source_tier = 'app'
                  AND NOT EXISTS (
                      SELECT 1 FROM handler_invocations
                      WHERE listener_id = listeners.id AND session_id = ?
                  )
                  AND EXISTS (
                      SELECT 1 FROM sessions
                      WHERE id = (
                          SELECT session_id FROM handler_invocations
                          WHERE listener_id = listeners.id
                          LIMIT 1
                      )
                      AND stopped_at IS NOT NULL
                  )
                """,
                (current_session_id,),
            )
            await self._database_service.db.commit()
            self.logger.debug("Cleaned up stale once=True app listeners from previous sessions")
        except Exception:
            await self._database_service.db.rollback()
            self.logger.exception("Failed to clean up stale once=True listeners")

    async def _do_finalize_session(self) -> None:
        """Execute the finalize UPDATE; called by the write-queue worker."""
        try:
            now = time.time()
            if self._session_error:
                # CRASHED event already wrote failure details — just set timestamps
                await self._database_service.db.execute(
                    "UPDATE sessions SET stopped_at = ?, last_heartbeat_at = ? WHERE id = ?",
                    (now, now, self._session_id),
                )
            else:
                await self._database_service.db.execute(
                    "UPDATE sessions SET status = ?, stopped_at = ?, last_heartbeat_at = ? WHERE id = ?",
                    ("success", now, now, self._session_id),
                )
            await self._database_service.db.commit()
        except Exception:
            self.logger.exception("Failed to finalize session on shutdown")
