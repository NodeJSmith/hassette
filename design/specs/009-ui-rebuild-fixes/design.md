# Design: UI Rebuild Post-Critique Fixes

**Date:** 2026-03-19
**Status:** archived
**Critique:** design/critiques/2026-03-19-ui-rebuild-challenge/critique.md
**Research:** design/research/2026-03-19-alpine-live-updates/research.md
**Critique iterations:** 4 rounds — morph approach revised twice, then abandoned in favor of completing existing polling partial

## Problem

The UI rebuild (008-ui-rebuild) has 6 design flaws identified by adversarial critique (7th deferred to issue). These range from N+1 queries that freeze the dashboard on Pi hardware, to live-update morphs destroying user investigation state, to dead polling code and inconsistent health thresholds.

**Deferred to GitHub issue:** CDN dependencies (finding #6) — vendor JS/fonts as static files.

## Findings to Fix

| # | Finding | Severity | Approach |
|---|---------|----------|----------|
| 1 | N+1 dashboard queries | CRITICAL | Batch SQL: `get_all_app_summaries()` — 2 queries total regardless of app count |
| 2 | Alpine state destroyed by morph | CRITICAL | Complete the existing 5s polling JS. Remove handler/job lists from morph targets. |
| 3 | Dead 5s polling + competing updates | HIGH | Not dead — complete it. Write ~15 lines of JS to read `data-*` attrs and update counts/dots. |
| 4 | Typed models unused | HIGH | Wire `GlobalSummary` + `SessionSummary` to query methods |
| 5 | Health thresholds scattered | HIGH | Centralize `classify_error_rate()` and `classify_health_bar()` in context.py |
| 7 | Apps page/partial template divergence | MEDIUM | Server-side filtering via `?status=` param |

## Architecture

### 1. Batch Dashboard Query (replaces N+1)

Add `get_all_app_summaries()` to `TelemetryQueryService`. Two SQL queries total (one for listeners, one for jobs) with `GROUP BY app_key`, regardless of app count.

Returns `dict[str, AppHealthSummary]` where `AppHealthSummary` is a new Pydantic model with raw counts: `handler_count`, `job_count`, `total_invocations`, `total_errors`, `total_executions`, `total_job_errors`, `avg_duration_ms`, `last_activity_ts`.

**Multi-instance:** SQL uses `WHERE instance_index = 0` to match current dashboard behavior.

`compute_app_grid_health()` in context.py becomes a thin wrapper calling this method once.

### 2. Complete the 5s Polling Partial (fixes morph state loss + dead polling)

**Key insight from 4 rounds of critique:** `app_status_changed` only fires on app lifecycle events (start/stop/fail), NOT on handler invocations. The morph approach was solving for an event that rarely fires. The existing 5s polling partial already provides time-based freshness — it just needs the consuming JS.

**What exists:**
- `app_detail.html:115-122` — hidden div with `hx-trigger="every 5s"` that polls `/ui/partials/app-handler-stats/{app_key}`
- `partials.py:147-157` — backend route that queries `telemetry.get_listener_summary()` and returns HTML
- `app_handler_stats.html` — renders `<span>` elements with `data-listener-id`, `data-total-invocations`, `data-failed`, `data-avg-duration-ms` attributes

**What's missing:** ~15 lines of JS in `live-updates.js` (or a new small file) that:
1. Listens for `htmx:afterSwap` on `#app-handler-stats`
2. Reads each `<span>` with a `data-listener-id` attribute
3. Finds the matching handler row by `#handler-{id}`
4. Updates the invocation count text, failed count, avg duration, and status dot class

**Changes to morph targets:**
- REMOVE `data-live-on-app` from `#app-handlers` and `#app-jobs` (handler/job lists). These no longer morph on WS events. Counts stay fresh via the 5s poll. Structure updates require page reload.
- KEEP `data-live-on-app` on health strip, dashboard grid, dashboard errors — these have no interactive state and morph safely.

**Status dot update:** The dot class (`ht-item-row__dot--success/danger/neutral`) is currently rendered as a static Jinja class. The JS updater will compute the class from the polled data and set it directly: `dot.className = 'ht-item-row__dot ht-item-row__dot--' + dotClass`.

### 3. Wire Typed Models

- `get_global_summary()` → return `GlobalSummary | None`
- `get_current_session_summary()` → return `SessionSummary | None`

**Fresh install edge case:** When SQL returns no rows, return `GlobalSummary` with zero-valued `ListenerGlobalStats(total_listeners=0, ...)` and `JobGlobalStats(total_jobs=0, ...)`. Template uses attribute access — no `.get()` fallbacks.

**Nullable fields:** Audit `SessionSummary` fields against DB schema. `last_heartbeat_at` may be NULL for new sessions — model must use `float | None`.

Update `dashboard.html` to use attribute access.

### 4. Centralize Health Thresholds

Add to `context.py`:

```python
def classify_error_rate(rate: float) -> str:
    if rate < 5: return "good"
    if rate < 10: return "warn"
    return "bad"

def classify_health_bar(success_rate: float) -> str:
    if success_rate == 100: return "excellent"
    if success_rate > 95: return "good"
    if success_rate > 90: return "warning"
    return "critical"
```

Register as Jinja2 template globals. Update all templates to use them.

### 5. Fix Apps Page/Partial Divergence

Use server-side filtering from the start:
- `manifest_list.html` renders rows unconditionally (server filters via `?status=`)
- Tab clicks update `data-live-on-app` URL dynamically via `x-bind` to include `?status=` param
- `live-updates.js` re-reads the URL attribute at fire time (not enqueue time) to pick up tab changes within the debounce window

## Non-Goals

- CDN vendoring (deferred to issue)
- CSS file splitting
- Error feed sorting
- View model layer
- New WS event types for telemetry
- Alpine.morph or alpine-morph extension (rejected after 3 rounds of critique)

## Impact

### Files modified

- `src/hassette/core/telemetry_query_service.py` — add `get_all_app_summaries()`, wire typed models
- `src/hassette/core/telemetry_models.py` — add `AppHealthSummary`, audit nullable fields on `SessionSummary`
- `src/hassette/web/ui/context.py` — simplify `compute_app_grid_health()`, add threshold functions
- `src/hassette/web/ui/router.py` — use typed models, register threshold globals
- `src/hassette/web/ui/partials.py` — use batch query for dashboard grid
- `src/hassette/web/templates/pages/app_detail.html` — remove `data-live-on-app` from handler/job lists
- `src/hassette/web/templates/pages/dashboard.html` — use attribute access, threshold functions
- `src/hassette/web/templates/pages/apps.html` — dynamic `data-live-on-app` URL with `x-bind`
- `src/hassette/web/templates/partials/manifest_list.html` — remove Alpine directives, render all rows
- `src/hassette/web/templates/partials/app_health_strip.html` — use threshold functions
- `src/hassette/web/templates/partials/dashboard_app_grid.html` — use threshold functions
- `src/hassette/web/static/js/live-updates.js` — add stats-to-DOM updater on `htmx:afterSwap`, re-read URL at fire time
- `tests/` — integration tests for batch query, E2E for polling updater
