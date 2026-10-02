"""Blocking-event read queries, mixed into TelemetryQueryService."""

from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from hassette_wire import BlockingFindingsResponse, UnattributedBlockingResponse

from hassette.core.telemetry.blocking_findings import classifier_for_apps, group_findings, summarize_unattributed
from hassette.core.telemetry.helpers import fetch_all_as_dicts, since_clause

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    import aiosqlite

    from hassette import Hassette

# Rows read per request, most recent first. Retention bounds the table, and a window holding more
# events than this reports truncated=True rather than reading without limit.
BLOCKING_ROW_LIMIT = 1000

_ROWS_QUERY = """
    SELECT be.id, be.app_key, be.instance_index, be.tier, be.primitive, be.stall_duration_ms,
           be.detected_ts, be.reason, be.frames,
           e.listener_id, e.job_id,
           l.name AS listener_name, l.handler_method AS listener_method,
           sj.job_name, sj.handler_method AS job_method
    FROM blocking_events be
    LEFT JOIN executions e ON e.execution_id = be.execution_id
    LEFT JOIN listeners l ON l.id = e.listener_id
    LEFT JOIN scheduled_jobs sj ON sj.id = e.job_id
    WHERE be.source_tier = :source_tier
    {filters}
    ORDER BY be.detected_ts DESC, be.id DESC
    LIMIT :limit
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
            instance_index: Restrict to this instance, or ``None`` for every instance.
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
        rows, truncated = await self._fetch_blocking_rows("app", filters, params, since)
        findings = group_findings(rows, classifier_for_apps(self._app_dirs()))
        return BlockingFindingsResponse(findings=findings, truncated=truncated)

    async def get_unattributed_blocking(self, *, since: float | None) -> UnattributedBlockingResponse:
        """Blocking events credited to no app (displaced or framework), for the diagnostics page."""
        rows, truncated = await self._fetch_blocking_rows("framework", "", {}, since)
        classifier = classifier_for_apps(self._app_dirs())(None)
        return summarize_unattributed(rows, classifier, truncated=truncated)

    async def get_blocking_event_counts(self, *, since: float | None) -> dict[str, int]:
        """Attributed blocking-event count per app key in the window. Apps with none are absent."""
        since_sql, params = since_clause(since, "detected_ts")
        rows = await fetch_all_as_dicts(
            self.execute(
                f"""
                SELECT app_key, COUNT(*) AS n FROM blocking_events
                WHERE source_tier = 'app' {since_sql}
                GROUP BY app_key
                """,
                params,
            )
        )
        return {row["app_key"]: row["n"] for row in rows}

    async def _fetch_blocking_rows(
        self, source_tier: str, filters: str, params: dict[str, Any], since: float | None
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch up to ``BLOCKING_ROW_LIMIT`` rows newest first, and whether more existed."""
        since_sql, since_params = since_clause(since, "be.detected_ts")
        query = _ROWS_QUERY.format(filters=f"{filters} {since_sql}")
        rows = await fetch_all_as_dicts(
            self.execute(query, {**params, **since_params, "source_tier": source_tier, "limit": BLOCKING_ROW_LIMIT + 1})
        )
        return rows[:BLOCKING_ROW_LIMIT], len(rows) > BLOCKING_ROW_LIMIT

    def _app_dirs(self) -> dict[str, PurePath]:
        """Each configured app's resolved directory, read fresh so config reloads apply."""
        return {key: PurePath(m.app_dir) for key, m in self.hassette.config.apps.manifests.items()}
