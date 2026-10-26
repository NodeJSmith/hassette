"""SessionManager — owns all session lifecycle logic for Hassette."""

import time
import typing
from typing import ClassVar

from hassette_wire import LogLevel

from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready

SESSION_STATUS_RUNNING = "running"
SESSION_STATUS_SUCCESS = "success"
SESSION_STATUS_FAILURE = "failure"
SESSION_STATUS_UNKNOWN = "unknown"

if typing.TYPE_CHECKING:
    from hassette import Hassette

    from .database_service import DatabaseService


class SessionManager(Resource):
    """Manages session lifecycle: creation, orphan cleanup, and finalization.

    This is a Resource (no background task). It extracts session CRUD logic that
    was previously inline on ``Hassette``.
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

    async def mark_orphaned_sessions(self) -> None:
        """Mark any sessions left with stopped_at NULL as orphaned."""
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
        """Execute the orphan-session UPDATE; called by the write-queue worker.

        Matches any session left with stopped_at IS NULL from a previous process run —
        not just status='running'. A session already marked 'failure' that never got its
        stopped_at is just as orphaned as one still marked 'running'; both need stopped_at
        backfilled so downstream liveness checks (the once=True listener cleanup's session join,
        in particular) treat them as ended. Only rows
        still 'running' get their status overwritten to 'unknown' — a 'failure' row already
        recorded a real outcome and keeps it, gaining only the backfilled stopped_at.
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
            if self.hassette.fatal_shutdown_reason is not None:
                # The fatal reason is recorded in memory at the decision site, before any teardown, so
                # it is already set by the time the foundation stage gets here.
                await self._database_service.db.execute(
                    "UPDATE sessions SET status = ?, stopped_at = ?, last_heartbeat_at = ?,"
                    " error_message = ?, dropped_overflow = ?, dropped_exhausted = ?, dropped_shutdown = ?"
                    " WHERE id = ?",
                    (
                        SESSION_STATUS_FAILURE,
                        now,
                        now,
                        self.hassette.fatal_shutdown_reason,
                        overflow,
                        exhausted,
                        shutdown,
                        self._session_id,
                    ),
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
