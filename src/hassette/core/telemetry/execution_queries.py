"""Execution-level telemetry query methods against the unified executions table."""

import time
from typing import TYPE_CHECKING, Any

from hassette.const.misc import SECONDS_PER_HOUR
from hassette.core.telemetry.helpers import (
    DEFAULT_QUERY_LIMIT,
    DEFAULT_SPARKLINE_BUCKETS,
    _row_to_dict,
    _since_clause,
    _source_tier_clause,
)
from hassette.core.telemetry_models import ActivityFeedEntry, AppLastError, Execution
from hassette.types.types import QuerySourceTier

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    import aiosqlite


class ExecutionQueriesMixin:
    """Execution-table query methods, mixed into TelemetryQueryService."""

    if TYPE_CHECKING:
        # Provided by TelemetryQueryService; declared for type narrowing within the mixin.
        execute: "Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]]"

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

        Exactly one of ``listener_id``, ``job_id``, or ``kind`` should be supplied to
        narrow the query. Supplying none returns all executions up to ``limit``.

        Args:
            listener_id: When provided, restrict to handler executions for this listener.
            job_id: When provided, restrict to job executions for this job.
            kind: When provided, restrict to ``'handler'`` or ``'job'`` executions.
            limit: Maximum number of records to return.
            since: When provided, restrict to records with ``execution_start_ts >= since``.
        """
        since_clause, since_params = _since_clause(since, "e.execution_start_ts")
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit, **since_params}

        if listener_id is not None:
            clauses.append("e.listener_id = :listener_id")
            params["listener_id"] = listener_id
        if job_id is not None:
            clauses.append("e.job_id = :job_id")
            params["job_id"] = job_id
        if kind is not None:
            clauses.append("e.kind = :kind")
            params["kind"] = kind

        where = " AND ".join(clauses) if clauses else "1=1"
        query = f"""
            SELECT
                e.kind,
                e.listener_id,
                e.job_id,
                e.execution_start_ts,
                e.duration_ms,
                e.status,
                e.source_tier,
                e.error_type,
                e.error_message,
                e.error_traceback,
                e.execution_id,
                e.trigger_context_id,
                e.trigger_origin,
                e.trigger_mode,
                e.retry_count,
                e.attempt_number,
                e.args_json,
                e.kwargs_json,
                e.thread_leaked
            FROM executions e
            WHERE {where} {since_clause}
            ORDER BY e.execution_start_ts DESC
            LIMIT :limit
        """
        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [Execution.model_validate(_row_to_dict(row)) for row in rows]

    async def get_app_recent_activity(
        self,
        app_key: str,
        instance_index: int | None,
        limit: int,
        since: float | None,
        source_tier: QuerySourceTier,
    ) -> list[ActivityFeedEntry]:
        """Return recent handler invocations and job executions for a single app, merged by time.

        Uses a single query against ``executions`` joined through ``listeners`` /
        ``scheduled_jobs`` to resolve ``app_key``.  The ``since`` parameter bounds the
        scan; UNION ALL merges the two kinds into one sorted result.

        Args:
            app_key: The app to query.
            instance_index: When provided, restrict to that instance only.
            limit: Maximum number of entries to return (1-500).
            since: Unix epoch float lower bound for ``execution_start_ts``, or ``None``.
            source_tier: Filter by source tier.

        Returns:
            List of :class:`ActivityFeedEntry` sorted by ``timestamp`` descending.
        """
        # The query is a UNION ALL of two arms: the handler arm (executions aliased `e_h`,
        # suffix `_hi`) and the job arm (executions aliased `e_j`, suffix `_je`). Each clause
        # builder embeds the alias in its fragment but always binds the same parameter name
        # (`:source_tier`, `:since`), so both arms share one bind value — the second call's
        # params dict is a duplicate and is intentionally discarded.
        tier_hi_clause, tier_params = _source_tier_clause(source_tier, "e_h")
        tier_je_clause, _ = _source_tier_clause(source_tier, "e_j")
        since_hi_clause, since_params = _since_clause(since, "e_h.execution_start_ts")
        since_je_clause, _ = _since_clause(since, "e_j.execution_start_ts")

        instance_hi_clause = ""
        instance_je_clause = ""
        instance_params: dict[str, int] = {}
        if instance_index is not None:
            instance_hi_clause = "AND l.instance_index = :instance_index"
            instance_je_clause = "AND sj.instance_index = :instance_index"
            instance_params = {"instance_index": instance_index}

        # row_id carries the execution_id UUID, falling back to 'h-'/'j-' + rowid for older rows.
        query = f"""
            SELECT row_id, status, timestamp, app_key, handler_name, duration_ms, error_type, kind
            FROM (
                SELECT
                    COALESCE(e_h.execution_id, 'h-' || CAST(e_h.rowid AS TEXT)) AS row_id,
                    e_h.status,
                    e_h.execution_start_ts AS timestamp,
                    l.app_key,
                    l.handler_method AS handler_name,
                    e_h.duration_ms,
                    e_h.error_type,
                    'handler' AS kind
                FROM executions e_h
                JOIN listeners l ON l.id = e_h.listener_id
                WHERE e_h.kind = 'handler'
                  AND l.app_key = :app_key
                  {instance_hi_clause}
                  {since_hi_clause}
                  {tier_hi_clause}

                UNION ALL

                SELECT
                    COALESCE(e_j.execution_id, 'j-' || CAST(e_j.rowid AS TEXT)) AS row_id,
                    e_j.status,
                    e_j.execution_start_ts AS timestamp,
                    sj.app_key,
                    sj.handler_method AS handler_name,
                    e_j.duration_ms,
                    e_j.error_type,
                    'job' AS kind
                FROM executions e_j
                JOIN scheduled_jobs sj ON sj.id = e_j.job_id
                WHERE e_j.kind = 'job'
                  AND sj.app_key = :app_key
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

        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [ActivityFeedEntry.model_validate(_row_to_dict(row)) for row in rows]

    async def get_per_app_activity_buckets(
        self,
        since: float,
        now: float,
        num_buckets: int = DEFAULT_SPARKLINE_BUCKETS,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, list[tuple[int, int]]]:
        """Return bucketed ok/err counts per app_key for sparkline charts.

        Queries the unified ``executions`` table and joins through
        ``listeners``/``scheduled_jobs`` to resolve ``app_key``.

        Returns:
            Dict mapping app_key to a list of ``(ok, err)`` tuples per bucket.
        """
        if now <= since or num_buckets <= 0:
            return {}

        bucket_width = (now - since) / num_buckets
        tier_hi_clause, tier_params = _source_tier_clause(source_tier, "e_h")
        tier_je_clause, _ = _source_tier_clause(source_tier, "e_j")

        query = f"""
            SELECT app_key, bucket_idx,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ok,
                SUM(CASE WHEN status IN ('error', 'timed_out') THEN 1 ELSE 0 END) AS err
            FROM (
                SELECT l.app_key, e_h.status,
                    CAST((e_h.execution_start_ts - :since) / :bucket_width AS INTEGER) AS bucket_idx
                FROM executions e_h
                JOIN listeners l ON l.id = e_h.listener_id
                WHERE e_h.kind = 'handler'
                  AND e_h.execution_start_ts >= :since AND e_h.execution_start_ts < :now
                  {tier_hi_clause}

                UNION ALL

                SELECT sj.app_key, e_j.status,
                    CAST((e_j.execution_start_ts - :since) / :bucket_width AS INTEGER) AS bucket_idx
                FROM executions e_j
                JOIN scheduled_jobs sj ON sj.id = e_j.job_id
                WHERE e_j.kind = 'job'
                  AND e_j.execution_start_ts >= :since AND e_j.execution_start_ts < :now
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

        async with self.execute(query, params) as cursor:
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
        since_hi_clause, since_params = _since_clause(since, "e_h.execution_start_ts")
        since_je_clause, _ = _since_clause(since, "e_j.execution_start_ts")
        tier_hi_clause, tier_params = _source_tier_clause(source_tier, "e_h")
        tier_je_clause, _ = _source_tier_clause(source_tier, "e_j")

        query = f"""
            SELECT app_key, error_message, error_type, execution_start_ts
            FROM (
                SELECT
                    app_key, error_message, error_type, execution_start_ts,
                    ROW_NUMBER() OVER (PARTITION BY app_key ORDER BY execution_start_ts DESC) AS rn
                FROM (
                    SELECT l.app_key, e_h.error_message, e_h.error_type, e_h.execution_start_ts
                    FROM executions e_h
                    JOIN listeners l ON l.id = e_h.listener_id
                    WHERE e_h.kind = 'handler'
                      AND e_h.status IN ('error', 'timed_out')
                      {since_hi_clause} {tier_hi_clause}

                    UNION ALL

                    SELECT sj.app_key, e_j.error_message, e_j.error_type, e_j.execution_start_ts
                    FROM executions e_j
                    JOIN scheduled_jobs sj ON sj.id = e_j.job_id
                    WHERE e_j.kind = 'job'
                      AND e_j.status IN ('error', 'timed_out')
                      {since_je_clause} {tier_je_clause}
                ) combined_inner
            )
            WHERE rn = 1
        """
        params: dict[str, Any] = {**since_params, **tier_params}
        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return {
            row["app_key"]: AppLastError(row["error_message"] or "", row["error_type"], row["execution_start_ts"])
            for row in rows
        }

    async def get_recent_invocations_1h_all_apps(
        self,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, int]:
        """Return handler invocation counts per app_key in the last hour.

        Returns:
            Dict mapping app_key to invocation count. Apps with zero invocations are omitted.
        """
        one_hour_ago = time.time() - SECONDS_PER_HOUR
        tier_clause, tier_params = _source_tier_clause(source_tier, "e")

        query = f"""
            SELECT l.app_key, COUNT(e.rowid) AS invocation_count
            FROM executions e
            JOIN listeners l ON l.id = e.listener_id
            WHERE e.kind = 'handler'
              AND e.execution_start_ts >= :since
              {tier_clause}
            GROUP BY l.app_key
        """
        params: dict[str, Any] = {"since": one_hour_ago, **tier_params}
        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return {row[0]: int(row[1]) for row in rows}

    async def check_execution_predates_retention_cutoff(self, execution_id: str, cutoff: float) -> bool:
        """Check if an execution predates the retention cutoff.

        A single lookup against the unified ``executions`` table by ``execution_id``.
        """
        async with self.execute(
            "SELECT execution_start_ts FROM executions WHERE execution_id = :eid LIMIT 1",
            {"eid": execution_id},
        ) as cursor:
            row = await cursor.fetchone()
        if row is not None:
            return float(row[0]) < cutoff
        return False
