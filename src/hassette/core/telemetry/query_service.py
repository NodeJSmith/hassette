"""TelemetryQueryService: historical telemetry queries backed by DatabaseService."""

import asyncio
import contextlib
import sqlite3
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, ClassVar

import aiosqlite

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.execution_queries import ExecutionQueriesMixin
from hassette.core.telemetry.helpers import DEFAULT_QUERY_LIMIT, DEFAULT_SPARKLINE_BUCKETS, AppHealthAggregates
from hassette.core.telemetry.registration_queries import RegistrationQueriesMixin
from hassette.core.telemetry.summary_queries import SummaryQueriesMixin
from hassette.exceptions import TelemetryUnavailableError
from hassette.resources.base import Resource
from hassette.types.types import LOG_LEVEL_TYPE

if TYPE_CHECKING:
    from hassette import Hassette

# Re-exported for callers that import these from the public query-service entry point.
__all__ = ["DEFAULT_QUERY_LIMIT", "DEFAULT_SPARKLINE_BUCKETS", "AppHealthAggregates", "TelemetryQueryService"]


class TelemetryQueryService(ExecutionQueriesMixin, RegistrationQueriesMixin, SummaryQueriesMixin, Resource):
    """Serves historical telemetry data from the SQLite database.

    The query methods come from the three query mixins and execute real SQL against
    the dedicated read connection. All methods are async and must be awaited.
    """

    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._snapshot_lock = asyncio.Lock()

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.web_api

    async def on_initialize(self) -> None:
        if not self.hassette.config.web_api.run:
            self.mark_ready(reason="Web API disabled")
            return

        # DatabaseService is guaranteed ready by depends_on auto-wait.

        async with self._db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
            mode = row[0] if row else "unknown"
        if mode != "wal":
            raise RuntimeError(
                f"TelemetryQueryService requires WAL journal mode on the read connection, "
                f"got {mode!r}. Snapshot isolation for multi-query reads is not guaranteed."
            )

        self.mark_ready(reason="TelemetryQueryService initialized")

    @property
    def _db(self) -> aiosqlite.Connection:
        """Return the dedicated read-only database connection from DatabaseService."""
        return self.hassette.database_service.read_db

    @contextlib.asynccontextmanager
    async def execute(self, query: str, params: dict[str, Any] | None = None) -> AsyncIterator[aiosqlite.Cursor]:
        """Execute a query with a read timeout, translating storage errors to TelemetryUnavailableError.

        The translation `except` wraps the `yield`, so a storage-tuple exception raised by the
        caller's `async with self.execute(...) as cursor:` body (e.g. from `cursor.fetchall()`) is
        also translated — which is exactly what the degradation contract needs for the fetch path.
        Invariant: keep the caller block to DB I/O only (fetch into a local, then transform/validate
        *outside* the block). Application logic that may raise a non-DB `ValueError` belongs outside,
        so it surfaces as a 500 rather than being mistaken for a closed-connection storage error.
        """
        try:
            async with asyncio.timeout(self.hassette.config.database.read_timeout_seconds):
                async with self._db.execute(query, params) as cursor:
                    yield cursor
        except (sqlite3.Error, OSError, ValueError, TimeoutError) as exc:
            raise TelemetryUnavailableError(str(exc)) from exc

    async def check_health(self) -> None:
        """Verify the database connection is alive."""
        async with self.execute("SELECT 1") as cursor:
            await cursor.fetchone()
