"""Registration-level telemetry query methods: listener and job summaries, slow handlers."""

from typing import TYPE_CHECKING, Any

from hassette.core.telemetry.helpers import DEFAULT_QUERY_LIMIT, _row_to_dict, _since_clause, _source_tier_clause
from hassette.core.telemetry_models import JobSummary, ListenerSummary, SlowHandlerRecord
from hassette.types.types import QuerySourceTier

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    import aiosqlite


class RegistrationQueriesMixin:
    """Listener/job registration-summary query methods, mixed into TelemetryQueryService."""

    if TYPE_CHECKING:
        # Provided by TelemetryQueryService; declared for type narrowing within the mixin.
        execute: "Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]]"

    async def get_listener_summary(
        self,
        app_key: str,
        instance_index: int,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[ListenerSummary]:
        """Return per-listener summary for a specific app instance.

        Args:
            app_key: The app key to filter by.
            instance_index: The app instance index to filter by.
            since: When provided, restrict invocation counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter listeners by source tier.
        """
        tier_clause, tier_params = _source_tier_clause(source_tier, "l")
        since_join_clause, since_params = _since_clause(since, "e.execution_start_ts")
        since_err_clause, _ = _since_clause(since, "e_err.execution_start_ts")

        join_condition = f"e.listener_id = l.id {since_join_clause}"
        params: dict[str, Any] = {"app_key": app_key, "instance_index": instance_index, **tier_params, **since_params}

        query = f"""
            WITH ranked_errors AS (
                SELECT e_err.listener_id, e_err.error_type, e_err.error_message,
                       e_err.error_traceback, e_err.execution_start_ts,
                       ROW_NUMBER() OVER (PARTITION BY e_err.listener_id ORDER BY e_err.execution_start_ts DESC) AS rn
                FROM executions e_err
                WHERE e_err.kind = 'handler'
                  AND e_err.status IN ('error', 'timed_out') {since_err_clause}
            )
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
                l.mode,
                l.backpressure,
                COUNT(e.rowid) AS total_invocations,
                SUM(CASE WHEN e.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN e.status = 'error' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN e.is_di_failure = 1 THEN 1 ELSE 0 END) AS di_failures,
                SUM(CASE WHEN e.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                SUM(CASE WHEN e.status = 'timed_out' THEN 1 ELSE 0 END) AS timed_out,
                SUM(CASE WHEN e.thread_leaked = 1 THEN 1 ELSE 0 END) AS thread_leaked,
                COALESCE(SUM(e.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(e.duration_ms), 0.0) AS avg_duration_ms,
                MIN(e.duration_ms) AS min_duration_ms,
                MAX(e.duration_ms) AS max_duration_ms,
                MAX(e.execution_start_ts) AS last_invoked_at,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message,
                last_err.error_traceback AS last_error_traceback
            FROM listeners l
            LEFT JOIN executions e ON {join_condition} AND e.kind = 'handler'
            LEFT JOIN ranked_errors last_err ON last_err.listener_id = l.id AND last_err.rn = 1
            WHERE l.app_key = :app_key AND l.instance_index = :instance_index
            AND l.cancelled_at IS NULL
            {tier_clause}
            GROUP BY l.id
        """
        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [ListenerSummary.model_validate(_row_to_dict(row)) for row in rows]

    async def get_all_listeners_summary(
        self,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[ListenerSummary]:
        """Return per-listener summaries across all apps, with no app_key filter."""
        tier_clause, tier_params = _source_tier_clause(source_tier, "l")
        since_join_clause, since_params = _since_clause(since, "e.execution_start_ts")
        since_err_clause, _ = _since_clause(since, "e_err.execution_start_ts")

        join_condition = f"e.listener_id = l.id {since_join_clause}"
        params: dict[str, Any] = {**tier_params, **since_params}

        query = f"""
            WITH ranked_errors AS (
                SELECT e_err.listener_id, e_err.error_type, e_err.error_message,
                       e_err.error_traceback, e_err.execution_start_ts,
                       ROW_NUMBER() OVER (PARTITION BY e_err.listener_id ORDER BY e_err.execution_start_ts DESC) AS rn
                FROM executions e_err
                WHERE e_err.kind = 'handler'
                  AND e_err.status IN ('error', 'timed_out') {since_err_clause}
            )
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
                l.mode,
                l.backpressure,
                COUNT(e.rowid) AS total_invocations,
                SUM(CASE WHEN e.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN e.status = 'error' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN e.is_di_failure = 1 THEN 1 ELSE 0 END) AS di_failures,
                SUM(CASE WHEN e.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                SUM(CASE WHEN e.status = 'timed_out' THEN 1 ELSE 0 END) AS timed_out,
                SUM(CASE WHEN e.thread_leaked = 1 THEN 1 ELSE 0 END) AS thread_leaked,
                COALESCE(SUM(e.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(e.duration_ms), 0.0) AS avg_duration_ms,
                MIN(e.duration_ms) AS min_duration_ms,
                MAX(e.duration_ms) AS max_duration_ms,
                MAX(e.execution_start_ts) AS last_invoked_at,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message,
                last_err.error_traceback AS last_error_traceback
            FROM listeners l
            LEFT JOIN executions e ON {join_condition} AND e.kind = 'handler'
            LEFT JOIN ranked_errors last_err ON last_err.listener_id = l.id AND last_err.rn = 1
            WHERE 1=1
            AND l.cancelled_at IS NULL
            {tier_clause}
            GROUP BY l.id
        """
        async with self.execute(query, params) as cursor:
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
            source_tier: Filter jobs by source tier.
        """
        tier_clause, tier_params = _source_tier_clause(source_tier, "sj")
        since_join_clause, since_params = _since_clause(since, "e.execution_start_ts")
        since_err_clause, _ = _since_clause(since, "e_err.execution_start_ts")

        join_condition = f"e.job_id = sj.id {since_join_clause}"
        params: dict[str, Any] = {"app_key": app_key, "instance_index": instance_index, **tier_params, **since_params}

        query = f"""
            WITH ranked_errors AS (
                SELECT e_err.job_id, e_err.error_type, e_err.error_message,
                       e_err.error_traceback, e_err.execution_start_ts,
                       ROW_NUMBER() OVER (PARTITION BY e_err.job_id ORDER BY e_err.execution_start_ts DESC) AS rn
                FROM executions e_err
                WHERE e_err.kind = 'job'
                  AND e_err.status IN ('error', 'timed_out') {since_err_clause}
            )
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
                sj.mode,
                COUNT(e.rowid) AS total_executions,
                SUM(CASE WHEN e.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN e.status = 'error' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN e.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                SUM(CASE WHEN e.status = 'timed_out' THEN 1 ELSE 0 END) AS timed_out,
                SUM(CASE WHEN e.thread_leaked = 1 THEN 1 ELSE 0 END) AS thread_leaked,
                MAX(e.execution_start_ts) AS last_executed_at,
                COALESCE(SUM(e.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(e.duration_ms), 0.0) AS avg_duration_ms,
                MIN(e.duration_ms) AS min_duration_ms,
                MAX(e.duration_ms) AS max_duration_ms,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message,
                last_err.execution_start_ts AS last_error_ts,
                last_err.error_traceback AS last_error_traceback
            FROM scheduled_jobs sj
            LEFT JOIN executions e ON {join_condition} AND e.kind = 'job'
            LEFT JOIN ranked_errors last_err ON last_err.job_id = sj.id AND last_err.rn = 1
            WHERE sj.app_key = :app_key AND sj.instance_index = :instance_index
            AND sj.cancelled_at IS NULL
            {tier_clause}
            GROUP BY sj.id
        """
        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [JobSummary.model_validate(_row_to_dict(row)) for row in rows]

    async def get_all_jobs_summary(
        self,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> list[JobSummary]:
        """Return per-job summaries across all apps, with no app_key filter."""
        tier_clause, tier_params = _source_tier_clause(source_tier, "sj")
        since_join_clause, since_params = _since_clause(since, "e.execution_start_ts")
        since_err_clause, _ = _since_clause(since, "e_err.execution_start_ts")

        join_condition = f"e.job_id = sj.id {since_join_clause}"
        params: dict[str, Any] = {**tier_params, **since_params}

        query = f"""
            WITH ranked_errors AS (
                SELECT e_err.job_id, e_err.error_type, e_err.error_message,
                       e_err.error_traceback, e_err.execution_start_ts,
                       ROW_NUMBER() OVER (PARTITION BY e_err.job_id ORDER BY e_err.execution_start_ts DESC) AS rn
                FROM executions e_err
                WHERE e_err.kind = 'job'
                  AND e_err.status IN ('error', 'timed_out') {since_err_clause}
            )
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
                sj.mode,
                COUNT(e.rowid) AS total_executions,
                SUM(CASE WHEN e.status = 'success' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN e.status = 'error' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN e.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                SUM(CASE WHEN e.status = 'timed_out' THEN 1 ELSE 0 END) AS timed_out,
                SUM(CASE WHEN e.thread_leaked = 1 THEN 1 ELSE 0 END) AS thread_leaked,
                MAX(e.execution_start_ts) AS last_executed_at,
                COALESCE(SUM(e.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(e.duration_ms), 0.0) AS avg_duration_ms,
                MIN(e.duration_ms) AS min_duration_ms,
                MAX(e.duration_ms) AS max_duration_ms,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message,
                last_err.execution_start_ts AS last_error_ts,
                last_err.error_traceback AS last_error_traceback
            FROM scheduled_jobs sj
            LEFT JOIN executions e ON {join_condition} AND e.kind = 'job'
            LEFT JOIN ranked_errors last_err ON last_err.job_id = sj.id AND last_err.rn = 1
            WHERE sj.cancelled_at IS NULL
            {tier_clause}
            GROUP BY sj.id
        """
        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [JobSummary.model_validate(_row_to_dict(row)) for row in rows]

    async def get_slow_handlers(
        self,
        threshold_ms: float,
        limit: int = DEFAULT_QUERY_LIMIT,
        source_tier: QuerySourceTier = "app",
    ) -> list[SlowHandlerRecord]:
        """Return handler executions whose duration exceeds threshold_ms.

        Uses LEFT JOIN so that orphaned executions (whose listener was deleted)
        still appear in results with null ``app_key``.

        Args:
            threshold_ms: Only return executions slower than this value.
            limit: Maximum number of records to return.
            source_tier: Filter by ``source_tier`` on executions.
        """
        tier_clause, tier_params = _source_tier_clause(source_tier, "e")
        query = f"""
            SELECT
                l.app_key,
                l.handler_method,
                l.topic,
                e.execution_start_ts,
                e.duration_ms,
                e.source_tier
            FROM executions e
            LEFT JOIN listeners l ON l.id = e.listener_id
            WHERE e.kind = 'handler'
              AND e.duration_ms > :threshold_ms
              {tier_clause}
            ORDER BY e.duration_ms DESC
            LIMIT :limit
        """
        async with self.execute(query, {"threshold_ms": threshold_ms, "limit": limit, **tier_params}) as cursor:
            rows = await cursor.fetchall()
        return [SlowHandlerRecord.model_validate(_row_to_dict(row)) for row in rows]
