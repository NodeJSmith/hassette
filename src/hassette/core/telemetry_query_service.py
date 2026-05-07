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
    GlobalSummary,
    HandlerErrorRecord,
    HandlerInvocation,
    JobErrorRecord,
    JobExecution,
    JobGlobalStats,
    JobSummary,
    ListenerGlobalStats,
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


def _build_global_queries(
    since_hi_clause: str,
    since_je_clause: str,
    since_params: dict[str, float],
    total_listeners_subq: str,
    total_jobs_subq: str,
    tier_hi_clause: str,
    tier_je_clause: str,
    tier_hi_params: dict[str, str],
    tier_je_params: dict[str, str],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """Build the listener and job SQL queries (and their params) for ``get_global_summary``.

    Returns ``(listener_query, job_query, listener_params, job_params)``.
    Optional ``since_*`` fragments (from :func:`_since_clause`) add lower-bound
    timestamp filters; they are empty strings when no ``since`` value is provided.
    """
    listener_query = f"""
        SELECT
            {total_listeners_subq} AS total_listeners,
            COUNT(DISTINCT hi.listener_id) AS invoked_listeners,
            COUNT(hi.rowid) AS total_invocations,
            SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
            SUM(CASE WHEN hi.status = 'timed_out' THEN 1 ELSE 0 END) AS total_timed_out,
            SUM(CASE WHEN hi.is_di_failure = 1 THEN 1 ELSE 0 END) AS total_di_failures,
            AVG(hi.duration_ms) AS avg_duration_ms
        FROM handler_invocations hi
        WHERE 1=1 {since_hi_clause} {tier_hi_clause}
    """
    job_query = f"""
        SELECT
            {total_jobs_subq} AS total_jobs,
            COUNT(DISTINCT je.job_id) AS executed_jobs,
            COUNT(je.rowid) AS total_executions,
            SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
            SUM(CASE WHEN je.status = 'timed_out' THEN 1 ELSE 0 END) AS total_timed_out,
            COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms
        FROM job_executions je
        WHERE 1=1 {since_je_clause} {tier_je_clause}
    """

    listener_params: dict[str, Any] = {**tier_hi_params, **since_params}
    job_params: dict[str, Any] = {**tier_je_params, **since_params}

    return listener_query, job_query, listener_params, job_params


def _parse_error_record(d: dict[str, Any]) -> HandlerErrorRecord | JobErrorRecord:
    """Build a typed error record from a row dict returned by the UNION ALL error query.

    ``d["kind"]`` is ``'handler'`` or ``'job'``; ``d["record_id"]`` aliases
    ``listener_id`` or ``job_id`` respectively.
    """
    if d["kind"] == "handler":
        return HandlerErrorRecord(
            listener_id=d["record_id"],
            app_key=d["app_key"],
            handler_method=d["handler_method"],
            topic=d["topic"],
            execution_start_ts=d["execution_start_ts"],
            duration_ms=d["duration_ms"],
            source_tier=d["source_tier"],
            error_type=d["error_type"],
            error_message=d["error_message"],
            error_traceback=d["error_traceback"],
            source_location=d.get("source_location"),
        )
    return JobErrorRecord(
        job_id=d["record_id"],
        app_key=d["app_key"],
        job_name=d["job_name"],
        handler_method=d["handler_method"],
        execution_start_ts=d["execution_start_ts"],
        duration_ms=d["duration_ms"],
        source_tier=d["source_tier"],
        error_type=d["error_type"],
        error_message=d["error_message"],
        error_traceback=d["error_traceback"],
        source_location=d.get("source_location"),
    )


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
        return self.hassette.config.web_api_log_level

    async def on_initialize(self) -> None:
        if not self.hassette.config.run_web_api:
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
                CASE WHEN sj.cancelled_at IS NOT NULL THEN 1 ELSE 0 END AS cancelled,
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
                last_err.execution_start_ts AS last_error_ts
            FROM scheduled_jobs sj
            LEFT JOIN job_executions je ON {join_condition}
            LEFT JOIN job_executions last_err ON last_err.id = (
                SELECT je2.id FROM job_executions je2
                WHERE je2.job_id = sj.id AND je2.status IN ('error', 'timed_out') {since_err_clause}
                ORDER BY je2.execution_start_ts DESC LIMIT 1
            )
            WHERE sj.app_key = :app_key AND sj.instance_index = :instance_index
            {tier_clause}
            GROUP BY sj.id
        """
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
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
        # --- Select view based on source_tier ---
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

        # --- Build registration queries (instance 0, via views) ---
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

        # --- Build activity queries (all instances) ---
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

    async def get_global_summary(
        self, since: float | None = None, source_tier: QuerySourceTier = "app"
    ) -> GlobalSummary:
        """Return aggregate telemetry summary across all apps.

        Args:
            since: When provided, restrict counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter invocations/executions by source tier.
                ``'app'`` (default) counts only app-registered handlers/jobs.
                ``'all'`` counts everything including framework internals.

        Returns a zero-value ``GlobalSummary`` on fresh installs (no telemetry data).
        """
        tier_hi_clause, tier_hi_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, tier_je_params = _source_tier_clause(source_tier, "je")
        since_hi_clause, since_params = _since_clause(since, "hi.execution_start_ts")
        since_je_clause, _ = _since_clause(since, "je.execution_start_ts")

        match source_tier:
            case "app":
                total_listeners_subq = "(SELECT COUNT(*) FROM active_app_listeners)"
                total_jobs_subq = "(SELECT COUNT(*) FROM active_app_scheduled_jobs)"
            case "framework":
                total_listeners_subq = "(SELECT COUNT(*) FROM active_framework_listeners)"
                total_jobs_subq = "(SELECT COUNT(*) FROM active_framework_scheduled_jobs)"
            case "all":
                total_listeners_subq = "(SELECT COUNT(*) FROM active_listeners)"
                total_jobs_subq = "(SELECT COUNT(*) FROM active_scheduled_jobs)"
            case _ as unreachable:
                assert_never(unreachable)

        listener_query, job_query, listener_params, job_params = _build_global_queries(
            since_hi_clause,
            since_je_clause,
            since_params,
            total_listeners_subq,
            total_jobs_subq,
            tier_hi_clause,
            tier_je_clause,
            tier_hi_params,
            tier_je_params,
        )

        # BEGIN DEFERRED pins the WAL read snapshot so both queries see consistent state.
        # The lock serializes access to prevent "cannot start a transaction within a transaction".
        async with self._snapshot_lock:
            try:
                await self._db.execute("BEGIN DEFERRED")
                async with self._db.execute(listener_query, listener_params) as cursor:
                    listener_row = await cursor.fetchone()
                async with self._db.execute(job_query, job_params) as cursor:
                    job_row = await cursor.fetchone()
            finally:
                with contextlib.suppress(aiosqlite.OperationalError):
                    await self._db.execute("ROLLBACK")

        listener_data = _row_to_dict(listener_row) if listener_row else {}
        job_data = _row_to_dict(job_row) if job_row else {}

        return GlobalSummary(
            listeners=ListenerGlobalStats(
                total_listeners=listener_data.get("total_listeners", 0),
                invoked_listeners=listener_data.get("invoked_listeners", 0),
                total_invocations=listener_data.get("total_invocations", 0),
                total_errors=listener_data.get("total_errors", 0) or 0,
                total_timed_out=listener_data.get("total_timed_out", 0) or 0,
                total_di_failures=listener_data.get("total_di_failures", 0) or 0,
                avg_duration_ms=listener_data.get("avg_duration_ms"),
            ),
            jobs=JobGlobalStats(
                total_jobs=job_data.get("total_jobs", 0),
                executed_jobs=job_data.get("executed_jobs", 0),
                total_executions=job_data.get("total_executions", 0),
                total_errors=job_data.get("total_errors", 0) or 0,
                total_timed_out=job_data.get("total_timed_out", 0) or 0,
                avg_duration_ms=job_data.get("avg_duration_ms", 0.0) or 0.0,
            ),
        )

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

    async def get_error_counts(
        self,
        since_ts: float,
        session_id: int | None = None,  # Internal test seam only — not exposed via routes
        source_tier: QuerySourceTier = "app",
    ) -> tuple[int, int]:
        """Return (handler_error_count, job_error_count) since a given timestamp.

        Uses COUNT(*) queries — no row materialization. Suitable for badge counts
        where exact numbers are needed without a LIMIT cap.
        """
        session_filter_hi = "AND hi.session_id = :session_id" if session_id is not None else ""
        session_filter_je = "AND je.session_id = :session_id" if session_id is not None else ""
        tier_hi_clause, tier_hi_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, tier_je_params = _source_tier_clause(source_tier, "je")

        handler_query = f"""
            SELECT COUNT(*) FROM handler_invocations hi
            WHERE hi.status IN ('error', 'timed_out') AND hi.execution_start_ts > :since_ts
                {session_filter_hi} {tier_hi_clause}
        """
        job_query = f"""
            SELECT COUNT(*) FROM job_executions je
            WHERE je.status IN ('error', 'timed_out') AND je.execution_start_ts > :since_ts
                {session_filter_je} {tier_je_clause}
        """

        hi_params_dict: dict = {"since_ts": since_ts, **tier_hi_params}
        if session_id is not None:
            hi_params_dict["session_id"] = session_id

        je_params_dict: dict = {"since_ts": since_ts, **tier_je_params}
        if session_id is not None:
            je_params_dict["session_id"] = session_id

        async with self._db.execute(handler_query, hi_params_dict) as cursor:
            handler_count = (await cursor.fetchone())[0]  # pyright: ignore[reportOptionalSubscript]
        async with self._db.execute(job_query, je_params_dict) as cursor:
            job_count = (await cursor.fetchone())[0]  # pyright: ignore[reportOptionalSubscript]

        return handler_count, job_count

    async def get_recent_errors(
        self,
        since_ts: float,
        limit: int = 50,
        session_id: int | None = None,  # Internal test seam only — not exposed via routes
        source_tier: QuerySourceTier = "app",
    ) -> list[HandlerErrorRecord | JobErrorRecord]:
        """Return recent error records since a given timestamp.

        Uses a single UNION ALL query with LEFT JOINs so that orphaned records
        (whose listener/job was deleted) are still returned with null FK fields.
        A single ORDER BY + LIMIT applies globally across both record types.

        Args:
            since_ts: Only return records with ``execution_start_ts > since_ts``.
            limit: Maximum number of records to return (applied globally).
            session_id: Internal test seam — not exposed via routes.
            source_tier: Filter by ``source_tier`` column on the invocation/execution
                table. ``'app'`` (default) excludes framework internals.
                ``'all'`` disables the filter entirely.
        """
        session_filter_hi = "AND hi.session_id = :session_id" if session_id is not None else ""
        session_filter_je = "AND je.session_id = :session_id" if session_id is not None else ""

        # Build source_tier fragments (parameterised — no string interpolation of values)
        tier_hi_clause, tier_hi_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, _ = _source_tier_clause(source_tier, "je")

        query = f"""
            SELECT
                'handler' AS kind,
                hi.listener_id AS record_id,
                l.app_key,
                l.handler_method,
                l.topic,
                NULL AS job_name,
                hi.execution_start_ts,
                hi.duration_ms,
                hi.source_tier,
                hi.error_type,
                hi.error_message,
                hi.error_traceback,
                l.source_location
            FROM handler_invocations hi
            LEFT JOIN listeners l ON l.id = hi.listener_id
            WHERE hi.status IN ('error', 'timed_out')
                AND hi.execution_start_ts > :since_ts
                {session_filter_hi}
                {tier_hi_clause}

            UNION ALL

            SELECT
                'job' AS kind,
                je.job_id AS record_id,
                sj.app_key,
                sj.handler_method,
                NULL AS topic,
                sj.job_name,
                je.execution_start_ts,
                je.duration_ms,
                je.source_tier,
                je.error_type,
                je.error_message,
                je.error_traceback,
                sj.source_location
            FROM job_executions je
            LEFT JOIN scheduled_jobs sj ON sj.id = je.job_id
            WHERE je.status IN ('error', 'timed_out')
                AND je.execution_start_ts > :since_ts
                {session_filter_je}
                {tier_je_clause}

            ORDER BY execution_start_ts DESC
            LIMIT :limit
        """

        # Named params: since_ts and source_tier are shared across both UNION halves
        params: dict = {"since_ts": since_ts, "limit": limit, **tier_hi_params}
        if session_id is not None:
            params["session_id"] = session_id

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [_parse_error_record(_row_to_dict(row)) for row in rows]

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

    async def get_activity_feed(
        self,
        limit: int = 20,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[ActivityFeedEntry]:
        """Return recent cross-app activity (handler invocations + job executions), merged and sorted by timestamp.

        Args:
            limit: Maximum number of entries to return.
            since: When provided, restrict to records with ``execution_start_ts >= since``.
            source_tier: Filter by source tier. ``'app'`` (default) excludes framework internals.
        """
        tier_hi_clause, tier_hi_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, _ = _source_tier_clause(source_tier, "je")
        since_hi_clause, since_params = _since_clause(since, "hi.execution_start_ts")
        since_je_clause, _ = _since_clause(since, "je.execution_start_ts")

        query = f"""
            SELECT
                hi.status,
                hi.execution_start_ts AS timestamp,
                COALESCE(l.app_key, '') AS app_key,
                COALESCE(l.handler_method, '') AS handler_name,
                hi.duration_ms,
                hi.error_type,
                'handler' AS kind
            FROM handler_invocations hi
            LEFT JOIN listeners l ON l.id = hi.listener_id
            WHERE 1=1 {since_hi_clause} {tier_hi_clause}

            UNION ALL

            SELECT
                je.status,
                je.execution_start_ts AS timestamp,
                COALESCE(sj.app_key, '') AS app_key,
                COALESCE(sj.handler_method, '') AS handler_name,
                je.duration_ms,
                je.error_type,
                'job' AS kind
            FROM job_executions je
            LEFT JOIN scheduled_jobs sj ON sj.id = je.job_id
            WHERE 1=1 {since_je_clause} {tier_je_clause}

            ORDER BY timestamp DESC
            LIMIT :limit
        """

        params: dict[str, Any] = {"limit": limit, **tier_hi_params, **since_params}
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [
            ActivityFeedEntry(
                status=row["status"],
                timestamp=row["timestamp"],
                app_key=row["app_key"],
                handler_name=row["handler_name"],
                duration_ms=row["duration_ms"],
                error_type=row["error_type"],
                kind=row["kind"],
            )
            for row in rows
        ]

    async def get_activity_buckets(
        self,
        since: float,
        now: float,
        num_buckets: int = 12,
        source_tier: QuerySourceTier = "app",
    ) -> list[tuple[int, int]]:
        """Return bucketed ok/err counts for the sparkline chart.

        Divides the time window [since, now] into ``num_buckets`` equal buckets.
        Each bucket contains counts of successful (ok) and failed (err) invocations
        and executions combined.

        Args:
            since: Start of the time window (Unix epoch float).
            now: End of the time window (Unix epoch float).
            num_buckets: Number of equal-width buckets (default 12).
            source_tier: Filter by source tier.

        Returns:
            List of ``(ok, err)`` tuples, one per bucket, ordered chronologically (oldest first).
        """
        if now <= since or num_buckets <= 0:
            return [(0, 0)] * max(num_buckets, 0)

        bucket_width = (now - since) / num_buckets
        tier_hi_clause, tier_hi_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, _ = _source_tier_clause(source_tier, "je")

        query = f"""
            SELECT
                CAST((execution_start_ts - :since) / :bucket_width AS INTEGER) AS bucket_idx,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ok,
                SUM(CASE WHEN status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS err
            FROM (
                SELECT hi.execution_start_ts, hi.status
                FROM handler_invocations hi
                WHERE hi.execution_start_ts >= :since AND hi.execution_start_ts < :now
                    {tier_hi_clause}

                UNION ALL

                SELECT je.execution_start_ts, je.status
                FROM job_executions je
                WHERE je.execution_start_ts >= :since AND je.execution_start_ts < :now
                    {tier_je_clause}
            ) combined
            GROUP BY bucket_idx
            HAVING bucket_idx >= 0 AND bucket_idx < :num_buckets
        """

        params: dict[str, Any] = {
            "since": since,
            "now": now,
            "bucket_width": bucket_width,
            "num_buckets": num_buckets,
            **tier_hi_params,
        }

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        buckets: list[list[int]] = [[0, 0] for _ in range(num_buckets)]
        for row in rows:
            idx = int(row["bucket_idx"])
            if 0 <= idx < num_buckets:
                buckets[idx][0] = int(row["ok"] or 0)
                buckets[idx][1] = int(row["err"] or 0)

        return [(b[0], b[1]) for b in buckets]

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

    async def check_health(self) -> None:
        """Verify the database connection is alive.

        Raises on any database error; callers catch DB_ERRORS to derive degraded state.
        """
        async with self._db.execute("SELECT 1") as cursor:
            await cursor.fetchone()
