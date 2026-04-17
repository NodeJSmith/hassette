---
feature_number: "2027"
feature_slug: "dashboard-quality-fixes"
status: "approved"
created: "2026-03-27T12:00:00Z"
issues: [443, 444, 445, 447]
---

# Spec: Dashboard Quality Fixes

## Problem Statement

The dashboard monitoring UI has four quality gaps that erode operator trust:

1. **Invisible multi-instance data** — The app grid query (`get_all_app_summaries`) hardcodes `instance_index = 0`, so apps running multiple instances only show metrics from instance 0. Operators see incomplete data without knowing it. Note: the KPI strip query (`get_global_summary`) already aggregates across all instances, creating a pre-existing inconsistency between the two dashboard sections.
2. **Silent database failures** — When the telemetry database is unavailable, dashboard endpoints return zeroed/empty responses indistinguishable from "healthy and empty." Operators cannot tell whether data is missing or the system is broken.
3. **Deprecated endpoint baggage** — A legacy health check endpoint bypasses the serialization pipeline and returns hardcoded JSON strings. It also provides the only health check that returns non-200 status codes on failure, which Docker health checks depend on.
4. **Stale truncation detection** — Log message overflow detection runs once at render time and never updates. After viewport resize or font loading, the expand affordance disappears or fails to appear, leaving operators unable to read full log messages.

## Goals

- Operators see accurate telemetry reflecting all app instances, not just instance 0.
- Operators can visually distinguish "no data" from "database unavailable" on the dashboard via the status bar (telemetry degraded indicator).
- The deprecated health check endpoint is removed, the canonical endpoint gains proper status code behavior, and all documentation references are updated.
- Log message truncation detection remains accurate after viewport resize, font loading, and data reflows.

## Non-Goals

- Per-instance telemetry breakdown in the app detail view (separate feature).
- Deduplicating handler/job registration counts across instances (separate follow-up issue to be filed).
- Making all log message rows always expandable regardless of truncation state.

## User Scenarios

### Operator: Monitoring a multi-instance deployment

- **Goal:** Verify that all app instances are healthy and processing events.
- **Context:** Checking the dashboard after scaling an app to 3 instances.

#### Viewing aggregated telemetry

1. **Opens the dashboard**
   - Sees: App grid with handler counts (from instance 0 as a representative), invocation totals, error rates, and job counts aggregated across all instances.
   - Decides: Whether any app needs attention based on aggregated health metrics.

### Operator: Diagnosing a database issue

- **Goal:** Understand why dashboard data looks empty.
- **Context:** The telemetry database is temporarily unavailable due to disk pressure or corruption.

#### Recognizing degraded state

1. **Opens the dashboard during a database outage**
   - Sees: The status bar shows a degraded telemetry indicator alongside the connection status, making it clear that data is unavailable rather than simply empty.
   - Decides: To investigate the database rather than assuming the system is idle.

### Operator: Configuring container health checks

- **Goal:** Set up health checks for a containerized deployment.
- **Context:** Writing or updating a docker-compose file.

#### Using the canonical health endpoint

1. **References documentation for health check configuration**
   - Sees: Documentation and examples pointing to the canonical health endpoint, which returns non-200 status codes when the system is degraded.

### Operator: Reading log messages on a resized viewport

- **Goal:** Expand truncated log messages to read full content.
- **Context:** Resized the browser window or navigated to the logs page after fonts finished loading.

#### Expanding a truncated message

1. **Scans the log table after resizing the viewport**
   - Sees: Expand affordance on messages that are truncated at the current viewport width. Messages that were previously truncated but now fit do not show the affordance.
   - Decides: Which message to expand based on visible preview text.

## Functional Requirements

1. **FR-1: Multi-instance telemetry aggregation** — The dashboard app grid must aggregate activity counts (invocation totals, error counts, execution totals, job error counts) and duration averages across all instances of each app, not just instance 0. Registration counts (handler_count, job_count) must continue to use instance 0 values as a representative of the app's structure. Only `get_all_app_summaries` is modified; `get_global_summary` already aggregates across all instances; `get_listener_summary` and `get_job_summary` remain parameterized by instance_index (app detail view, out of scope). Duration averages must be computed from raw invocation rows (weighted by count), not by averaging per-instance averages. The app grid's `avg_duration_ms` reflects handler invocation durations only (not job executions); this remains unchanged.

2. **FR-2: Telemetry status endpoint** — A dedicated endpoint must report whether the telemetry database is healthy or degraded. The health check must exercise the same database join paths used by dashboard queries (not just a connectivity check). The endpoint must catch database errors (`sqlite3.Error`, `OSError`, connection-closed errors from the database driver) and return a degraded response. `asyncio.CancelledError` must not be caught. Other exceptions indicate programming errors and should propagate as 500s. This endpoint serves as a public API for external monitoring tools.

