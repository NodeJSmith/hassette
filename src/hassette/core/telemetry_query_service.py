"""TelemetryQueryService: historical telemetry queries backed by DatabaseService."""

from typing import TYPE_CHECKING, Any

import aiosqlite

from hassette.core.telemetry_models import (
    AppHealthSummary,
    GlobalSummary,
    HandlerInvocation,
    JobExecution,
    JobGlobalStats,
    JobSummary,
    ListenerGlobalStats,
    ListenerSummary,
    SessionSummary,
)
from hassette.resources.base import Resource

if TYPE_CHECKING:
    from hassette import Hassette


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert an aiosqlite Row to a plain dict."""
    return dict(zip(row.keys(), tuple(row), strict=False))


class TelemetryQueryService(Resource):
    """Serves historical telemetry data from the SQLite database.

    All query methods execute real SQL against DatabaseService.db.
    Methods are async and must be awaited.
    """

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)

    @property
    def config_log_level(self) -> str:
        return self.hassette.config.web_api_log_level

    async def on_initialize(self) -> None:
        if not self.hassette.config.run_web_api:
            self.mark_ready(reason="Web API disabled")
            return
        await self.hassette.wait_for_ready([self.hassette.database_service])
        self.mark_ready(reason="TelemetryQueryService initialized")

    @property
    def _db(self) -> aiosqlite.Connection:
        """Return the active database connection from DatabaseService."""
        return self.hassette.database_service.db

    async def get_listener_summary(
        self,
        app_key: str,
        instance_index: int,
        session_id: int | None = None,
    ) -> list[ListenerSummary]:
        """Return per-listener summary for a specific app instance."""
        if session_id is not None:
            join_condition = "hi.listener_id = l.id AND hi.session_id = ?"
            last_err_filter = "AND session_id = ?"
            params: tuple = (session_id, session_id, app_key, instance_index)
        else:
            join_condition = "hi.listener_id = l.id"
            last_err_filter = ""
            params = (app_key, instance_index)

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
                COUNT(hi.rowid) AS total_invocations,
                SUM(CASE WHEN hi.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN hi.status = 'error' AND hi.error_type LIKE 'Dependency%'
                    THEN 1 ELSE 0 END) AS di_failures,
                SUM(CASE WHEN hi.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
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
                WHERE listener_id = l.id AND status = 'error' {last_err_filter}
                ORDER BY execution_start_ts DESC LIMIT 1
            )
            WHERE l.app_key = ? AND l.instance_index = ?
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
    ) -> list[JobSummary]:
        """Return per-job summary for a specific app instance."""
        if session_id is not None:
            join_condition = "je.job_id = sj.id AND je.session_id = ?"
            params: tuple = (session_id, app_key, instance_index)
        else:
            join_condition = "je.job_id = sj.id"
            params = (app_key, instance_index)

        query = f"""
            SELECT
                sj.id AS job_id,
                sj.app_key,
                sj.instance_index,
                sj.job_name,
                sj.handler_method,
                sj.trigger_type,
                sj.trigger_value,
                sj.repeat,
                sj.args_json,
                sj.kwargs_json,
                sj.source_location,
                sj.registration_source,
                COUNT(je.rowid) AS total_executions,
                SUM(CASE WHEN je.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS failed,
                MAX(je.execution_start_ts) AS last_executed_at,
                COALESCE(SUM(je.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms
            FROM scheduled_jobs sj
            LEFT JOIN job_executions je ON {join_condition}
            WHERE sj.app_key = ? AND sj.instance_index = ?
            GROUP BY sj.id
        """
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [JobSummary.model_validate(_row_to_dict(row)) for row in rows]

    async def get_all_app_summaries(self, session_id: int | None = None) -> dict[str, AppHealthSummary]:
        """Return per-app health summaries via 2 batch SQL queries (not 2N).

        Groups by ``app_key`` with ``instance_index = 0``.  Returns an empty
        dict when no listeners or jobs exist.
        """
        if session_id is not None:
            listener_query = """
                SELECT
                    l.app_key,
                    COUNT(DISTINCT l.id) AS handler_count,
                    COUNT(hi.rowid) AS total_invocations,
                    SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
                    COALESCE(AVG(hi.duration_ms), 0.0) AS avg_duration_ms,
                    MAX(hi.execution_start_ts) AS last_listener_activity_ts
                FROM listeners l
                LEFT JOIN handler_invocations hi ON hi.listener_id = l.id AND hi.session_id = ?
                WHERE l.instance_index = 0
                GROUP BY l.app_key
            """
            job_query = """
                SELECT
                    sj.app_key,
                    COUNT(DISTINCT sj.id) AS job_count,
                    COUNT(je.rowid) AS total_executions,
                    SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS total_job_errors,
                    MAX(je.execution_start_ts) AS last_job_activity_ts
                FROM scheduled_jobs sj
                LEFT JOIN job_executions je ON je.job_id = sj.id AND je.session_id = ?
                WHERE sj.instance_index = 0
                GROUP BY sj.app_key
            """
            listener_params: tuple[int, ...] = (session_id,)
            job_params: tuple[int, ...] = (session_id,)
        else:
            listener_query = """
                SELECT
                    l.app_key,
                    COUNT(DISTINCT l.id) AS handler_count,
                    COUNT(hi.rowid) AS total_invocations,
                    SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
                    COALESCE(AVG(hi.duration_ms), 0.0) AS avg_duration_ms,
                    MAX(hi.execution_start_ts) AS last_listener_activity_ts
                FROM listeners l
                LEFT JOIN handler_invocations hi ON hi.listener_id = l.id
                WHERE l.instance_index = 0
                GROUP BY l.app_key
            """
            job_query = """
                SELECT
                    sj.app_key,
                    COUNT(DISTINCT sj.id) AS job_count,
                    COUNT(je.rowid) AS total_executions,
                    SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS total_job_errors,
                    MAX(je.execution_start_ts) AS last_job_activity_ts
                FROM scheduled_jobs sj
                LEFT JOIN job_executions je ON je.job_id = sj.id
                WHERE sj.instance_index = 0
                GROUP BY sj.app_key
            """
            listener_params = ()
            job_params = ()

        async with self._db.execute(listener_query, listener_params) as cursor:
            listener_rows = await cursor.fetchall()
        async with self._db.execute(job_query, job_params) as cursor:
            job_rows = await cursor.fetchall()

        # Build per-app listener data
        listener_data: dict[str, dict[str, Any]] = {}
        for row in listener_rows:
            d = _row_to_dict(row)
            listener_data[d["app_key"]] = d

        # Build per-app job data
        job_data: dict[str, dict[str, Any]] = {}
        for row in job_rows:
            d = _row_to_dict(row)
            job_data[d["app_key"]] = d

        # Merge into AppHealthSummary per app_key
        all_keys = set(listener_data.keys()) | set(job_data.keys())
        result: dict[str, AppHealthSummary] = {}
        for app_key in all_keys:
            ld = listener_data.get(app_key, {})
            jd = job_data.get(app_key, {})
            last_listener_ts = ld.get("last_listener_activity_ts")
            last_job_ts = jd.get("last_job_activity_ts")
            last_times = [t for t in (last_listener_ts, last_job_ts) if t is not None]
            result[app_key] = AppHealthSummary(
                handler_count=ld.get("handler_count", 0),
                job_count=jd.get("job_count", 0),
                total_invocations=ld.get("total_invocations", 0),
                total_errors=ld.get("total_errors", 0),
                total_executions=jd.get("total_executions", 0),
                total_job_errors=jd.get("total_job_errors", 0),
                avg_duration_ms=ld.get("avg_duration_ms", 0.0),
                last_activity_ts=max(last_times) if last_times else None,
            )
        return result

    async def get_global_summary(self, session_id: int | None = None) -> GlobalSummary:
        """Return aggregate telemetry summary across all apps.

        Returns a zero-value ``GlobalSummary`` on fresh installs (no telemetry data).
        """
        if session_id is not None:
            listener_query = """
                SELECT
                    (SELECT COUNT(*) FROM listeners) AS total_listeners,
                    COUNT(DISTINCT hi.listener_id) AS invoked_listeners,
                    COUNT(hi.rowid) AS total_invocations,
                    SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
                    SUM(CASE WHEN hi.status = 'error' AND hi.error_type LIKE 'Dependency%'
                        THEN 1 ELSE 0 END) AS total_di_failures,
                    AVG(hi.duration_ms) AS avg_duration_ms
                FROM handler_invocations hi
                WHERE hi.session_id = ?
            """
            job_query = """
                SELECT
                    (SELECT COUNT(*) FROM scheduled_jobs) AS total_jobs,
                    COUNT(DISTINCT je.job_id) AS executed_jobs,
                    COUNT(je.rowid) AS total_executions,
                    SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
                    COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms
                FROM job_executions je
                WHERE je.session_id = ?
            """
            listener_params: tuple = (session_id,)
            job_params: tuple = (session_id,)
        else:
            listener_query = """
                SELECT
                    (SELECT COUNT(*) FROM listeners) AS total_listeners,
                    COUNT(DISTINCT hi.listener_id) AS invoked_listeners,
                    COUNT(hi.rowid) AS total_invocations,
                    SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
                    SUM(CASE WHEN hi.status = 'error' AND hi.error_type LIKE 'Dependency%'
                        THEN 1 ELSE 0 END) AS total_di_failures,
                    AVG(hi.duration_ms) AS avg_duration_ms
                FROM handler_invocations hi
            """
            job_query = """
                SELECT
                    (SELECT COUNT(*) FROM scheduled_jobs) AS total_jobs,
                    COUNT(DISTINCT je.job_id) AS executed_jobs,
                    COUNT(je.rowid) AS total_executions,
                    SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
                    COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms
                FROM job_executions je
            """
            listener_params = ()
            job_params = ()

        async with self._db.execute(listener_query, listener_params) as cursor:
            listener_row = await cursor.fetchone()
        async with self._db.execute(job_query, job_params) as cursor:
            job_row = await cursor.fetchone()

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
                je.error_type,
                je.error_message
            FROM job_executions je
            WHERE je.job_id = ? {session_clause}
            ORDER BY je.execution_start_ts DESC
            LIMIT ?
        """
        params = (job_id, session_id, limit) if session_id is not None else (job_id, limit)
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [JobExecution.model_validate(_row_to_dict(row)) for row in rows]

    async def get_recent_errors(
        self,
        since_ts: float,
        limit: int = 50,
        session_id: int | None = None,
    ) -> list[dict]:
        """Return recent error records since a given timestamp."""
        if session_id is not None:
            handler_query = """
                SELECT
                    hi.listener_id,
                    l.app_key,
                    l.handler_method,
                    l.topic,
                    hi.execution_start_ts,
                    hi.duration_ms,
                    hi.error_type,
                    hi.error_message
                FROM handler_invocations hi
                -- INNER JOIN: excludes invocations whose listener was deleted by clear_registrations()
                JOIN listeners l ON l.id = hi.listener_id
                WHERE hi.status = 'error'
                    AND hi.execution_start_ts > ?
                    AND hi.session_id = ?
                ORDER BY hi.execution_start_ts DESC
                LIMIT ?
            """
            job_query = """
                SELECT
                    je.job_id,
                    sj.app_key,
                    sj.job_name,
                    sj.handler_method,
                    je.execution_start_ts,
                    je.duration_ms,
                    je.error_type,
                    je.error_message
                FROM job_executions je
                -- INNER JOIN: excludes executions whose job was deleted by clear_registrations()
                JOIN scheduled_jobs sj ON sj.id = je.job_id
                WHERE je.status = 'error'
                    AND je.execution_start_ts > ?
                    AND je.session_id = ?
                ORDER BY je.execution_start_ts DESC
                LIMIT ?
            """
            handler_params: tuple = (since_ts, session_id, limit)
            job_params: tuple = (since_ts, session_id, limit)
        else:
            handler_query = """
                SELECT
                    hi.listener_id,
                    l.app_key,
                    l.handler_method,
                    l.topic,
                    hi.execution_start_ts,
                    hi.duration_ms,
                    hi.error_type,
                    hi.error_message
                FROM handler_invocations hi
                -- INNER JOIN: excludes invocations whose listener was deleted by clear_registrations()
                JOIN listeners l ON l.id = hi.listener_id
                WHERE hi.status = 'error'
                    AND hi.execution_start_ts > ?
                ORDER BY hi.execution_start_ts DESC
                LIMIT ?
            """
            job_query = """
                SELECT
                    je.job_id,
                    sj.app_key,
                    sj.job_name,
                    sj.handler_method,
                    je.execution_start_ts,
                    je.duration_ms,
                    je.error_type,
                    je.error_message
                FROM job_executions je
                -- INNER JOIN: excludes executions whose job was deleted by clear_registrations()
                JOIN scheduled_jobs sj ON sj.id = je.job_id
                WHERE je.status = 'error'
                    AND je.execution_start_ts > ?
                ORDER BY je.execution_start_ts DESC
                LIMIT ?
            """
            handler_params = (since_ts, limit)
            job_params = (since_ts, limit)

        async with self._db.execute(handler_query, handler_params) as cursor:
            handler_rows = await cursor.fetchall()
        async with self._db.execute(job_query, job_params) as cursor:
            job_rows = await cursor.fetchall()

        handler_errors = [dict(_row_to_dict(r), kind="handler") for r in handler_rows]
        job_errors = [dict(_row_to_dict(r), kind="job") for r in job_rows]
        merged = handler_errors + job_errors
        merged.sort(key=lambda e: e.get("execution_start_ts", 0), reverse=True)
        return merged[:limit]

    async def get_slow_handlers(self, threshold_ms: float, limit: int = 50) -> list[dict]:
        """Return handler invocations whose duration exceeds threshold_ms."""
        query = """
            SELECT
                l.app_key,
                l.handler_method,
                l.topic,
                hi.execution_start_ts,
                hi.duration_ms
            FROM handler_invocations hi
            -- INNER JOIN: excludes invocations whose listener was deleted by clear_registrations()
            JOIN listeners l ON l.id = hi.listener_id
            WHERE hi.duration_ms > ?
            ORDER BY hi.duration_ms DESC
            LIMIT ?
        """
        async with self._db.execute(query, (threshold_ms, limit)) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_dict(row) for row in rows]

    async def get_session_list(self, limit: int = 20) -> list[dict]:
        """Return recent session records."""
        query = """
            SELECT
                s.id,
                s.started_at,
                s.stopped_at,
                s.status,
                s.error_type,
                s.error_message,
                (COALESCE(s.stopped_at, s.last_heartbeat_at) - s.started_at) AS duration_seconds
            FROM sessions s
            ORDER BY s.started_at DESC
            LIMIT ?
        """
        async with self._db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_dict(row) for row in rows]

    async def get_current_session_summary(self) -> SessionSummary | None:
        """Return a summary of the current running session, or None if no session is running."""
        query = """
            SELECT
                s.started_at,
                s.last_heartbeat_at,
                (SELECT COUNT(*) FROM handler_invocations WHERE session_id = s.id) AS total_invocations,
                (SELECT COUNT(*) FROM handler_invocations
                    WHERE session_id = s.id AND status = 'error') AS invocation_errors,
                (SELECT COUNT(*) FROM job_executions WHERE session_id = s.id) AS total_executions,
                (SELECT COUNT(*) FROM job_executions WHERE session_id = s.id AND status = 'error') AS execution_errors
            FROM sessions s
            WHERE s.status = 'running'
        """
        async with self._db.execute(query) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return SessionSummary.model_validate(_row_to_dict(row))
