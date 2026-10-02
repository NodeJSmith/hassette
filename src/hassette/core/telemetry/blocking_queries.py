"""Blocking-event read queries, mixed into TelemetryQueryService."""

import asyncio
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from hassette_wire import BlockingFindingsResponse, UnattributedBlockingResponse

from hassette.core.telemetry.blocking_findings import (
    all_apps_classifier,
    classifier_for_apps,
    group_findings,
    summarize_unattributed,
)
from hassette.core.telemetry.helpers import fetch_all_as_dicts, since_clause

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    import aiosqlite

    from hassette import Hassette

# Distinct (stack, handler) groups read per findings request, most recently seen first. Each group
# carries exact aggregates over all its events, so the cap can only drop the least recently seen
# call sites, and a response that hit it reports truncated=True.
BLOCKING_GROUP_LIMIT = 1000
# Most recent unattributed stalls listed individually on the diagnostics page.
RECENT_UNATTRIBUTED_LIMIT = 20

# One row per distinct stack, handler, and instance. Grouping runs in SQL so counts and stall stats are exact;
# Python then classifies each distinct stack once and merges groups that share a call site. The
# GROUP BY lists every non-aggregated SELECT column; keep the two in step.
_FINDING_GROUPS_QUERY = """
    SELECT be.app_key, be.instance_index, be.instance_name, be.tier, be.primitive, be.frames,
           e.listener_id, e.job_id,
           l.name AS listener_name, l.handler_method AS listener_method,
           sj.job_name, sj.handler_method AS job_method,
           COUNT(*) AS event_count,
           MAX(be.stall_duration_ms) AS max_stall_ms,
           SUM(be.stall_duration_ms) AS stall_sum_ms,
           COUNT(be.stall_duration_ms) AS stall_count,
           MAX(be.detected_ts) AS last_seen_ts,
           MAX(be.id) AS latest_event_id
    FROM blocking_events be
    LEFT JOIN executions e ON e.execution_id = be.execution_id
    LEFT JOIN listeners l ON l.id = e.listener_id
    LEFT JOIN scheduled_jobs sj ON sj.id = e.job_id
    WHERE be.source_tier = 'app'
    {filters}
    GROUP BY be.app_key, be.instance_index, be.instance_name, be.tier, be.primitive, be.frames,
             e.listener_id, e.job_id, l.name, l.handler_method, sj.job_name, sj.handler_method
    -- latest_event_id breaks last-seen ties so the order, and so each finding's latest stack, is stable.
    -- It also names a row to inspect when a group's frames can't be decoded.
    ORDER BY last_seen_ts DESC, latest_event_id DESC
    LIMIT :limit
"""

_UNATTRIBUTED_TOTALS_QUERY = """
    SELECT COUNT(*) AS total_count,
           COALESCE(SUM(reason = 'displaced'), 0) AS displaced_count,
           MAX(stall_duration_ms) AS max_stall_ms
    FROM blocking_events
    WHERE source_tier = 'framework' {since}
"""

_UNATTRIBUTED_RECENT_QUERY = """
    SELECT id, tier, primitive, stall_duration_ms, detected_ts, reason, frames
    FROM blocking_events
    WHERE source_tier = 'framework' {since}
    ORDER BY detected_ts DESC, id DESC
    LIMIT :limit
"""

_BLOCKING_COUNTS_QUERY = """
    SELECT app_key, COUNT(*) AS n FROM blocking_events
    WHERE source_tier = 'app' {since}
    GROUP BY app_key
"""


class BlockingQueriesMixin:
    """Blocking-event findings and counts, mixed into TelemetryQueryService."""

    if TYPE_CHECKING:
        # Provided by TelemetryQueryService; declared for type narrowing within the mixin.
        hassette: "Hassette"
        execute: "Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]]"

    async def get_blocking_findings(
        self, *, app_key: str | None, instance_index: int | None, since: float | None
    ) -> BlockingFindingsResponse:
        """Attributed blocking events grouped into findings, for one app or (``app_key=None``) all apps.

        Args:
            app_key: Restrict to this app, or ``None`` for every app.
            instance_index: Restrict to this instance, or ``None`` for every instance (one finding per
                call site, listing the instances it came from).
            since: Only events detected at or after this Unix epoch time; ``None`` for all time.
        """
        filters = ""
        params: dict[str, Any] = {}
        if app_key is not None:
            filters += " AND be.app_key = :app_key"
            params["app_key"] = app_key
        if instance_index is not None:
            filters += " AND be.instance_index = :instance_index"
            params["instance_index"] = instance_index
        since_sql, since_params = since_clause(since, "be.detected_ts")
        groups = await fetch_all_as_dicts(
            self.execute(
                _FINDING_GROUPS_QUERY.format(filters=f"{filters} {since_sql}"),
                {**params, **since_params, "limit": BLOCKING_GROUP_LIMIT + 1},
            )
        )
        # Classifying stacks is pure-Python CPU work that grows with the number of distinct stacks; a
        # worker thread keeps it off the event loop the watchdog is measuring.
        findings = await asyncio.to_thread(
            group_findings, groups[:BLOCKING_GROUP_LIMIT], classifier_for_apps(self._app_dirs())
        )
        return BlockingFindingsResponse(findings=findings, truncated=len(groups) > BLOCKING_GROUP_LIMIT)

    async def get_unattributed_blocking(self, *, since: float | None) -> UnattributedBlockingResponse:
        """Blocking events credited to no app (displaced or framework), for the diagnostics page."""
        since_sql, params = since_clause(since, "detected_ts")
        # An aggregate with no GROUP BY always returns exactly one row. The totals and the recent rows are
        # separate reads, so a stall recorded between them can show in one and not the other.
        [totals] = await fetch_all_as_dicts(self.execute(_UNATTRIBUTED_TOTALS_QUERY.format(since=since_sql), params))
        recent = await fetch_all_as_dicts(
            self.execute(
                _UNATTRIBUTED_RECENT_QUERY.format(since=since_sql), {**params, "limit": RECENT_UNATTRIBUTED_LIMIT}
            )
        )
        return summarize_unattributed(totals, recent, all_apps_classifier(self._app_dirs()))

    async def get_blocking_event_counts(self, *, since: float | None) -> dict[str, int]:
        """Attributed blocking-event count per app key in the window. Apps with none are absent."""
        since_sql, params = since_clause(since, "detected_ts")
        rows = await fetch_all_as_dicts(self.execute(_BLOCKING_COUNTS_QUERY.format(since=since_sql), params))
        return {row["app_key"]: row["n"] for row in rows}

    def _app_dirs(self) -> dict[str, PurePath]:
        """Each configured app's resolved directory, read fresh so config reloads apply."""
        return {key: PurePath(m.app_dir) for key, m in self.hassette.config.apps.manifests.items()}
