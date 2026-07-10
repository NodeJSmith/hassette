"""Shared helpers for telemetry query modules.

Contains clause-builders, row converters, and the AppHealthAggregates dataclass
used across registration_queries, execution_queries, and summary_queries.
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, assert_never

import aiosqlite

from hassette.schemas.telemetry_models import AppHealthSummary
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
