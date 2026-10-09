"""Registration-level telemetry query methods: listener and job summaries, slow handlers."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hassette_wire import JobSummary, QuerySourceTier

from hassette.core.telemetry.helpers import (
    SQL_FAILED_STATUSES,
    SQL_KIND_HANDLER,
    SQL_KIND_JOB,
    SQL_NO_FILTER,
    SQL_STATUS_CANCELLED,
    SQL_STATUS_ERROR,
    SQL_STATUS_SUCCESS,
    SQL_STATUS_TIMED_OUT,
    row_to_dict,
    since_clause,
    source_tier_clause,
)
from hassette.schemas.listener_models import ListenerSummaryRow, SlowHandlerRecord
from hassette.schemas.query_constants import DEFAULT_QUERY_LIMIT
from hassette.types.types import APP_SOURCE_TIER

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    import aiosqlite


@dataclass(frozen=True)
class RegistrationSummarySource:
    """The per-kind pieces of a registration summary query; see ``build_registration_summary_query``."""

    table: str
    """Registration table (``listeners`` or ``scheduled_jobs``)."""

    alias: str
    """SQL alias for ``table``; ``select_columns`` must reference the table through it."""

    fk_column: str
    """Column on ``executions`` that references ``table.id``."""

    kind: str
    """SQL literal for the ``executions.kind`` value belonging to this registration type."""

    tombstone_columns: tuple[str, ...]
    """Timestamp columns that must all be NULL for a registration to count as live."""

    select_columns: str
    """Registration columns and execution aggregates; ``e`` is the executions row, ``last_err`` the latest failure."""


LISTENER_SUMMARY_SOURCE = RegistrationSummarySource(
    table="listeners",
    alias="l",
    fk_column="listener_id",
    kind=SQL_KIND_HANDLER,
    tombstone_columns=("removed_at",),
    select_columns=f"""
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
                SUM(CASE WHEN e.status = {SQL_STATUS_SUCCESS} THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN e.status = {SQL_STATUS_ERROR} THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN e.is_di_failure = 1 THEN 1 ELSE 0 END) AS di_failures,
                SUM(CASE WHEN e.status = {SQL_STATUS_CANCELLED} THEN 1 ELSE 0 END) AS cancelled,
                SUM(CASE WHEN e.status = {SQL_STATUS_TIMED_OUT} THEN 1 ELSE 0 END) AS timed_out,
                SUM(CASE WHEN e.thread_leaked = 1 THEN 1 ELSE 0 END) AS thread_leaked,
                COALESCE(SUM(e.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(e.duration_ms), 0.0) AS avg_duration_ms,
                MIN(e.duration_ms) AS min_duration_ms,
                MAX(e.duration_ms) AS max_duration_ms,
                MAX(e.execution_start_ts) AS last_invoked_at,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message,
                last_err.error_traceback AS last_error_traceback""",
)

JOB_SUMMARY_SOURCE = RegistrationSummarySource(
    table="scheduled_jobs",
    alias="sj",
    fk_column="job_id",
    kind=SQL_KIND_JOB,
    tombstone_columns=("removed_at", "retired_at"),
    select_columns=f"""
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
                sj.mode,
                sj.predicate_description,
                sj.human_description,
                sj.schedule_status,
                sj.schedule_status_reason,
                COUNT(e.rowid) AS total_executions,
                SUM(CASE WHEN e.status = {SQL_STATUS_SUCCESS} THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN e.status = {SQL_STATUS_ERROR} THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN e.status = {SQL_STATUS_CANCELLED} THEN 1 ELSE 0 END) AS cancelled,
                SUM(CASE WHEN e.status = {SQL_STATUS_TIMED_OUT} THEN 1 ELSE 0 END) AS timed_out,
                SUM(CASE WHEN e.status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                SUM(CASE WHEN e.thread_leaked = 1 THEN 1 ELSE 0 END) AS thread_leaked,
                MAX(e.execution_start_ts) AS last_executed_at,
                COALESCE(SUM(e.duration_ms), 0.0) AS total_duration_ms,
                COALESCE(AVG(CASE WHEN e.status != 'skipped' THEN e.duration_ms END), 0.0) AS avg_duration_ms,
                MIN(CASE WHEN e.status != 'skipped' THEN e.duration_ms END) AS min_duration_ms,
                MAX(CASE WHEN e.status != 'skipped' THEN e.duration_ms END) AS max_duration_ms,
                last_err.error_type AS last_error_type,
                last_err.error_message AS last_error_message,
                last_err.execution_start_ts AS last_error_ts,
                last_err.error_traceback AS last_error_traceback""",
)


class RegistrationQueriesMixin:
    """Listener/job registration-summary query methods, mixed into TelemetryQueryService."""

    if TYPE_CHECKING:
        # Provided by TelemetryQueryService; declared for type narrowing within the mixin.
        execute: "Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]]"

    async def get_listener_summary(
        self,
        app_key: str | None = None,
        instance_index: int | None = None,
        since: float | None = None,
        source_tier: QuerySourceTier = APP_SOURCE_TIER,
    ) -> list[ListenerSummaryRow]:
        """Return per-listener summaries, optionally filtered to a specific app instance.

        When ``app_key`` is ``None``, returns all listeners across all apps (no WHERE filter
        on app_key or instance_index). When ``app_key`` is provided, returns only listeners
        for that app and instance (``instance_index`` defaults to 0).

        Args:
            app_key: The app key to filter by. ``None`` returns all apps.
            instance_index: The app instance index to filter by. Ignored when ``app_key`` is ``None``.
            since: When provided, restrict invocation counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter listeners by source tier.
        """
        query, params = build_registration_summary_query(
            LISTENER_SUMMARY_SOURCE,
            app_key=app_key,
            instance_index=instance_index,
            since=since,
            source_tier=source_tier,
        )
        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [ListenerSummaryRow.model_validate(row_to_dict(row)) for row in rows]

    async def get_job_summary(
        self,
        app_key: str | None = None,
        instance_index: int | None = None,
        since: float | None = None,
        source_tier: QuerySourceTier = APP_SOURCE_TIER,
    ) -> list[JobSummary]:
        """Return per-job summaries, optionally filtered to a specific app instance.

        When ``app_key`` is ``None``, returns all jobs across all apps (no WHERE filter
        on app_key or instance_index). When ``app_key`` is provided, returns only jobs
        for that app and instance (``instance_index`` defaults to 0).

        Args:
            app_key: The app key to filter by. ``None`` returns all apps.
            instance_index: The app instance index to filter by. Ignored when ``app_key`` is ``None``.
            since: When provided, restrict execution counts to records with
                ``execution_start_ts >= since`` (Unix epoch float).
            source_tier: Filter jobs by source tier.
        """
        query, params = build_registration_summary_query(
            JOB_SUMMARY_SOURCE,
            app_key=app_key,
            instance_index=instance_index,
            since=since,
            source_tier=source_tier,
        )
        async with self.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [JobSummary.model_validate(row_to_dict(row)) for row in rows]

    async def get_slow_handlers(
        self,
        threshold_ms: float,
        limit: int = DEFAULT_QUERY_LIMIT,
        source_tier: QuerySourceTier = APP_SOURCE_TIER,
    ) -> list[SlowHandlerRecord]:
        """Return handler executions whose duration exceeds threshold_ms.

        Uses LEFT JOIN so that orphaned executions (whose listener was deleted)
        still appear in results with null ``app_key``.

        Args:
            threshold_ms: Only return executions slower than this value.
            limit: Maximum number of records to return.
            source_tier: Filter by ``source_tier`` on executions.
        """
        tier_clause, tier_params = source_tier_clause(source_tier, "e")
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
            WHERE e.kind = {SQL_KIND_HANDLER}
              AND e.duration_ms > :threshold_ms
              {tier_clause}
            ORDER BY e.duration_ms DESC
            LIMIT :limit
        """
        async with self.execute(query, {"threshold_ms": threshold_ms, "limit": limit, **tier_params}) as cursor:
            rows = await cursor.fetchall()
        return [SlowHandlerRecord.model_validate(row_to_dict(row)) for row in rows]


def build_registration_summary_query(
    source: RegistrationSummarySource,
    *,
    app_key: str | None,
    instance_index: int | None,
    since: float | None,
    source_tier: QuerySourceTier,
) -> tuple[str, dict[str, Any]]:
    """Build the per-registration summary query and its bind parameters.

    Every live registration row is left-joined to its executions (restricted by ``since``) for the
    aggregate columns, and to its most recent failed execution (via the ``ranked_errors`` CTE) for
    the ``last_err`` columns. When ``app_key`` is ``None`` no app/instance filter is applied;
    otherwise ``instance_index`` defaults to 0.
    """
    alias = source.alias
    tier_clause, tier_params = source_tier_clause(source_tier, alias)
    since_join_clause, since_params = since_clause(since, "e.execution_start_ts")
    since_err_clause, _ = since_clause(since, "e_err.execution_start_ts")

    if app_key is not None:
        where_clause = f"{alias}.app_key = :app_key AND {alias}.instance_index = :instance_index"
        params: dict[str, Any] = {
            "app_key": app_key,
            "instance_index": instance_index if instance_index is not None else 0,
            **tier_params,
            **since_params,
        }
    else:
        where_clause = SQL_NO_FILTER
        params = {**tier_params, **since_params}

    live_filter = "".join(f"\n            AND {alias}.{column} IS NULL" for column in source.tombstone_columns)
    query = f"""
            WITH ranked_errors AS (
                SELECT e_err.{source.fk_column}, e_err.error_type, e_err.error_message,
                       e_err.error_traceback, e_err.execution_start_ts,
                       ROW_NUMBER() OVER (
                           PARTITION BY e_err.{source.fk_column} ORDER BY e_err.execution_start_ts DESC
                       ) AS rn
                FROM executions e_err
                WHERE e_err.kind = {source.kind}
                  AND e_err.status IN {SQL_FAILED_STATUSES} {since_err_clause}
            )
            SELECT {source.select_columns}
            FROM {source.table} {alias}
            LEFT JOIN executions e ON e.{source.fk_column} = {alias}.id {since_join_clause} AND e.kind = {source.kind}
            LEFT JOIN ranked_errors last_err ON last_err.{source.fk_column} = {alias}.id AND last_err.rn = 1
            WHERE {where_clause}{live_filter}
            {tier_clause}
            GROUP BY {alias}.id
        """
    return query, params
