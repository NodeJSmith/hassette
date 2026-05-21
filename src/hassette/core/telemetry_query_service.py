"""TelemetryQueryService: historical telemetry queries backed by DatabaseService."""

import asyncio
import contextlib
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar, assert_never

import aiosqlite

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_models import (
    ActivityFeedEntry,
    AppHealthSummary,
    AppLastError,
    HandlerInvocation,
    JobExecution,
    JobSummary,
    ListenerSummary,
    SessionRecord,
    SlowHandlerRecord,
)
from hassette.resources.base import Resource
from hassette.types.types import LOG_LEVEL_TYPE, QuerySourceTier, is_framework_key

if TYPE_CHECKING:
    from hassette import Hassette


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert an aiosqlite Row to a plain dict."""
    return dict(zip(row.keys(), tuple(row), strict=False))


def _source_tier_clause(source_tier: QuerySourceTier, alias: str) -> tuple[str, dict[str, str]]:
    """Return a (fragment, params) tuple for source_tier filtering.

    When ``source_tier`` is ``'all'``, returns ``("", {})`` (no filter).
    Otherwise returns a parameterised fragment and the value as a bind param.

    Args:
        source_tier: One of ``'app'``, ``'framework'``, or ``'all'``.
        alias: The SQL table alias to qualify the ``source_tier`` column.
    """
    # alias is an internal SQL table alias; no user data flows through this parameter
    match source_tier:
        case "all":
            return ("", {})
        case "app" | "framework":
            return (f"AND {alias}.source_tier = :source_tier", {"source_tier": source_tier})
        case _ as unreachable:
            assert_never(unreachable)


def _since_clause(since: float | None, timestamp_col: str) -> tuple[str, dict[str, float]]:
    """Return a (fragment, params) tuple for timestamp lower-bound filtering.

    When ``since`` is not None, returns a parameterised ``AND`` fragment that
    restricts rows to those with ``timestamp_col >= :since``.  When absent,
    returns ``("", {})`` (no filter).

    Mirrors the pattern of :func:`_source_tier_clause`.

    Args:
        since: Unix epoch float lower bound, or ``None`` for no filter.
        timestamp_col: The SQL column expression to filter on (e.g.
            ``"hi.execution_start_ts"``).
    """
    if since is None:
        return ("", {})
    # timestamp_col is an internal SQL column reference; no user data flows here
    return (f"AND {timestamp_col} >= :since", {"since": since})


def _build_app_summaries(
    listener_reg_rows: Iterable[aiosqlite.Row],
    listener_act_rows: Iterable[aiosqlite.Row],
    job_reg_rows: Iterable[aiosqlite.Row],
    job_act_rows: Iterable[aiosqlite.Row],
    source_tier: QuerySourceTier,
) -> dict[str, AppHealthSummary]:
    """Aggregate raw query rows from ``get_all_app_summaries`` into per-app summaries.

    ``source_tier`` controls whether framework app keys are filtered from the result.
    """

    def _index(rows: Iterable[aiosqlite.Row]) -> dict[str, dict[str, Any]]:
        dicts = [_row_to_dict(r) for r in rows]
        return {d["app_key"]: d for d in dicts}

    listener_reg = _index(listener_reg_rows)
    listener_act = _index(listener_act_rows)
    job_reg = _index(job_reg_rows)
    job_act = _index(job_act_rows)

    all_keys = {
        k
        for k in set(listener_reg.keys()) | set(listener_act.keys()) | set(job_reg.keys()) | set(job_act.keys())
        if source_tier in ("framework", "all") or not is_framework_key(k)
    }
    result: dict[str, AppHealthSummary] = {}
    for app_key in all_keys:
        lr = listener_reg.get(app_key, {})
        la = listener_act.get(app_key, {})
        jr = job_reg.get(app_key, {})
        ja = job_act.get(app_key, {})
        last_listener_ts = la.get("last_listener_activity_ts")
        last_job_ts = ja.get("last_job_activity_ts")
        last_times = [t for t in (last_listener_ts, last_job_ts) if t is not None]
        result[app_key] = AppHealthSummary(
            handler_count=lr.get("handler_count", 0),
            job_count=jr.get("job_count", 0),
            total_invocations=la.get("total_invocations", 0),
            total_errors=la.get("total_errors", 0),
            total_timed_out=la.get("total_timed_out", 0),
            total_executions=ja.get("total_executions", 0),
            total_job_errors=ja.get("total_job_errors", 0),
            total_job_timed_out=ja.get("total_job_timed_out", 0),
            avg_duration_ms=la.get("avg_duration_ms", 0.0),
            last_activity_ts=max(last_times) if last_times else None,
        )
    return result


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
        """Return the dedicated read-only database connection from DatabaseService.

        Uses a separate WAL snapshot so reads never block the write worker.
        """
        return self.hassette.database_service.read_db

    async def get_listener_summary(
        self,
        app_key: str,
        instance_index: int,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[ListenerSummary]:
        """Return per-listener summary for a specific app instance.

        ``handler_count`` reflects instance 0 only while ``total_invocations``
        aggregates all instances.

        Args:
            app_key: The app key to filter by.
            instance_index: The app instance index to filter by.
            since: When provided, restrict invocation counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter listeners by source tier. ``'app'`` (default) excludes
                framework internals. ``'all'`` includes all tiers.
        """
        tier_clause, tier_params = _source_tier_clause(source_tier, "l")
        since_join_clause, since_params = _since_clause(since, "hi.execution_start_ts")
        since_err_clause, _ = _since_clause(since, "hi2.execution_start_ts")

        join_condition = f"hi.listener_id = l.id {since_join_clause}"
        params: dict = {"app_key": app_key, "instance_index": instance_index, **tier_params, **since_params}

        query = f"""
            SELECT
                l.id AS listener_id,
                l.app_key,
                l.instance_index,
                l.handler_method,
                l.topic,
                l.debounce,
                l.throttle,
                l.once,
                l.priority,
                l.predicate_description,
                l.human_description,
                l.source_location,
                l.registration_source,
                l.source_tier,
                l.immediate,
                l.duration,
                l.entity_id,
                COUNT(hi.rowid) AS total_invocations,
                SUM(CASE WHEN hi.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN hi.is_di_failure = 1 THEN 1 ELSE 0 END) AS di_failures,
                SUM(CASE WHEN hi.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                SUM(CASE WHEN hi.status = 'timed_out' THEN 1 ELSE 0 END) AS timed_out,
                COALESCE(SUM(hi.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(hi.duration_ms), 0.0) AS avg_duration_ms,
                MIN(hi.duration_ms) AS min_duration_ms,
                MAX(hi.duration_ms) AS max_duration_ms,
                MAX(hi.execution_start_ts) AS last_invoked_at,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message,
                last_err.error_traceback AS last_error_traceback
            FROM listeners l
            LEFT JOIN handler_invocations hi ON {join_condition}
            LEFT JOIN handler_invocations last_err ON last_err.id = (
                SELECT hi2.id FROM handler_invocations hi2
                WHERE hi2.listener_id = l.id AND hi2.status IN ('error', 'timed_out') {since_err_clause}
                ORDER BY hi2.execution_start_ts DESC LIMIT 1
            )
            WHERE l.app_key = :app_key AND l.instance_index = :instance_index
            {tier_clause}
            GROUP BY l.id
        """
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [ListenerSummary.model_validate(_row_to_dict(row)) for row in rows]

    async def get_job_summary(
        self,
        app_key: str,
        instance_index: int,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[JobSummary]:
        """Return per-job summary for a specific app instance.

        Args:
            app_key: The app key to filter by.
            instance_index: The app instance index to filter by.
            since: When provided, restrict execution counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter jobs by source tier. ``'app'`` (default) excludes
                framework internals. ``'all'`` includes all tiers.
        """
        tier_clause, tier_params = _source_tier_clause(source_tier, "sj")
        since_join_clause, since_params = _since_clause(since, "je.execution_start_ts")
        # Params discarded — :since is already in params via since_params above;
        # the same bind name resolves inside the correlated subquery.
        since_err_clause, _ = _since_clause(since, "je2.execution_start_ts")

        join_condition = f"je.job_id = sj.id {since_join_clause}"
        params: dict = {"app_key": app_key, "instance_index": instance_index, **tier_params, **since_params}

        query = f"""
            SELECT
                sj.id AS job_id,
                sj.app_key,
                sj.instance_index,
                sj.job_name,
                sj.handler_method,
                sj.trigger_type,
                sj.trigger_label,
                sj.trigger_detail,
                sj.args_json,
                sj.kwargs_json,
                sj.source_location,
                sj.registration_source,
                sj.source_tier,
                sj."group" AS "group",
                sj.name_auto,
                COUNT(je.rowid) AS total_executions,
                SUM(CASE WHEN je.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN je.status = 'timed_out' THEN 1 ELSE 0 END) AS timed_out,
                MAX(je.execution_start_ts) AS last_executed_at,
                COALESCE(SUM(je.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms,
                MIN(je.duration_ms) AS min_duration_ms,
                MAX(je.duration_ms) AS max_duration_ms,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message,
                last_err.execution_start_ts AS last_error_ts,
                last_err.error_traceback AS last_error_traceback
            FROM scheduled_jobs sj
            LEFT JOIN job_executions je ON {join_condition}
            LEFT JOIN job_executions last_err ON last_err.id = (
                SELECT je2.id FROM job_executions je2
                WHERE je2.job_id = sj.id AND je2.status IN ('error', 'timed_out') {since_err_clause}
                ORDER BY je2.execution_start_ts DESC LIMIT 1
            )
            WHERE sj.app_key = :app_key AND sj.instance_index = :instance_index
            AND sj.cancelled_at IS NULL
            {tier_clause}
            GROUP BY sj.id
        """
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [JobSummary.model_validate(_row_to_dict(row)) for row in rows]

    async def get_all_jobs_summary(
        self,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[JobSummary]:
        """Return per-job summaries across all apps, with no app_key filter.

        Models the single-query approach of ``get_job_summary()`` but without
        the ``app_key``/``instance_index`` WHERE clause.  Uses a ``BEGIN DEFERRED``
        WAL snapshot to ensure the main query and the correlated error subquery
        see a consistent snapshot (same pattern as ``get_all_app_summaries()``).

        Args:
            since: When provided, restrict execution counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter jobs by source tier.  ``'app'`` (default) excludes
                framework internals.  ``'framework'`` returns only internal actors.
                ``'all'`` returns everything.
        """
        tier_clause, tier_params = _source_tier_clause(source_tier, "sj")
        since_join_clause, since_params = _since_clause(since, "je.execution_start_ts")
        # :since is reused inside the correlated subquery via the same bind name.
        since_err_clause, _ = _since_clause(since, "je2.execution_start_ts")

        join_condition = f"je.job_id = sj.id {since_join_clause}"
        params: dict = {**tier_params, **since_params}

        query = f"""
            SELECT
                sj.id AS job_id,
                sj.app_key,
                sj.instance_index,
                sj.job_name,
                sj.handler_method,
                sj.trigger_type,
                sj.trigger_label,
                sj.trigger_detail,
                sj.args_json,
                sj.kwargs_json,
                sj.source_location,
                sj.registration_source,
                sj.source_tier,
                sj."group" AS "group",
                sj.name_auto,
                COUNT(je.rowid) AS total_executions,
                SUM(CASE WHEN je.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN je.status = 'timed_out' THEN 1 ELSE 0 END) AS timed_out,
                MAX(je.execution_start_ts) AS last_executed_at,
                COALESCE(SUM(je.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms,
                MIN(je.duration_ms) AS min_duration_ms,
                MAX(je.duration_ms) AS max_duration_ms,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message,
                last_err.execution_start_ts AS last_error_ts,
                last_err.error_traceback AS last_error_traceback
            FROM scheduled_jobs sj
            LEFT JOIN job_executions je ON {join_condition}
            LEFT JOIN job_executions last_err ON last_err.id = (
                SELECT je2.id FROM job_executions je2
                WHERE je2.job_id = sj.id AND je2.status IN ('error', 'timed_out') {since_err_clause}
                ORDER BY je2.execution_start_ts DESC LIMIT 1
            )
            WHERE sj.cancelled_at IS NULL
            {tier_clause}
            GROUP BY sj.id
        """
        async with self._snapshot_lock:
            try:
                await self._db.execute("BEGIN DEFERRED")
                async with self._db.execute(query, params) as cursor:
                    rows = await cursor.fetchall()
            finally:
                with contextlib.suppress(aiosqlite.OperationalError):
                    await self._db.execute("ROLLBACK")

        return [JobSummary.model_validate(_row_to_dict(row)) for row in rows]

    async def get_all_app_summaries(
        self, since: float | None = None, source_tier: QuerySourceTier = "app"
    ) -> dict[str, AppHealthSummary]:
        """Return per-app health summaries via 4 batch SQL queries.

        Registration counts (handler_count, job_count) use the appropriate
        ``active_*`` views based on ``source_tier``.
        Registration counts reflect instance 0 only.

        Activity counts (invocations, errors, executions, duration averages) aggregate
        across all instances and filter by ``source_tier``.

        Args:
            since: When provided, restrict activity counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter by source tier. ``'app'`` (default) excludes
                framework internals. ``'framework'`` shows only framework actors.
                ``'all'`` includes everything.

        Returns an empty dict when no matching listeners or jobs exist.
        """
        match source_tier:
            case "app":
                listener_view = "active_app_listeners"
                job_view = "active_app_scheduled_jobs"
            case "framework":
                listener_view = "active_framework_listeners"
                job_view = "active_framework_scheduled_jobs"
            case "all":
                listener_view = "active_listeners"
                job_view = "active_scheduled_jobs"
            case _ as unreachable:
                assert_never(unreachable)

        tier_clause, tier_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, tier_je_params = _source_tier_clause(source_tier, "je")
        tier_l_clause, _ = _source_tier_clause(source_tier, "l")
        tier_sj_clause, _ = _source_tier_clause(source_tier, "sj")
        since_hi_clause, since_params = _since_clause(since, "hi.execution_start_ts")
        since_je_clause, _ = _since_clause(since, "je.execution_start_ts")

        listener_reg_query = f"""
            SELECT l.app_key, COUNT(DISTINCT l.id) AS handler_count
            FROM {listener_view} l
            WHERE l.instance_index = 0
            GROUP BY l.app_key
        """
        job_reg_query = f"""
            SELECT sj.app_key, COUNT(DISTINCT sj.id) AS job_count
            FROM {job_view} sj
            WHERE sj.instance_index = 0
            GROUP BY sj.app_key
        """

        listener_act_query = f"""
            SELECT
                l.app_key,
                COUNT(hi.rowid) AS total_invocations,
                SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
                SUM(CASE WHEN hi.status = 'timed_out' THEN 1 ELSE 0 END) AS total_timed_out,
                COALESCE(AVG(hi.duration_ms), 0.0) AS avg_duration_ms,
                MAX(hi.execution_start_ts) AS last_listener_activity_ts
            FROM listeners l
            LEFT JOIN handler_invocations hi ON hi.listener_id = l.id
                {tier_clause}
                {since_hi_clause}
            WHERE 1=1 {tier_l_clause}
            GROUP BY l.app_key
        """
        job_act_query = f"""
            SELECT
                sj.app_key,
                COUNT(je.rowid) AS total_executions,
                SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS total_job_errors,
                SUM(CASE WHEN je.status = 'timed_out' THEN 1 ELSE 0 END) AS total_job_timed_out,
                MAX(je.execution_start_ts) AS last_job_activity_ts
            FROM scheduled_jobs sj
            LEFT JOIN job_executions je ON je.job_id = sj.id
                {tier_je_clause}
                {since_je_clause}
            WHERE 1=1 {tier_sj_clause}
            GROUP BY sj.app_key
        """
        listener_act_params: dict[str, Any] = {**tier_params, **since_params}
        job_act_params: dict[str, Any] = {**tier_je_params, **since_params}

        # BEGIN DEFERRED pins the WAL read mark on the read-only connection,
        # ensuring all four queries see a consistent snapshot. ROLLBACK releases it.
        # The lock serializes access to prevent "cannot start a transaction within a transaction".
        async with self._snapshot_lock:
            try:
                await self._db.execute("BEGIN DEFERRED")
                async with self._db.execute(listener_reg_query) as cursor:
                    listener_reg_rows = await cursor.fetchall()
                async with self._db.execute(listener_act_query, listener_act_params) as cursor:
                    listener_act_rows = await cursor.fetchall()
                async with self._db.execute(job_reg_query) as cursor:
                    job_reg_rows = await cursor.fetchall()
                async with self._db.execute(job_act_query, job_act_params) as cursor:
                    job_act_rows = await cursor.fetchall()
            finally:
                with contextlib.suppress(aiosqlite.OperationalError):
                    await self._db.execute("ROLLBACK")

        return _build_app_summaries(listener_reg_rows, listener_act_rows, job_reg_rows, job_act_rows, source_tier)

    async def get_handler_invocations(
        self, listener_id: int, limit: int = 50, since: float | None = None
    ) -> list[HandlerInvocation]:
        """Return recent invocation records for a specific listener.

        Args:
            listener_id: The listener to query.
            limit: Maximum number of records to return.
            since: When provided, restrict to records with
                ``execution_start_ts >= since`` (Unix epoch float).
        """
        since_hi_clause, since_params = _since_clause(since, "hi.execution_start_ts")
        query = f"""
            SELECT
                hi.execution_start_ts,
                hi.duration_ms,
                hi.status,
                hi.source_tier,
                hi.error_type,
                hi.error_message,
                hi.error_traceback,
                hi.execution_id,
                hi.trigger_context_id,
                hi.trigger_origin
            FROM handler_invocations hi
            WHERE hi.listener_id = :listener_id {since_hi_clause}
            ORDER BY hi.execution_start_ts DESC
            LIMIT :limit
        """
        params: dict = {"listener_id": listener_id, "limit": limit, **since_params}
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [HandlerInvocation.model_validate(_row_to_dict(row)) for row in rows]

    async def get_job_executions(self, job_id: int, limit: int = 50, since: float | None = None) -> list[JobExecution]:
        """Return recent execution records for a specific scheduled job.

        Args:
            job_id: The job to query.
            limit: Maximum number of records to return.
            since: When provided, restrict to records with
                ``execution_start_ts >= since`` (Unix epoch float).
        """
        since_je_clause, since_params = _since_clause(since, "je.execution_start_ts")
        query = f"""
            SELECT
                je.execution_start_ts,
                je.duration_ms,
                je.status,
                je.source_tier,
                je.error_type,
                je.error_message,
                je.error_traceback,
                je.execution_id
            FROM job_executions je
            WHERE je.job_id = :job_id {since_je_clause}
            ORDER BY je.execution_start_ts DESC
            LIMIT :limit
        """
        params: dict = {"job_id": job_id, "limit": limit, **since_params}
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [JobExecution.model_validate(_row_to_dict(row)) for row in rows]

    async def get_slow_handlers(
        self, threshold_ms: float, limit: int = 50, source_tier: QuerySourceTier = "app"
    ) -> list[SlowHandlerRecord]:
        """Return handler invocations whose duration exceeds threshold_ms.

        Uses LEFT JOIN so that orphaned invocations (whose listener was deleted)
        still appear in results with null ``app_key``.

        Args:
            threshold_ms: Only return invocations slower than this value.
            limit: Maximum number of records to return.
            source_tier: Filter by ``source_tier`` on handler_invocations.
                ``'app'`` (default) excludes framework internals.
                ``'all'`` disables the filter.
        """
        tier_clause, tier_params = _source_tier_clause(source_tier, "hi")
        query = f"""
            SELECT
                l.app_key,
                l.handler_method,
                l.topic,
                hi.execution_start_ts,
                hi.duration_ms,
                hi.source_tier
            FROM handler_invocations hi
            LEFT JOIN listeners l ON l.id = hi.listener_id
            WHERE hi.duration_ms > :threshold_ms
                {tier_clause}
            ORDER BY hi.duration_ms DESC
            LIMIT :limit
        """
        async with self._db.execute(query, {"threshold_ms": threshold_ms, "limit": limit, **tier_params}) as cursor:
            rows = await cursor.fetchall()
        return [SlowHandlerRecord.model_validate(_row_to_dict(row)) for row in rows]

    async def get_session_list(self, limit: int = 20) -> list[SessionRecord]:
        """Return recent session records."""
        query = """
            SELECT
                s.id,
                s.started_at,
                s.stopped_at,
                s.status,
                s.error_type,
                s.error_message,
                (COALESCE(s.stopped_at, s.last_heartbeat_at) - s.started_at) AS duration_seconds,
                s.dropped_overflow,
                s.dropped_exhausted,
                s.dropped_no_session,
                s.dropped_shutdown
            FROM sessions s
            ORDER BY s.started_at DESC
            LIMIT :limit
        """
        async with self._db.execute(query, {"limit": limit}) as cursor:
            rows = await cursor.fetchall()
        return [SessionRecord.model_validate(_row_to_dict(row)) for row in rows]

    async def get_per_app_activity_buckets(
        self,
        since: float,
        now: float,
        num_buckets: int = 12,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, list[tuple[int, int]]]:
        """Return bucketed ok/err counts per app_key for sparkline charts.

        Same bucketing logic as ``get_activity_buckets()`` but grouped by app_key.
        Joins through listeners/scheduled_jobs to resolve the app_key for each
        invocation/execution.

        Returns:
            Dict mapping app_key to a list of ``(ok, err)`` tuples per bucket.
            Only app_keys with at least one event in the window are included.
        """
        if now <= since or num_buckets <= 0:
            return {}

        bucket_width = (now - since) / num_buckets
        tier_hi_clause, tier_params = _source_tier_clause(source_tier, "hi")
        # _source_tier_clause always binds :source_tier — same key for both branches
        tier_je_clause, _ = _source_tier_clause(source_tier, "je")

        query = f"""
            SELECT app_key, bucket_idx,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ok,
                SUM(CASE WHEN status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS err
            FROM (
                SELECT l.app_key, hi.status,
                    CAST((hi.execution_start_ts - :since) / :bucket_width AS INTEGER) AS bucket_idx
                FROM handler_invocations hi
                JOIN listeners l ON l.id = hi.listener_id
                WHERE hi.execution_start_ts >= :since AND hi.execution_start_ts < :now
                    {tier_hi_clause}

                UNION ALL

                SELECT sj.app_key, je.status,
                    CAST((je.execution_start_ts - :since) / :bucket_width AS INTEGER) AS bucket_idx
                FROM job_executions je
                JOIN scheduled_jobs sj ON sj.id = je.job_id
                WHERE je.execution_start_ts >= :since AND je.execution_start_ts < :now
                    {tier_je_clause}
            ) combined
            WHERE bucket_idx >= 0 AND bucket_idx < :num_buckets
            GROUP BY app_key, bucket_idx
        """

        params: dict[str, Any] = {
            "since": since,
            "now": now,
            "bucket_width": bucket_width,
            "num_buckets": num_buckets,
            **tier_params,
        }

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        result: dict[str, list[list[int]]] = {}
        for row in rows:
            app_key = row["app_key"]
            if app_key not in result:
                result[app_key] = [[0, 0] for _ in range(num_buckets)]
            idx = int(row["bucket_idx"])
            if 0 <= idx < num_buckets:
                result[app_key][idx][0] = int(row["ok"] or 0)
                result[app_key][idx][1] = int(row["err"] or 0)

        return {k: [(b[0], b[1]) for b in v] for k, v in result.items()}

    async def get_per_app_last_errors(
        self,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, AppLastError]:
        """Return the most recent error per app_key.

        Returns:
            Dict mapping app_key to ``AppLastError``.
            Only apps with at least one error in the window are included.
        """
        since_hi_clause, since_params = _since_clause(since, "hi.execution_start_ts")
        since_je_clause, _ = _since_clause(since, "je.execution_start_ts")
        # _source_tier_clause always binds :source_tier — same key for both branches
        tier_hi_clause, tier_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, _ = _source_tier_clause(source_tier, "je")

        query = f"""
            SELECT app_key, error_message, error_type, execution_start_ts
            FROM (
                SELECT
                    app_key, error_message, error_type, execution_start_ts,
                    ROW_NUMBER() OVER (PARTITION BY app_key ORDER BY execution_start_ts DESC) AS rn
                FROM (
                    SELECT l.app_key, hi.error_message, hi.error_type, hi.execution_start_ts
                    FROM handler_invocations hi
                    JOIN listeners l ON l.id = hi.listener_id
                    WHERE hi.status IN ('error', 'timed_out')
                        {since_hi_clause} {tier_hi_clause}

                    UNION ALL

                    SELECT sj.app_key, je.error_message, je.error_type, je.execution_start_ts
                    FROM job_executions je
                    JOIN scheduled_jobs sj ON sj.id = je.job_id
                    WHERE je.status IN ('error', 'timed_out')
                        {since_je_clause} {tier_je_clause}
                ) combined_inner
            )
            WHERE rn = 1
        """
        params: dict[str, Any] = {**since_params, **tier_params}
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return {
            row["app_key"]: AppLastError(row["error_message"] or "", row["error_type"], row["execution_start_ts"])
            for row in rows
        }

    async def get_recent_invocations_1h(
        self,
        app_key: str,
        source_tier: QuerySourceTier = "app",
    ) -> int:
        """Return total handler invocations for a specific app in the last hour.

        Args:
            app_key: The app to query.
            source_tier: Filter by source tier.

        Returns:
            Count of handler invocations in the last 3600 seconds.
        """
        one_hour_ago = time.time() - 3600.0
        tier_clause, tier_params = _source_tier_clause(source_tier, "hi")

        query = f"""
            SELECT COUNT(hi.rowid) AS invocation_count
            FROM handler_invocations hi
            JOIN listeners l ON l.id = hi.listener_id
            WHERE l.app_key = :app_key
                AND hi.execution_start_ts >= :since
                {tier_clause}
        """
        params: dict[str, Any] = {"app_key": app_key, "since": one_hour_ago, **tier_params}
        async with self._db.execute(query, params) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_recent_invocations_1h_all_apps(
        self,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, int]:
        """Return handler invocation counts per app_key in the last hour.

        Returns:
            Dict mapping app_key to invocation count. Apps with zero invocations are omitted.
        """
        one_hour_ago = time.time() - 3600.0
        tier_clause, tier_params = _source_tier_clause(source_tier, "hi")

        query = f"""
            SELECT l.app_key, COUNT(hi.rowid) AS invocation_count
            FROM handler_invocations hi
            JOIN listeners l ON l.id = hi.listener_id
            WHERE hi.execution_start_ts >= :since
                {tier_clause}
            GROUP BY l.app_key
        """
        params: dict[str, Any] = {"since": one_hour_ago, **tier_params}
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return {row[0]: int(row[1]) for row in rows}

    async def get_app_recent_activity(
        self,
        app_key: str,
        instance_index: int | None,
        limit: int,
        since: float | None,
        source_tier: QuerySourceTier,
    ) -> list[ActivityFeedEntry]:
        """Return recent handler invocations and job executions for a single app, merged and sorted by time.

        Uses a UNION ALL to merge handler_invocations and job_executions, then orders by
        timestamp DESC with a LIMIT.  The ``since`` parameter bounds the scan so that
        typical volumes remain fast without pushing LIMIT into UNION ALL branches.

        Args:
            app_key: The app to query.
            instance_index: When provided, restrict to that instance only.
            limit: Maximum number of entries to return (1-500).
            since: Unix epoch float lower bound for ``execution_start_ts``, or ``None``.
            source_tier: Filter by source tier (``'app'``, ``'framework'``, or ``'all'``).

        Returns:
            List of :class:`ActivityFeedEntry` sorted by ``timestamp`` descending.
        """
        tier_hi_clause, tier_params = _source_tier_clause(source_tier, "hi")
        # _source_tier_clause always binds :source_tier — same key for both branches
        tier_je_clause, _ = _source_tier_clause(source_tier, "je")
        since_hi_clause, since_params = _since_clause(since, "hi.execution_start_ts")
        since_je_clause, _ = _since_clause(since, "je.execution_start_ts")

        instance_hi_clause = ""
        instance_je_clause = ""
        instance_params: dict[str, int] = {}
        if instance_index is not None:
            instance_hi_clause = "AND l.instance_index = :instance_index"
            instance_je_clause = "AND sj.instance_index = :instance_index"
            instance_params = {"instance_index": instance_index}

        query = f"""
            SELECT row_id, status, timestamp, app_key, handler_name, duration_ms, error_type, kind
            FROM (
                SELECT
                    'h-' || CAST(hi.rowid AS TEXT) AS row_id,
                    hi.status,
                    hi.execution_start_ts AS timestamp,
                    l.app_key,
                    l.handler_method AS handler_name,
                    hi.duration_ms,
                    hi.error_type,
                    'handler' AS kind
                FROM handler_invocations hi
                JOIN listeners l ON l.id = hi.listener_id
                WHERE l.app_key = :app_key
                    {instance_hi_clause}
                    {since_hi_clause}
                    {tier_hi_clause}

                UNION ALL

                SELECT
                    'j-' || CAST(je.rowid AS TEXT) AS row_id,
                    je.status,
                    je.execution_start_ts AS timestamp,
                    sj.app_key,
                    sj.handler_method AS handler_name,
                    je.duration_ms,
                    je.error_type,
                    'job' AS kind
                FROM job_executions je
                JOIN scheduled_jobs sj ON sj.id = je.job_id
                WHERE sj.app_key = :app_key
                    {instance_je_clause}
                    {since_je_clause}
                    {tier_je_clause}
            ) combined
            ORDER BY timestamp DESC
            LIMIT :limit
        """

        params: dict[str, Any] = {
            "app_key": app_key,
            "limit": limit,
            **since_params,
            **tier_params,
            **instance_params,
        }

        # Single UNION ALL — no snapshot needed; SQLite guarantees a consistent view per statement.
        # Inner JOINs by design: orphaned invocations (deleted listener/job) are excluded.
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [ActivityFeedEntry.model_validate(_row_to_dict(row)) for row in rows]

    async def check_health(self) -> None:
        """Verify the database connection is alive.

        Raises on any database error; callers catch DB_ERRORS to derive degraded state.
        """
        async with self._db.execute("SELECT 1") as cursor:
            await cursor.fetchone()
