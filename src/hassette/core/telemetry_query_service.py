"""TelemetryQueryService: historical telemetry queries backed by DatabaseService."""

import contextlib
from typing import TYPE_CHECKING, Any, assert_never

import aiosqlite

from hassette.core.telemetry_models import (
    AppHealthSummary,
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


def _source_tier_clause(source_tier: QuerySourceTier, alias: str) -> tuple[str, list[str]]:
    """Return a (fragment, params) tuple for source_tier filtering.

    When ``source_tier`` is ``'all'``, returns ``("", [])`` (no filter).
    Otherwise returns a parameterised fragment and the value as a bind param.

    Args:
        source_tier: One of ``'app'``, ``'framework'``, or ``'all'``.
        alias: The SQL table alias to qualify the ``source_tier`` column.
    """
    # alias is an internal SQL table alias; no user data flows through this parameter
    match source_tier:
        case "all":
            return ("", [])
        case "app" | "framework":
            return (f"AND {alias}.source_tier = ?", [source_tier])
        case _ as unreachable:
            assert_never(unreachable)


class TelemetryQueryService(Resource):
    """Serves historical telemetry data from the SQLite database.

    All query methods execute real SQL against DatabaseService.db.
    Methods are async and must be awaited.
    """

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.web_api_log_level

    async def on_initialize(self) -> None:
        if not self.hassette.config.run_web_api:
            self.mark_ready(reason="Web API disabled")
            return
        await self.hassette.wait_for_ready([self.hassette.database_service])

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
        session_id: int | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[ListenerSummary]:
        """Return per-listener summary for a specific app instance.

        ``handler_count`` reflects instance 0 only while ``total_invocations``
        aggregates all instances.

        Args:
            app_key: The app key to filter by.
            instance_index: The app instance index to filter by.
            session_id: When provided, restrict invocation counts to this session.
            source_tier: Filter listeners by source tier. ``'app'`` (default) excludes
                framework internals. ``'all'`` includes all tiers.
        """
        tier_clause, tier_params = _source_tier_clause(source_tier, "l")

        if session_id is not None:
            join_condition = "hi.listener_id = l.id AND hi.session_id = ?"
            last_err_filter = "AND session_id = ?"
            params: list = [session_id, session_id, app_key, instance_index, *tier_params]
        else:
            join_condition = "hi.listener_id = l.id"
            last_err_filter = ""
            params = [app_key, instance_index, *tier_params]

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
                COALESCE(MIN(hi.duration_ms), 0.0) AS min_duration_ms,
                COALESCE(MAX(hi.duration_ms), 0.0) AS max_duration_ms,
                MAX(hi.execution_start_ts) AS last_invoked_at,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message
            FROM listeners l
            LEFT JOIN handler_invocations hi ON {join_condition}
            LEFT JOIN handler_invocations last_err ON last_err.id = (
                SELECT id FROM handler_invocations
                WHERE listener_id = l.id AND status IN ('error', 'timed_out') {last_err_filter}
                ORDER BY execution_start_ts DESC LIMIT 1
            )
            WHERE l.app_key = ? AND l.instance_index = ?
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
        session_id: int | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[JobSummary]:
        """Return per-job summary for a specific app instance.

        Args:
            app_key: The app key to filter by.
            instance_index: The app instance index to filter by.
            session_id: When provided, restrict execution counts to this session.
            source_tier: Filter jobs by source tier. ``'app'`` (default) excludes
                framework internals. ``'all'`` includes all tiers.
        """
        tier_clause, tier_params = _source_tier_clause(source_tier, "sj")

        if session_id is not None:
            join_condition = "je.job_id = sj.id AND je.session_id = ?"
            params: list = [session_id, app_key, instance_index, *tier_params]
        else:
            join_condition = "je.job_id = sj.id"
            params = [app_key, instance_index, *tier_params]

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
                CASE WHEN sj.cancelled_at IS NOT NULL THEN 1 ELSE 0 END AS cancelled,
                COUNT(je.rowid) AS total_executions,
                SUM(CASE WHEN je.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN je.status = 'timed_out' THEN 1 ELSE 0 END) AS timed_out,
                MAX(je.execution_start_ts) AS last_executed_at,
                COALESCE(SUM(je.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms
            FROM scheduled_jobs sj
            LEFT JOIN job_executions je ON {join_condition}
            WHERE sj.app_key = ? AND sj.instance_index = ?
            {tier_clause}
            GROUP BY sj.id
        """
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [JobSummary.model_validate(_row_to_dict(row)) for row in rows]

    async def get_all_app_summaries(
        self, session_id: int | None = None, source_tier: QuerySourceTier = "app"
    ) -> dict[str, AppHealthSummary]:
        """Return per-app health summaries via 4 batch SQL queries.

        Registration counts (handler_count, job_count) use the appropriate
        ``active_*`` views based on ``source_tier``.
        Registration counts reflect instance 0 only.

        Activity counts (invocations, errors, executions, duration averages) aggregate
        across all instances and filter by ``source_tier``.

        Args:
            session_id: When provided, restrict activity counts to this session.
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
        tier_l_clause, tier_l_params = _source_tier_clause(source_tier, "l")
        tier_sj_clause, tier_sj_params = _source_tier_clause(source_tier, "sj")

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
        if session_id is not None:
            listener_act_query = f"""
                SELECT
                    l.app_key,
                    COUNT(hi.rowid) AS total_invocations,
                    SUM(CASE WHEN hi.status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS total_errors,
                    COALESCE(AVG(hi.duration_ms), 0.0) AS avg_duration_ms,
                    MAX(hi.execution_start_ts) AS last_listener_activity_ts
                FROM listeners l
                LEFT JOIN handler_invocations hi ON hi.listener_id = l.id
                    AND hi.session_id = ?
                    {tier_clause}
                WHERE 1=1 {tier_l_clause}
                GROUP BY l.app_key
            """
            job_act_query = f"""
                SELECT
                    sj.app_key,
                    COUNT(je.rowid) AS total_executions,
                    SUM(CASE WHEN je.status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS total_job_errors,
                    MAX(je.execution_start_ts) AS last_job_activity_ts
                FROM scheduled_jobs sj
                LEFT JOIN job_executions je ON je.job_id = sj.id
                    AND je.session_id = ?
                    {tier_je_clause}
                WHERE 1=1 {tier_sj_clause}
                GROUP BY sj.app_key
            """
            listener_act_params: list[Any] = [session_id, *tier_params, *tier_l_params]
            job_act_params: list[Any] = [session_id, *tier_je_params, *tier_sj_params]
        else:
            listener_act_query = f"""
                SELECT
                    l.app_key,
                    COUNT(hi.rowid) AS total_invocations,
                    SUM(CASE WHEN hi.status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS total_errors,
                    COALESCE(AVG(hi.duration_ms), 0.0) AS avg_duration_ms,
                    MAX(hi.execution_start_ts) AS last_listener_activity_ts
                FROM listeners l
                LEFT JOIN handler_invocations hi ON hi.listener_id = l.id
                    {tier_clause}
                WHERE 1=1 {tier_l_clause}
                GROUP BY l.app_key
            """
            job_act_query = f"""
                SELECT
                    sj.app_key,
                    COUNT(je.rowid) AS total_executions,
                    SUM(CASE WHEN je.status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS total_job_errors,
                    MAX(je.execution_start_ts) AS last_job_activity_ts
                FROM scheduled_jobs sj
                LEFT JOIN job_executions je ON je.job_id = sj.id
                    {tier_je_clause}
                WHERE 1=1 {tier_sj_clause}
                GROUP BY sj.app_key
            """
            listener_act_params = [*tier_params, *tier_l_params]
            job_act_params = [*tier_je_params, *tier_sj_params]

        # BEGIN DEFERRED pins the WAL read mark on the read-only connection,
        # ensuring all four queries see a consistent snapshot. ROLLBACK releases it.
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

        # Build per-app data from each query
        listener_reg: dict[str, dict[str, Any]] = {}
        for row in listener_reg_rows:
            d = _row_to_dict(row)
            listener_reg[d["app_key"]] = d

        listener_act: dict[str, dict[str, Any]] = {}
        for row in listener_act_rows:
            d = _row_to_dict(row)
            listener_act[d["app_key"]] = d

        job_reg: dict[str, dict[str, Any]] = {}
        for row in job_reg_rows:
            d = _row_to_dict(row)
            job_reg[d["app_key"]] = d

        job_act: dict[str, dict[str, Any]] = {}
        for row in job_act_rows:
            d = _row_to_dict(row)
            job_act[d["app_key"]] = d

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
                total_executions=ja.get("total_executions", 0),
                total_job_errors=ja.get("total_job_errors", 0),
                avg_duration_ms=la.get("avg_duration_ms", 0.0),
                last_activity_ts=max(last_times) if last_times else None,
            )
        return result

    async def get_global_summary(
        self, session_id: int | None = None, source_tier: QuerySourceTier = "app"
    ) -> GlobalSummary:
        """Return aggregate telemetry summary across all apps.

        Args:
            session_id: When provided, restrict counts to this session.
            source_tier: Filter invocations/executions by source tier.
                ``'app'`` (default) counts only app-registered handlers/jobs.
                ``'all'`` counts everything including framework internals.

        Returns a zero-value ``GlobalSummary`` on fresh installs (no telemetry data).
        """
        tier_hi_clause, tier_hi_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, tier_je_params = _source_tier_clause(source_tier, "je")

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

        if session_id is not None:
            listener_query = f"""
                SELECT
                    {total_listeners_subq} AS total_listeners,
                    COUNT(DISTINCT hi.listener_id) AS invoked_listeners,
                    COUNT(hi.rowid) AS total_invocations,
                    SUM(CASE WHEN hi.status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS total_errors,
                    SUM(CASE WHEN hi.is_di_failure = 1 THEN 1 ELSE 0 END) AS total_di_failures,
                    AVG(hi.duration_ms) AS avg_duration_ms
                FROM handler_invocations hi
                WHERE hi.session_id = ? {tier_hi_clause}
            """
            job_query = f"""
                SELECT
                    {total_jobs_subq} AS total_jobs,
                    COUNT(DISTINCT je.job_id) AS executed_jobs,
                    COUNT(je.rowid) AS total_executions,
                    SUM(CASE WHEN je.status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS total_errors,
                    COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms
                FROM job_executions je
                WHERE je.session_id = ? {tier_je_clause}
            """
            listener_params: list = [session_id, *tier_hi_params]
            job_params: list = [session_id, *tier_je_params]
        else:
            listener_query = f"""
                SELECT
                    {total_listeners_subq} AS total_listeners,
                    COUNT(DISTINCT hi.listener_id) AS invoked_listeners,
                    COUNT(hi.rowid) AS total_invocations,
                    SUM(CASE WHEN hi.status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS total_errors,
                    SUM(CASE WHEN hi.is_di_failure = 1 THEN 1 ELSE 0 END) AS total_di_failures,
                    AVG(hi.duration_ms) AS avg_duration_ms
                FROM handler_invocations hi
                WHERE 1=1 {tier_hi_clause}
            """
            job_query = f"""
                SELECT
                    {total_jobs_subq} AS total_jobs,
                    COUNT(DISTINCT je.job_id) AS executed_jobs,
                    COUNT(je.rowid) AS total_executions,
                    SUM(CASE WHEN je.status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS total_errors,
                    COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms
                FROM job_executions je
                WHERE 1=1 {tier_je_clause}
            """
            listener_params = [*tier_hi_params]
            job_params = [*tier_je_params]

        # BEGIN DEFERRED pins the WAL read snapshot so both queries see consistent state.
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
                total_di_failures=listener_data.get("total_di_failures", 0) or 0,
                avg_duration_ms=listener_data.get("avg_duration_ms"),
            ),
            jobs=JobGlobalStats(
                total_jobs=job_data.get("total_jobs", 0),
                executed_jobs=job_data.get("executed_jobs", 0),
                total_executions=job_data.get("total_executions", 0),
                total_errors=job_data.get("total_errors", 0) or 0,
                avg_duration_ms=job_data.get("avg_duration_ms", 0.0) or 0.0,
            ),
        )

    async def get_handler_invocations(
        self, listener_id: int, limit: int = 50, session_id: int | None = None
    ) -> list[HandlerInvocation]:
        """Return recent invocation records for a specific listener."""
        session_clause = "AND hi.session_id = ?" if session_id is not None else ""
        query = f"""
            SELECT
                hi.execution_start_ts,
                hi.duration_ms,
                hi.status,
                hi.source_tier,
                hi.error_type,
                hi.error_message,
                hi.error_traceback
            FROM handler_invocations hi
            WHERE hi.listener_id = ? {session_clause}
            ORDER BY hi.execution_start_ts DESC
            LIMIT ?
        """
        params = (listener_id, session_id, limit) if session_id is not None else (listener_id, limit)
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [HandlerInvocation.model_validate(_row_to_dict(row)) for row in rows]

    async def get_job_executions(
        self, job_id: int, limit: int = 50, session_id: int | None = None
    ) -> list[JobExecution]:
        """Return recent execution records for a specific scheduled job."""
        session_clause = "AND je.session_id = ?" if session_id is not None else ""
        query = f"""
            SELECT
                je.execution_start_ts,
                je.duration_ms,
                je.status,
                je.source_tier,
                je.error_type,
                je.error_message,
                je.error_traceback
            FROM job_executions je
            WHERE je.job_id = ? {session_clause}
            ORDER BY je.execution_start_ts DESC
            LIMIT ?
        """
        params = (job_id, session_id, limit) if session_id is not None else (job_id, limit)
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [JobExecution.model_validate(_row_to_dict(row)) for row in rows]

    async def get_error_counts(
        self,
        since_ts: float,
        session_id: int | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> tuple[int, int]:
        """Return (handler_error_count, job_error_count) since a given timestamp.

        Uses COUNT(*) queries — no row materialization. Suitable for badge counts
        where exact numbers are needed without a LIMIT cap.
        """
        session_filter_hi = "AND hi.session_id = ?" if session_id is not None else ""
        session_filter_je = "AND je.session_id = ?" if session_id is not None else ""
        tier_hi_clause, tier_hi_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, tier_je_params = _source_tier_clause(source_tier, "je")

        handler_query = f"""
            SELECT COUNT(*) FROM handler_invocations hi
            WHERE hi.status IN ('error', 'timed_out') AND hi.execution_start_ts > ?
                {session_filter_hi} {tier_hi_clause}
        """
        job_query = f"""
            SELECT COUNT(*) FROM job_executions je
            WHERE je.status IN ('error', 'timed_out') AND je.execution_start_ts > ?
                {session_filter_je} {tier_je_clause}
        """

        hi_params: list = [since_ts]
        if session_id is not None:
            hi_params.append(session_id)
        hi_params.extend(tier_hi_params)

        je_params: list = [since_ts]
        if session_id is not None:
            je_params.append(session_id)
        je_params.extend(tier_je_params)

        async with self._db.execute(handler_query, hi_params) as cursor:
            handler_count = (await cursor.fetchone())[0]  # pyright: ignore[reportOptionalSubscript]
        async with self._db.execute(job_query, je_params) as cursor:
            job_count = (await cursor.fetchone())[0]  # pyright: ignore[reportOptionalSubscript]

        return handler_count, job_count

    async def get_recent_errors(
        self,
        since_ts: float,
        limit: int = 50,
        session_id: int | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[HandlerErrorRecord | JobErrorRecord]:
        """Return recent error records since a given timestamp.

        Uses a single UNION ALL query with LEFT JOINs so that orphaned records
        (whose listener/job was deleted) are still returned with null FK fields.
        A single ORDER BY + LIMIT applies globally across both record types.

        Args:
            since_ts: Only return records with ``execution_start_ts > since_ts``.
            limit: Maximum number of records to return (applied globally).
            session_id: When provided, restrict to this session only.
            source_tier: Filter by ``source_tier`` column on the invocation/execution
                table. ``'app'`` (default) excludes framework internals.
                ``'all'`` disables the filter entirely.
        """
        session_filter_hi = "AND hi.session_id = ?" if session_id is not None else ""
        session_filter_je = "AND je.session_id = ?" if session_id is not None else ""

        # Build source_tier fragments (parameterised — no string interpolation of values)
        tier_hi_clause, tier_hi_params = _source_tier_clause(source_tier, "hi")
        tier_je_clause, tier_je_params = _source_tier_clause(source_tier, "je")

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
                hi.error_traceback
            FROM handler_invocations hi
            LEFT JOIN listeners l ON l.id = hi.listener_id
            WHERE hi.status IN ('error', 'timed_out')
                AND hi.execution_start_ts > ?
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
                je.error_traceback
            FROM job_executions je
            LEFT JOIN scheduled_jobs sj ON sj.id = je.job_id
            WHERE je.status IN ('error', 'timed_out')
                AND je.execution_start_ts > ?
                {session_filter_je}
                {tier_je_clause}

            ORDER BY execution_start_ts DESC
            LIMIT ?
        """

        # Build params: handler side, then job side, then limit
        if session_id is not None:
            params: list = [since_ts, session_id, *tier_hi_params, since_ts, session_id, *tier_je_params, limit]
        else:
            params = [since_ts, *tier_hi_params, since_ts, *tier_je_params, limit]

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        result: list[HandlerErrorRecord | JobErrorRecord] = []
        for row in rows:
            d = _row_to_dict(row)
            if d["kind"] == "handler":
                result.append(
                    HandlerErrorRecord(
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
                    )
                )
            else:
                result.append(
                    JobErrorRecord(
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
                    )
                )
        return result

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
            WHERE hi.duration_ms > ?
                {tier_clause}
            ORDER BY hi.duration_ms DESC
            LIMIT ?
        """
        async with self._db.execute(query, [threshold_ms, *tier_params, limit]) as cursor:
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
            LIMIT ?
        """
        async with self._db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
        return [SessionRecord.model_validate(_row_to_dict(row)) for row in rows]

    async def check_health(self) -> None:
        """Verify the database connection is alive.

        Raises on any database error; callers catch DB_ERRORS to derive degraded state.
        """
        async with self._db.execute("SELECT 1") as cursor:
            await cursor.fetchone()
