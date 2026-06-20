"""App-level summary and session query methods."""

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, assert_never

from hassette.core.telemetry.helpers import (
    DEFAULT_EXECUTION_LOG_LIMIT,
    DEFAULT_LOG_RECORDS_LIMIT,
    DEFAULT_SESSION_LIST_LIMIT,
    AppHealthAggregates,
    _build_app_summaries,
    _row_to_dict,
    _since_clause,
    _source_tier_clause,
)
from hassette.schemas.telemetry_models import AppHealthSummary, SessionRecord
from hassette.types.types import QuerySourceTier

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    import aiosqlite

    from hassette import Hassette


class SummaryQueriesMixin:
    """App-health, session, and log summary query methods, mixed into TelemetryQueryService."""

    if TYPE_CHECKING:
        # Provided by TelemetryQueryService; declared for type narrowing within the mixin.
        # This mixin reaches _db / _snapshot_lock directly (for the batched BEGIN DEFERRED read
        # in get_all_app_summaries); the sibling mixins only need execute().
        hassette: "Hassette"
        _db: "aiosqlite.Connection"
        _snapshot_lock: "asyncio.Lock"
        execute: "Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]]"

    async def get_app_health_aggregates(
        self,
        app_key: str,
        instance_index: int,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> AppHealthAggregates:
        """Return a single-row aggregate of handler and job health metrics for one app instance.

        Uses a single query against ``executions`` with two CTE arms (handler_agg, job_agg).
        SQLite does not support ``FILTER``; uses ``SUM(CASE WHEN kind='handler' ...)`` instead.

        Args:
            app_key: The app key to filter by.
            instance_index: The app instance index to filter by.
            since: When provided, restrict counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter by source tier.
        """
        tier_e_clause, tier_params = _source_tier_clause(source_tier, "e")
        since_clause, since_params = _since_clause(since, "e.execution_start_ts")

        params: dict[str, Any] = {
            "app_key": app_key,
            "instance_index": instance_index,
            **tier_params,
            **since_params,
        }

        # SQLite has no FILTER clause; use SUM(CASE WHEN kind='handler' THEN 1 ELSE 0 END) pattern.
        query = f"""
            WITH agg AS (
                SELECT
                    SUM(CASE WHEN e.kind = 'handler' THEN 1 ELSE 0 END) AS total_invocations,
                    SUM(CASE WHEN e.kind = 'handler' AND e.status = 'error' THEN 1 ELSE 0 END) AS handler_errors,
                    SUM(CASE WHEN e.kind = 'handler' AND e.status = 'timed_out' THEN 1 ELSE 0 END) AS handler_timed_out,
                    AVG(CASE WHEN e.kind = 'handler' THEN e.duration_ms END) AS handler_avg_duration_ms,
                    SUM(CASE WHEN e.kind = 'job' THEN 1 ELSE 0 END) AS total_executions,
                    SUM(CASE WHEN e.kind = 'job' AND e.status = 'error' THEN 1 ELSE 0 END) AS job_errors,
                    SUM(CASE WHEN e.kind = 'job' AND e.status = 'timed_out' THEN 1 ELSE 0 END) AS job_timed_out,
                    AVG(CASE WHEN e.kind = 'job' THEN e.duration_ms END) AS job_avg_duration_ms,
                    MAX(e.execution_start_ts) AS last_activity
                FROM executions e
                LEFT JOIN listeners l ON l.id = e.listener_id AND e.kind = 'handler'
                LEFT JOIN scheduled_jobs sj ON sj.id = e.job_id AND e.kind = 'job'
                WHERE (
                    (e.kind = 'handler' AND l.app_key = :app_key AND l.instance_index = :instance_index
                     AND l.cancelled_at IS NULL)
                    OR
                    (e.kind = 'job' AND sj.app_key = :app_key AND sj.instance_index = :instance_index
                     AND sj.cancelled_at IS NULL)
                )
                {tier_e_clause}
                {since_clause}
            )
            SELECT * FROM agg
        """
        async with self.execute(query, params) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return AppHealthAggregates(
                total_invocations=0,
                handler_errors=0,
                handler_timed_out=0,
                handler_avg_duration_ms=0.0,
                total_executions=0,
                job_errors=0,
                job_timed_out=0,
                job_avg_duration_ms=0.0,
                last_activity_ts=None,
            )

        d = _row_to_dict(row)
        return AppHealthAggregates(
            total_invocations=d["total_invocations"] or 0,
            handler_errors=d["handler_errors"] or 0,
            handler_timed_out=d["handler_timed_out"] or 0,
            handler_avg_duration_ms=d["handler_avg_duration_ms"] or 0.0,
            total_executions=d["total_executions"] or 0,
            job_errors=d["job_errors"] or 0,
            job_timed_out=d["job_timed_out"] or 0,
            job_avg_duration_ms=d["job_avg_duration_ms"] or 0.0,
            last_activity_ts=d["last_activity"] if d.get("last_activity") is not None else None,
        )

    async def get_all_app_summaries(
        self,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, AppHealthSummary]:
        """Return per-app health summaries via 4 batch SQL queries against executions.

        Registration counts (handler_count, job_count) still use ``active_*`` views.
        Activity counts query the unified ``executions`` table.

        Args:
            since: When provided, restrict activity counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter by source tier.
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

        # Each call binds the same param keys (:source_tier / :since) regardless of alias,
        # so only the first params dict is kept; the rest are discarded as _.
        tier_e_handler_clause, tier_params = _source_tier_clause(source_tier, "e_h")
        tier_e_job_clause, _ = _source_tier_clause(source_tier, "e_j")
        tier_l_clause, _ = _source_tier_clause(source_tier, "l")
        tier_sj_clause, _ = _source_tier_clause(source_tier, "sj")
        since_h_clause, since_params = _since_clause(since, "e_h.execution_start_ts")
        since_j_clause, _ = _since_clause(since, "e_j.execution_start_ts")

        # Count distinct handler/job identities across all instances, not listener rows.
        # Each instance of a multi-instance app registers its own rows under the same
        # (name, topic)/job_name identity, so COUNT(DISTINCT id) would multiply the count
        # by instance_count. The two natural-key parts are concatenated into one distinct
        # key joined by char(31) — the ASCII unit separator, chosen because it cannot occur
        # in an entity name or topic, so it can never collide with the parts it separates.
        listener_reg_query = f"""
            SELECT l.app_key, COUNT(DISTINCT l.name || char(31) || l.topic) AS handler_count
            FROM {listener_view} l
            GROUP BY l.app_key
        """
        job_reg_query = f"""
            SELECT sj.app_key, COUNT(DISTINCT sj.job_name) AS job_count
            FROM {job_view} sj
            GROUP BY sj.app_key
        """

        listener_act_query = f"""
            SELECT
                l.app_key,
                COUNT(e_h.rowid) AS total_invocations,
                SUM(CASE WHEN e_h.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
                SUM(CASE WHEN e_h.status = 'timed_out' THEN 1 ELSE 0 END) AS total_timed_out,
                COALESCE(AVG(e_h.duration_ms), 0.0) AS avg_duration_ms,
                MAX(e_h.execution_start_ts) AS last_listener_activity_ts
            FROM listeners l
            LEFT JOIN executions e_h ON e_h.listener_id = l.id AND e_h.kind = 'handler'
                {tier_e_handler_clause}
                {since_h_clause}
            WHERE 1=1 {tier_l_clause}
            GROUP BY l.app_key
        """
        job_act_query = f"""
            SELECT
                sj.app_key,
                COUNT(e_j.rowid) AS total_executions,
                SUM(CASE WHEN e_j.status = 'error' THEN 1 ELSE 0 END) AS total_job_errors,
                SUM(CASE WHEN e_j.status = 'timed_out' THEN 1 ELSE 0 END) AS total_job_timed_out,
                MAX(e_j.execution_start_ts) AS last_job_activity_ts
            FROM scheduled_jobs sj
            LEFT JOIN executions e_j ON e_j.job_id = sj.id AND e_j.kind = 'job'
                {tier_e_job_clause}
                {since_j_clause}
            WHERE 1=1 {tier_sj_clause}
            GROUP BY sj.app_key
        """
        listener_act_params: dict[str, Any] = {**tier_params, **since_params}
        job_act_params: dict[str, Any] = {**tier_params, **since_params}

        async with asyncio.timeout(self.hassette.config.database.read_timeout_seconds), self._snapshot_lock:
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
                # Always discard the read snapshot. Suppress broadly so a ROLLBACK failure
                # (e.g. no transaction is open) can never mask an exception from the queries.
                with contextlib.suppress(Exception):
                    await self._db.execute("ROLLBACK")

        return _build_app_summaries(
            listener_reg_rows=listener_reg_rows,
            listener_act_rows=listener_act_rows,
            job_reg_rows=job_reg_rows,
            job_act_rows=job_act_rows,
            source_tier=source_tier,
        )

    async def get_session_list(self, limit: int = DEFAULT_SESSION_LIST_LIMIT) -> list[SessionRecord]:
        """Return recent session records.

        Session identity is intentionally not exposed in the API — time-based filtering is
        the only user-facing grain. ``SessionRecord.id`` carries the integer row id but is
        not forwarded to any API-facing response model.
        """
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
                s.dropped_shutdown
            FROM sessions s
            ORDER BY s.started_at DESC
            LIMIT :limit
        """
        async with self.execute(query, {"limit": limit}) as cursor:
            rows = await cursor.fetchall()
        return [SessionRecord.model_validate(_row_to_dict(row)) for row in rows]

    async def get_log_records(
        self,
        *,
        limit: int = DEFAULT_LOG_RECORDS_LIMIT,
        since: float | None = None,
        app_key: str | None = None,
        level: str | None = None,
        execution_id: str | None = None,
        source_tier: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch log records with optional filters, ordered by timestamp DESC.

        ``session_id`` is intentionally not included in the SELECT — session identity is
        not exposed in the API. All other log_records columns are returned as-is.
        """
        clauses: list[str] = []
        params: dict[str, Any] = {}

        if since is not None:
            clauses.append("timestamp >= :since")
            params["since"] = since
        if app_key is not None:
            clauses.append("app_key = :app_key")
            params["app_key"] = app_key
        if level is not None:
            clauses.append("level = :level")
            params["level"] = level
        if execution_id is not None:
            clauses.append("execution_id = :execution_id")
            params["execution_id"] = execution_id
        if source_tier is not None:
            clauses.append("source_tier = :source_tier")
            params["source_tier"] = source_tier

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params["limit"] = limit

        query = f"SELECT * FROM log_records{where} ORDER BY timestamp DESC, seq DESC LIMIT :limit"
        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_dict(row) for row in rows]

    async def get_log_records_by_execution(
        self,
        execution_id: str,
        *,
        limit: int = DEFAULT_EXECUTION_LOG_LIMIT,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch all log records for a single execution, ordered by seq ASC."""
        query = "SELECT * FROM log_records WHERE execution_id = :execution_id ORDER BY seq ASC LIMIT :limit"
        async with self.execute(query, {"execution_id": execution_id, "limit": limit + 1}) as cursor:
            rows = list(await cursor.fetchall())
        truncated = len(rows) > limit
        return [_row_to_dict(row) for row in rows[:limit]], truncated