3. **FR-3: Telemetry degraded indicator in status bar** — The status bar must display a telemetry degraded indicator when the telemetry status endpoint reports degradation. The indicator must clear automatically when the endpoint reports recovery. The frontend must poll the status endpoint regardless of which page is active so the indicator is always current. On fetch failure (network error, server unreachable), the indicator must show degraded state.

4. **FR-4: Remove legacy health endpoint** — The deprecated health check endpoint returning hardcoded JSON strings must be removed.

5. **FR-5: Canonical health endpoint status codes** — The canonical health endpoint must return HTTP 503 for any non-ok system status (degraded, starting), preserving the behavior that Docker health checks depend on. When the system is healthy (status ok), it must continue returning HTTP 200. Both 200 and 503 responses must return the same structured status data in the response body.

6. **FR-6: Update health check references** — All docker-compose files, documentation pages, examples, and generated API specifications (e.g., openapi.json) that reference the deprecated health check path must be updated to use the canonical health endpoint path.

7. **FR-7: Reactive truncation detection** — Log message overflow detection must re-evaluate when the viewport is resized, fonts finish loading, or data reflows. Messages that become truncated after initial render must gain the expand affordance; messages that are no longer truncated must lose it. A single ResizeObserver instance must be used for all visible rows, disconnected on component unmount. Font load completion must be detected via `document.fonts.ready`, not ResizeObserver alone. The truncatedRows set must be rebuilt on each re-evaluation (entries added and removed). Signal updates must be suppressed when the set is unchanged.

8. **FR-8: Existing single-instance behavior preserved** — For apps with only one instance (instance 0), telemetry aggregation must produce equivalent results to the current behavior.

## Edge Cases

1. **All instances have zero activity** — Aggregation returns zero counts, not null or missing entries. The app still appears in the grid.
2. **Database recovers mid-session** — Subsequent requests return `degraded: false` with real data. No sticky degraded state. Status bar indicator clears.
3. **Log table with no truncated messages** — No expand affordances shown. ResizeObserver must not cause unnecessary re-renders when no truncation state changes.
4. **Font swap completes before component mount** — Truncation detection at mount time is correct; ResizeObserver handles the case where it hasn't completed yet.
5. **Health check consumers using the old path** — Requests to the removed endpoint receive a 404. No redirect or deprecation header.

## Dependencies and Assumptions

- The telemetry database schema already stores `instance_index` per listener and scheduled job — no schema changes needed.
- The canonical health endpoint already exists and returns structured data suitable for health checks. Adding 503 behavior is a change to its contract.
- The frontend uses Preact Signals for reactive state management — ResizeObserver callbacks can update signals directly.
- Docker health checks tolerate a path change without requiring container recreation (standard docker-compose behavior on restart).
- The dashboard shows aggregated multi-instance totals while the app detail view provides per-instance drill-down. These are complementary granularity levels, not an inconsistency.
- `get_recent_errors` already returns errors from all instances (no `instance_index` filter). This fix resolves the pre-existing inconsistency between error feed totals and app grid error counts.

## Acceptance Criteria

1. Dashboard app grid shows correct aggregated activity totals (invocations, errors, executions) when an app runs multiple instances with activity distributed across them. Handler and job counts reflect instance 0 values.
2. The telemetry status endpoint returns healthy when the database is operational and degraded when the database is unavailable.
3. The status bar displays a telemetry degraded indicator when the status endpoint reports degradation.
4. The status bar degraded indicator clears when the status endpoint reports recovery.
5. The deprecated health check endpoint returns 404.
6. The canonical health endpoint returns 503 when the system status is non-ok (degraded or starting) and 200 when healthy. Both return structured status JSON.
7. All docker-compose files and documentation reference the canonical health endpoint.
8. Log message expand affordance appears correctly after browser window is narrowed (not truncated -> truncated).
9. Log message expand affordance disappears when a previously truncated message fits within the viewport after the window is widened (truncated -> not truncated).
10. Log message expand affordance appears correctly when fonts load after initial render.
11. Existing tests for single-instance telemetry continue to pass with equivalent values (delta < 0.001 for duration averages).
12. Health endpoint continues to return structured status JSON. The addition of 503 for non-ok states and removal of `/healthz` are intentional contract changes, not regressions.

## Open Questions

- A follow-up issue should be filed for proper deduplication of handler/job registration counts across instances (e.g., `COUNT(DISTINCT handler_method)` instead of using instance 0 as a proxy).
- **Signal propagation for FR-4**: The architecture for flowing the `degraded` flag from API responses to the status bar (app-wide signal vs dashboard-scoped state) is deferred to the design phase.
- **Terminology**: This spec uses "telemetry degraded" (FR-2/3/4, database unavailability) and "system degraded" (FR-6, WebSocket/health status) to describe independent failure modes. The design phase should ensure these are visually distinguishable.
