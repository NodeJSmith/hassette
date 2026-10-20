"""App-level summary and log query methods."""

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, assert_never

from hassette_wire import QuerySourceTier

from hassette.core.telemetry.helpers import (
    DEFAULT_EXECUTION_LOG_LIMIT,
    DEFAULT_LOG_RECORDS_LIMIT,
    STORAGE_ERRORS,
    build_app_summaries,
    fetch_all_as_dicts,
    log_record_filter_clauses,
    row_to_dict,
    since_clause,
    source_tier_clause,
)
from hassette.exceptions import TelemetryUnavailableError
from hassette.schemas.summary_models import AppHealthAggregates, AppHealthSummary

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from contextlib import AbstractAsyncContextManager

    import aiosqlite

    from hassette import Hassette


# Shared prefix for log-record reads: every log row plus its owning execution's kind and
# listener/job id (NULL when the record has no execution). Callers append WHERE/ORDER/LIMIT.
LOG_RECORD_SELECT = """
    SELECT lr.*, e.kind AS execution_kind, e.listener_id, e.job_id
    FROM log_records lr
    LEFT JOIN executions e ON lr.execution_id = e.execution_id
"""


class SummaryQueriesMixin:
    """App-health and log summary query methods, mixed into TelemetryQueryService."""

    if TYPE_CHECKING:
        # Provided by TelemetryQueryService; declared for type narrowing within the mixin.
        # This mixin reaches _db / _snapshot_lock directly (for the batched BEGIN DEFERRED read
        # in _read_summary_snapshot); the sibling mixins only need execute().
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

        Uses a single query against ``executions``. SQLite does not support ``FILTER``; uses
        ``SUM(CASE WHEN kind='handler' ...)`` instead. Executions of handlers and jobs removed
        since they ran still count: health over a window reflects what ran in it.

        Args:
            app_key: The app key to filter by.
            instance_index: The app instance index to filter by.
            since: When provided, restrict counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter by source tier.
        """
        tier_e_clause, tier_params = source_tier_clause(source_tier, "e")
        since_sql, since_params = since_clause(since, "e.execution_start_ts")

        params: dict[str, Any] = {
            "app_key": app_key,
            "instance_index": instance_index,
            **tier_params,
            **since_params,
        }

        query = f"""
            SELECT
                SUM(CASE WHEN e.kind = 'handler' THEN 1 ELSE 0 END) AS total_invocations,
                SUM(CASE WHEN e.kind = 'handler' AND e.status = 'error' THEN 1 ELSE 0 END) AS handler_errors,
                SUM(CASE WHEN e.kind = 'handler' AND e.status = 'timed_out' THEN 1 ELSE 0 END) AS handler_timed_out,
                AVG(CASE WHEN e.kind = 'handler' THEN e.duration_ms END) AS handler_avg_duration_ms,
                SUM(CASE WHEN e.kind = 'job' THEN 1 ELSE 0 END) AS total_executions,
                SUM(CASE WHEN e.kind = 'job' AND e.status = 'error' THEN 1 ELSE 0 END) AS job_errors,
                SUM(CASE WHEN e.kind = 'job' AND e.status = 'timed_out' THEN 1 ELSE 0 END) AS job_timed_out,
                -- A skipped job run did no work, so its duration would drag the average down.
                AVG(CASE WHEN e.kind = 'job' AND e.status != 'skipped'
                    THEN e.duration_ms END) AS job_avg_duration_ms,
                MAX(e.execution_start_ts) AS last_activity_ts
            FROM executions e
            LEFT JOIN listeners l ON l.id = e.listener_id AND e.kind = 'handler'
            LEFT JOIN scheduled_jobs sj ON sj.id = e.job_id AND e.kind = 'job'
            WHERE (
                (e.kind = 'handler' AND l.app_key = :app_key AND l.instance_index = :instance_index)
                OR
                (e.kind = 'job' AND sj.app_key = :app_key AND sj.instance_index = :instance_index)
            )
            {tier_e_clause}
            {since_sql}
        """
        async with self.execute(query, params) as cursor:
            row = await cursor.fetchone()

        # SUMs over no rows are NULL, hence the `or 0` below.
        row_dict = row_to_dict(row)  # pyright: ignore[reportArgumentType] — aggregates without GROUP BY yield one row
        return AppHealthAggregates(
            total_invocations=row_dict["total_invocations"] or 0,
            handler_errors=row_dict["handler_errors"] or 0,
            handler_timed_out=row_dict["handler_timed_out"] or 0,
            handler_avg_duration_ms=row_dict["handler_avg_duration_ms"],
            total_executions=row_dict["total_executions"] or 0,
            job_errors=row_dict["job_errors"] or 0,
            job_timed_out=row_dict["job_timed_out"] or 0,
            job_avg_duration_ms=row_dict["job_avg_duration_ms"],
            last_activity_ts=row_dict["last_activity_ts"],
        )

    async def get_all_app_summaries(
        self,
        since: float | None = None,
        source_tier: QuerySourceTier = "app",
    ) -> dict[str, AppHealthSummary]:
        """Return per-app health summaries via 4 batch SQL queries read in one snapshot.

        Registration counts (handler_count, job_count) use the ``active_*`` views. Activity
        aggregates join the raw ``listeners``/``scheduled_jobs`` tables, so executions of
        handlers and jobs removed since they ran still count, as in ``get_app_health_aggregates``.

        Args:
            since: When provided, restrict activity counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter by source tier.
        """
        listener_act_query, listener_act_params = listener_activity_query(source_tier, since)
        job_act_query, job_act_params = job_activity_query(source_tier, since)
        listener_reg_rows, listener_act_rows, job_reg_rows, job_act_rows = await self._read_summary_snapshot(
            [
                (listener_registration_query(source_tier), None),
                (listener_act_query, listener_act_params),
                (job_registration_query(source_tier), None),
                (job_act_query, job_act_params),
            ]
        )

        return build_app_summaries(
            listener_reg_rows=listener_reg_rows,
            listener_act_rows=listener_act_rows,
            job_reg_rows=job_reg_rows,
            job_act_rows=job_act_rows,
            source_tier=source_tier,
        )

    async def _read_summary_snapshot(
        self, queries: "Sequence[tuple[str, dict[str, Any] | None]]"
    ) -> "list[Iterable[aiosqlite.Row]]":
        """Run ``queries`` in order inside one ``BEGIN DEFERRED`` snapshot and return each one's rows.

        Bypasses ``execute()`` so every read sees the same snapshot, and therefore applies the same
        read timeout and ``STORAGE_ERRORS`` -> ``TelemetryUnavailableError`` translation itself.
        """
        results: list[Iterable[aiosqlite.Row]] = []
        try:
            async with asyncio.timeout(self.hassette.config.database.read_timeout_seconds), self._snapshot_lock:
                try:
                    await self._db.execute("BEGIN DEFERRED")
                    for query, params in queries:
                        async with self._db.execute(query, params) as cursor:
                            results.append(await cursor.fetchall())
                finally:
                    # Always discard the read snapshot. Suppress broadly so a ROLLBACK failure
                    # (e.g. no transaction is open) can never mask an exception from the queries.
                    with contextlib.suppress(Exception):
                        await self._db.execute("ROLLBACK")
        except STORAGE_ERRORS as exc:
            raise TelemetryUnavailableError(str(exc)) from exc
        return results

    # dup-ignore-start: filter param list intentionally mirrors the e2e test double in
    # tests/e2e/conftest.py that stands in for this method — signature drift between them
    # would silently break e2e log filtering.
    async def get_log_records(
        self,
        *,
        limit: int = DEFAULT_LOG_RECORDS_LIMIT,
        since: float | None = None,
        app_key: str | None = None,
        level: str | None = None,
        execution_id: str | None = None,
        source_tier: QuerySourceTier = "all",
        instance_index: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch log records with optional filters, ordered by timestamp DESC.

        ``session_id`` is intentionally not included in the SELECT — session identity is
        not exposed in the API. All other log_records columns are returned as-is.
        """
        # dup-ignore-end
        clauses, params = log_record_filter_clauses(
            since=since,
            app_key=app_key,
            level=level,
            execution_id=execution_id,
            source_tier=source_tier,
            instance_index=instance_index,
        )

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params["limit"] = limit

        query = f"""
            {LOG_RECORD_SELECT}
            {where}
            ORDER BY lr.timestamp DESC, lr.seq DESC
            LIMIT :limit
        """
        return await fetch_all_as_dicts(self.execute(query, params))

    async def get_log_records_by_execution(
        self,
        execution_id: str,
        *,
        limit: int = DEFAULT_EXECUTION_LOG_LIMIT,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch all log records for a single execution, ordered by seq ASC."""
        query = f"""
            {LOG_RECORD_SELECT}
            WHERE lr.execution_id = :execution_id
            ORDER BY lr.seq ASC
            LIMIT :limit
        """
        async with self.execute(query, {"execution_id": execution_id, "limit": limit + 1}) as cursor:
            rows = list(await cursor.fetchall())
        truncated = len(rows) > limit
        return [row_to_dict(row) for row in rows[:limit]], truncated


def active_registration_views(source_tier: QuerySourceTier) -> tuple[str, str]:
    """Return the ``(listener_view, job_view)`` pair of ``active_*`` views for a source tier."""
    match source_tier:
        case "app":
            return "active_app_listeners", "active_app_scheduled_jobs"
        case "framework":
            return "active_framework_listeners", "active_framework_scheduled_jobs"
        case "all":
            return "active_listeners", "active_scheduled_jobs"
        case _ as unreachable:
            assert_never(unreachable)


# Registration queries count distinct handler/job identities across all instances, not rows.
# Each instance of a multi-instance app registers its own rows under the same (name, topic)/job_name
# identity, so COUNT(DISTINCT id) would multiply the count by instance_count. The two natural-key
# parts are concatenated into one distinct key joined by char(31) — the ASCII unit separator, chosen
# because it cannot occur in an entity name or topic, so it can never collide with the parts it separates.
def listener_registration_query(source_tier: QuerySourceTier) -> str:
    """Build the per-app distinct handler count query over currently registered listeners."""
    listener_view, _ = active_registration_views(source_tier)
    return f"""
        SELECT l.app_key, COUNT(DISTINCT l.name || char(31) || l.topic) AS handler_count
        FROM {listener_view} l
        GROUP BY l.app_key
    """


def job_registration_query(source_tier: QuerySourceTier) -> str:
    """Build the per-app distinct job count query over currently registered jobs."""
    _, job_view = active_registration_views(source_tier)
    return f"""
        SELECT sj.app_key, COUNT(DISTINCT sj.job_name) AS job_count
        FROM {job_view} sj
        GROUP BY sj.app_key
    """


# Activity queries select executions by the execution's own tier, as get_app_health_aggregates does,
# so both scopes count the same executions even after a registration's tier changes. Inner joins: an
# app with no matching executions gets no activity row, and its summary falls back to zero counts and
# null averages in build_app_summaries.
def listener_activity_query(source_tier: QuerySourceTier, since: float | None) -> tuple[str, dict[str, Any]]:
    """Build the per-app handler activity aggregate query and its bound params."""
    tier_clause, tier_params = source_tier_clause(source_tier, "e_h")
    since_sql, since_params = since_clause(since, "e_h.execution_start_ts")
    query = f"""
        SELECT
            l.app_key,
            COUNT(e_h.rowid) AS total_invocations,
            SUM(CASE WHEN e_h.status = 'error' THEN 1 ELSE 0 END) AS handler_errors,
            SUM(CASE WHEN e_h.status = 'timed_out' THEN 1 ELSE 0 END) AS handler_timed_out,
            AVG(e_h.duration_ms) AS handler_avg_duration_ms,
            MAX(e_h.execution_start_ts) AS last_listener_activity_ts
        FROM listeners l
        JOIN executions e_h ON e_h.listener_id = l.id AND e_h.kind = 'handler'
            {tier_clause}
            {since_sql}
        GROUP BY l.app_key
    """
    return query, {**tier_params, **since_params}


def job_activity_query(source_tier: QuerySourceTier, since: float | None) -> tuple[str, dict[str, Any]]:
    """Build the per-app job activity aggregate query and its bound params."""
    tier_clause, tier_params = source_tier_clause(source_tier, "e_j")
    since_sql, since_params = since_clause(since, "e_j.execution_start_ts")
    query = f"""
        SELECT
            sj.app_key,
            COUNT(e_j.rowid) AS total_executions,
            SUM(CASE WHEN e_j.status = 'error' THEN 1 ELSE 0 END) AS job_errors,
            SUM(CASE WHEN e_j.status = 'timed_out' THEN 1 ELSE 0 END) AS job_timed_out,
            -- Skipped runs excluded, as in get_app_health_aggregates.
            AVG(CASE WHEN e_j.status != 'skipped' THEN e_j.duration_ms END) AS job_avg_duration_ms,
            MAX(e_j.execution_start_ts) AS last_job_activity_ts
        FROM scheduled_jobs sj
        JOIN executions e_j ON e_j.job_id = sj.id AND e_j.kind = 'job'
            {tier_clause}
            {since_sql}
        GROUP BY sj.app_key
    """
    return query, {**tier_params, **since_params}
