"""Shared helpers for telemetry query modules.

Contains clause-builders, row converters, and the AppHealthAggregates dataclass
used across registration_queries, execution_queries, and summary_queries.
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, assert_never

import aiosqlite

from hassette.schemas.summary_models import AppHealthSummary
from hassette.types.types import QuerySourceTier, is_framework_key

# Storage-layer exceptions translated to TelemetryUnavailableError at the read boundary.
# Named once here so both the execute() chokepoint and the get_all_app_summaries bypass
# (which runs a manual BEGIN DEFERRED transaction) catch the identical set.
STORAGE_ERRORS = (sqlite3.Error, OSError, ValueError, TimeoutError)

DEFAULT_SESSION_LIST_LIMIT = 20
"""Default number of recent sessions returned by get_session_list."""

DEFAULT_LOG_RECORDS_LIMIT = 100
"""Default row cap for get_log_records."""

DEFAULT_EXECUTION_LOG_LIMIT = 500
"""Default row cap for log records of a single execution (get_log_records_by_execution)."""

# Exports the package's public constants plus the clause-builders shared by the query
# mixins. The clause-builders keep their underscore prefix (package-internal, not for
# callers outside hassette.core.telemetry); listing them here marks them as exported so
# the cross-module imports don't read as unused.
__all__ = [
    "DEFAULT_EXECUTION_LOG_LIMIT",
    "DEFAULT_LOG_RECORDS_LIMIT",
    "DEFAULT_SESSION_LIST_LIMIT",
    "STORAGE_ERRORS",
    "AppHealthAggregates",
    "build_app_summaries",
    "handler_job_union_arms",
    "row_to_dict",
    "since_clause",
    "source_tier_clause",
]


@dataclass(frozen=True)
class AppHealthAggregates:
    """Single-row aggregate result returned by ``get_app_health_aggregates()``.

    All counts and averages are computed in a single query over the ``executions``
    table - no per-item detail fetching or Python-side aggregation.
    """

    total_invocations: int
    handler_errors: int
    handler_timed_out: int
    handler_avg_duration_ms: float
    total_executions: int
    job_errors: int
    job_timed_out: int
    job_avg_duration_ms: float
    last_activity_ts: float | None


def row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert an aiosqlite Row to a plain dict."""
    return dict(zip(row.keys(), tuple(row), strict=False))


def source_tier_clause(source_tier: QuerySourceTier, alias: str) -> tuple[str, dict[str, str]]:
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


def since_clause(since: float | None, timestamp_col: str) -> tuple[str, dict[str, float]]:
    """Return a (fragment, params) tuple for timestamp lower-bound filtering.

    When ``since`` is not None, returns a parameterised ``AND`` fragment that
    restricts rows to those with ``timestamp_col >= :since``.  When absent,
    returns ``("", {})`` (no filter).

    Args:
        since: Unix epoch float lower bound, or ``None`` for no filter.
        timestamp_col: The SQL column expression to filter on.
    """
    if since is None:
        return ("", {})
    # timestamp_col is an internal SQL column reference; no user data flows here
    return (f"AND {timestamp_col} >= :since", {"since": since})


def handler_job_union_arms(
    handler_select: str,
    job_select: str,
    *,
    extra_handler_where: str = "",
    extra_job_where: str = "",
    since: float | None = None,
    source_tier: QuerySourceTier = "app",
    instance_index: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build handler UNION ALL job SQL fragment with merged params.

    Both arms query the unified ``executions`` table: the handler arm (aliased ``e_h``)
    joins ``listeners`` as ``l``, and the job arm (aliased ``e_j``) joins ``scheduled_jobs``
    as ``sj``. Callers supply the SELECT column list for each arm (``handler_select`` /
    ``job_select``, including the leading ``SELECT`` keyword) and any arm-specific WHERE
    fragments (``extra_handler_where`` / ``extra_job_where``, e.g. an ``app_key`` filter).

    ``since_clause`` and ``source_tier_clause`` are called once per alias so each arm's
    fragment references the correct column, but both arms bind the same parameter names
    (``:since``, ``:source_tier``) - the second call's params dict is a duplicate and is
    intentionally discarded, matching the convention documented on the UNION methods in
    ``execution_queries.py``.

    Args:
        handler_select: Full ``SELECT ...`` column list for the handler arm.
        job_select: Full ``SELECT ...`` column list for the job arm.
        extra_handler_where: Additional ``AND ...`` fragment appended to the handler arm's
            WHERE clause (e.g. an ``app_key`` or ``status`` filter). Caller supplies any
            bind params this fragment references.
        extra_job_where: Additional ``AND ...`` fragment appended to the job arm's WHERE
            clause. Caller supplies any bind params this fragment references.
        since: Unix epoch float lower bound for ``execution_start_ts``, or ``None`` to skip
            the ``since_clause`` filter (e.g. when the caller expresses time bounds itself
            via ``extra_handler_where``/``extra_job_where``).
        source_tier: Filter by source tier.
        instance_index: When provided, restricts each arm to that instance only.

    Returns:
        A ``(sql_fragment, params)`` tuple. ``sql_fragment`` is the two-arm ``UNION ALL``
        body (no enclosing ``SELECT ... FROM (`` wrapper); ``params`` merges the
        deduplicated ``since``/``source_tier`` bind values with the ``instance_index`` value
        when applicable.
    """
    tier_hi_clause, tier_params = source_tier_clause(source_tier, "e_h")
    tier_je_clause, _ = source_tier_clause(source_tier, "e_j")
    since_hi_clause, since_params = since_clause(since, "e_h.execution_start_ts")
    since_je_clause, _ = since_clause(since, "e_j.execution_start_ts")

    instance_hi_clause = ""
    instance_je_clause = ""
    instance_params: dict[str, int] = {}
    if instance_index is not None:
        instance_hi_clause = "AND l.instance_index = :instance_index"
        instance_je_clause = "AND sj.instance_index = :instance_index"
        instance_params = {"instance_index": instance_index}

    fragment = f"""
        {handler_select}
        FROM executions e_h
        JOIN listeners l ON l.id = e_h.listener_id
        WHERE e_h.kind = 'handler'
          {extra_handler_where}
          {instance_hi_clause}
          {since_hi_clause}
          {tier_hi_clause}

        UNION ALL

        {job_select}
        FROM executions e_j
        JOIN scheduled_jobs sj ON sj.id = e_j.job_id
        WHERE e_j.kind = 'job'
          {extra_job_where}
          {instance_je_clause}
          {since_je_clause}
          {tier_je_clause}
    """

    params: dict[str, Any] = {**since_params, **tier_params, **instance_params}
    return (fragment, params)


def build_app_summaries(
    *,
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
        dicts = [row_to_dict(r) for r in rows]
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
