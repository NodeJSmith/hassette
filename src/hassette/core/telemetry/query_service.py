"""TelemetryQueryService: historical telemetry queries backed by DatabaseService."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, ClassVar

import aiosqlite

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.execution_queries import (
    DEFAULT_QUERY_LIMIT,
    check_execution_predates_retention_cutoff,
    get_app_recent_activity,
    get_executions,
    get_handler_invocations_compat,
    get_job_executions_compat,
    get_per_app_activity_buckets,
    get_per_app_last_errors,
    get_recent_invocations_1h,
    get_recent_invocations_1h_all_apps,
)
from hassette.core.telemetry.helpers import (
    AppHealthAggregates,
    _build_app_summaries,
    _row_to_dict,
    _since_clause,
    _source_tier_clause,
)
from hassette.core.telemetry.registration_queries import (
    get_all_jobs_summary,
    get_all_listeners_summary,
    get_job_summary,
    get_listener_summary,
    get_slow_handlers,
)
from hassette.core.telemetry.summary_queries import (
    get_all_app_summaries,
    get_app_health_aggregates,
    get_log_records,
    get_log_records_by_execution,
    get_session_list,
)
from hassette.core.telemetry_models import (
    ActivityFeedEntry,
    AppHealthSummary,
    AppLastError,
    Execution,
    HandlerInvocation,
    JobExecution,
    JobSummary,
    ListenerSummary,
    SessionRecord,
    SlowHandlerRecord,
)
from hassette.resources.base import Resource
from hassette.types.types import LOG_LEVEL_TYPE, QuerySourceTier

if TYPE_CHECKING:
    from hassette import Hassette


class TelemetryQueryService(Resource):
    """Serves historical telemetry data from the SQLite database.

    All query methods execute real SQL against DatabaseService.db.
    Methods are async and must be awaited.
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
        """Execute a query with a read timeout."""
        async with asyncio.timeout(self.hassette.config.database.read_timeout_seconds):
            async with self._db.execute(query, params) as cursor:
                yield cursor

    # ------------------------------------------------------------------
    # Registration queries
    # ------------------------------------------------------------------

    async def get_listener_summary(
        self,
        app_key: str,
        instance_index: int,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[ListenerSummary]:
        """Return per-listener summary for a specific app instance."""
        return await get_listener_summary(self, app_key, instance_index, since=since, source_tier=source_tier)

    async def get_all_listeners_summary(
        self,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[ListenerSummary]:
        """Return per-listener summaries across all apps."""
        return await get_all_listeners_summary(self, since=since, source_tier=source_tier)

    async def get_job_summary(
        self,
        app_key: str,
        instance_index: int,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[JobSummary]:
        """Return per-job summary for a specific app instance."""
        return await get_job_summary(self, app_key, instance_index, since=since, source_tier=source_tier)

    async def get_all_jobs_summary(
        self,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[JobSummary]:
        """Return per-job summaries across all apps."""
        return await get_all_jobs_summary(self, since=since, source_tier=source_tier)

    async def get_slow_handlers(
        self,
        threshold_ms: float,
        limit: int = DEFAULT_QUERY_LIMIT,
        source_tier: QuerySourceTier = "app",
    ) -> list[SlowHandlerRecord]:
        """Return handler executions whose duration exceeds threshold_ms."""
        return await get_slow_handlers(self, threshold_ms, limit=limit, source_tier=source_tier)

    # ------------------------------------------------------------------
    # Execution queries (unified executions table)
    # ------------------------------------------------------------------

    async def get_executions(
        self,
        *,
        listener_id: int | None = None,
        job_id: int | None = None,
        kind: str | None = None,
        limit: int = DEFAULT_QUERY_LIMIT,
        since: float | None = None,
    ) -> list[Execution]:
        """Return recent execution records from the unified executions table.

        Replaces the split ``get_handler_invocations`` / ``get_job_executions`` pair.
        """
        return await get_executions(self, listener_id=listener_id, job_id=job_id, kind=kind, limit=limit, since=since)

    async def get_handler_invocations(
        self, listener_id: int, limit: int = DEFAULT_QUERY_LIMIT, since: float | None = None
    ) -> list[HandlerInvocation]:
        """Return recent invocation records for a specific listener.

        Backward-compat wrapper - T11/T17 migrate callers to get_executions.
        Reads from ``executions`` (kind='handler') against the unified table.
        """
        return await get_handler_invocations_compat(self, listener_id, limit=limit, since=since)

    async def get_job_executions(
        self, job_id: int, limit: int = DEFAULT_QUERY_LIMIT, since: float | None = None
    ) -> list[JobExecution]:
        """Return recent execution records for a specific scheduled job.

        Backward-compat wrapper - T11/T17 migrate callers to get_executions.
        Reads from ``executions`` (kind='job') against the unified table.
        """
        return await get_job_executions_compat(self, job_id, limit=limit, since=since)

    async def get_app_recent_activity(
        self,
        app_key: str,
        instance_index: int | None,
        limit: int,
        since: float | None,
        source_tier: QuerySourceTier,
    ) -> list[ActivityFeedEntry]:
        """Return recent handler invocations and job executions for a single app."""
        return await get_app_recent_activity(self, app_key, instance_index, limit, since, source_tier)

    async def get_per_app_activity_buckets(
        self,
        since: float,
        now: float,
        num_buckets: int = 12,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, list[tuple[int, int]]]:
        """Return bucketed ok/err counts per app_key for sparkline charts."""
        return await get_per_app_activity_buckets(self, since, now, num_buckets=num_buckets, source_tier=source_tier)

    async def get_per_app_last_errors(
        self,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, AppLastError]:
        """Return the most recent error per app_key."""
        return await get_per_app_last_errors(self, since=since, source_tier=source_tier)

    async def get_recent_invocations_1h(
        self,
        app_key: str,
        source_tier: QuerySourceTier = "app",
    ) -> int:
        """Return total handler invocations for a specific app in the last hour."""
        return await get_recent_invocations_1h(self, app_key, source_tier=source_tier)

    async def get_recent_invocations_1h_all_apps(
        self,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, int]:
        """Return handler invocation counts per app_key in the last hour."""
        return await get_recent_invocations_1h_all_apps(self, source_tier=source_tier)

    async def check_execution_predates_retention_cutoff(self, execution_id: str, cutoff: float) -> bool:
        """Check if an execution predates the retention cutoff via the unified executions table."""
        return await check_execution_predates_retention_cutoff(self, execution_id, cutoff)

    # ------------------------------------------------------------------
    # Summary queries
    # ------------------------------------------------------------------

    async def get_app_health_aggregates(
        self,
        app_key: str,
        instance_index: int,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> AppHealthAggregates:
        """Return a single-row aggregate of handler and job health metrics for one app instance."""
        return await get_app_health_aggregates(self, app_key, instance_index, since=since, source_tier=source_tier)

    async def get_all_app_summaries(
        self, since: float | None = None, source_tier: QuerySourceTier = "app"
    ) -> dict[str, AppHealthSummary]:
        """Return per-app health summaries via 4 batch SQL queries."""
        return await get_all_app_summaries(self, since=since, source_tier=source_tier)

    async def get_session_list(self, limit: int = 20) -> list[SessionRecord]:
        """Return recent session records."""
        return await get_session_list(self, limit=limit)

    async def get_log_records(
        self,
        *,
        limit: int = 100,
        since: float | None = None,
        app_key: str | None = None,
        level: str | None = None,
        execution_id: str | None = None,
        source_tier: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch log records with optional filters, ordered by timestamp DESC."""
        return await get_log_records(
            self,
            limit=limit,
            since=since,
            app_key=app_key,
            level=level,
            execution_id=execution_id,
            source_tier=source_tier,
        )

    async def get_log_records_by_execution(
        self,
        execution_id: str,
        *,
        limit: int = 500,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch all log records for a single execution, ordered by seq ASC."""
        return await get_log_records_by_execution(self, execution_id, limit=limit)

    async def check_health(self) -> None:
        """Verify the database connection is alive."""
        async with self.execute("SELECT 1") as cursor:
            await cursor.fetchone()


# Re-exports for callers that import from this module directly
__all__ = [
    "DEFAULT_QUERY_LIMIT",
    "AppHealthAggregates",
    "TelemetryQueryService",
    "_build_app_summaries",
    "_row_to_dict",
    "_since_clause",
    "_source_tier_clause",
]
