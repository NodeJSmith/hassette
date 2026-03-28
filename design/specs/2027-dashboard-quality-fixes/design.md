# Design: Dashboard Quality Fixes

**Date:** 2026-03-27
**Status:** approved
**Spec:** design/specs/2027-dashboard-quality-fixes/spec.md
**Research:** /tmp/claude-mine-design-research-Xv3A2t/brief.md

## Problem

The dashboard has four quality gaps documented in spec 2027 (issues 443, 444, 445, 447). The app grid shows instance-0-only telemetry while the KPI strip already shows all-instance data. Database failures silently return zeroed data. The legacy `/healthz` endpoint is the only one returning proper status codes for Docker health checks, but it bypasses serialization. Log truncation detection fires once and never updates.

## Non-Goals

- Per-instance breakdown in the app detail view
- Deduplicating handler/job registration counts across instances (follow-up issue)
- Making all log rows always expandable
- Fixing `get_global_summary()` handler count inflation (KPI strip shows total registrations across all instances, not unique handlers — pre-existing, out of scope, tracked by follow-up issue)

## Architecture

### 1. Telemetry Aggregation (FR-1, FR-8)

**Approach: Separate queries for registration counts vs activity counts.**

`get_all_app_summaries()` in `src/hassette/core/telemetry_query_service.py` currently runs two queries (listener + job), each with `WHERE instance_index = 0`. Split each into two queries:

- **Registration query** (handler_count / job_count): Retains `WHERE instance_index = 0`, grouped by `app_key`. Returns the structural shape of the app.
- **Activity query** (invocations, errors, executions, duration): Removes the `instance_index` filter entirely, grouped by `app_key`. Aggregates across all instances.

The method merges results by `app_key` before returning `dict[str, AppHealthSummary]`. For the session-scoped variants, both queries additionally filter by `session_id`.

This doubles the query count from 2 to 4 (or 4 to 8 counting session variants), but each query is simpler and the intent is explicit. The registration query uses the composite index on `listeners(app_key, instance_index)`. The activity query joins through `handler_invocations` via the existing `idx_hi_listener_time(listener_id, execution_start_ts)` index, which covers the join column. Full-table aggregation across all instances is acceptable at current scale (~thousands of rows). Data retention/pruning bounds the growth.

**Duration averages**: `AVG(hi.duration_ms)` in the activity query computes a correctly weighted average across all instances' invocations. No special handling needed — SQL AVG over raw rows is already count-weighted. The `avg_duration_ms` field reflects handler invocation durations only (not job executions), unchanged from current behavior.

**Files changed**:
- `src/hassette/core/telemetry_query_service.py` — `get_all_app_summaries()` method rewrite

### 2. Degraded Response Flag (FR-2, FR-3)

In `src/hassette/web/routes/telemetry.py`, widen each `except sqlite3.Error` block to `except (sqlite3.Error, OSError, ValueError)`. Log `ValueError` at WARNING level (not INFO like the existing sqlite3.Error catches) to preserve the lifecycle signal for developers. Extract the exception tuple into a shared constant (e.g., `DB_ERRORS = (sqlite3.Error, OSError, ValueError)`) to keep the dashboard endpoints and status endpoint in sync.

**Rationale for catching ValueError**: aiosqlite raises `ValueError("Connection is closed")` during shutdown races when the database connection is closed before in-flight queries complete. This is a normal operational scenario, not a programming error. Operators should see a degraded response rather than a 500 during restart. The WARNING log ensures the lifecycle issue is still visible to developers.

**No per-endpoint degraded fields**: The dashboard response models (`DashboardKpisResponse`, `DashboardAppGridResponse`, `DashboardErrorsResponse`) do not get a `degraded` field. The frontend reads degraded state solely from the `/api/telemetry/status` poller (Section 3). Adding per-endpoint flags would create two sources of truth with no frontend consumer — YAGNI.

**Files changed**:
- `src/hassette/web/routes/telemetry.py` — three except blocks widened, shared exception constant

### 3. Telemetry Degraded Indicator in Status Bar (FR-4)

**Approach: Dedicated status endpoint with app-shell poller. Single source of truth.**

Add a `/api/telemetry/status` endpoint to `src/hassette/web/routes/telemetry.py` that performs a representative database health check — a lightweight query against the same tables the dashboard uses (e.g., a simple `SELECT COUNT(*) FROM listeners` or similar), not just `SELECT 1`. This ensures the status endpoint reflects actual query health, not just database connectivity. Returns `{"degraded": false}` on success, `{"degraded": true}` on database error. Catches the same exception set as the dashboard endpoints (`sqlite3.Error`, `OSError`, `ValueError`).

This endpoint serves as a **public API** — useful for external tools like Home Assistant, Homepage, Glances, or any monitoring dashboard that wants to check hassette's telemetry health.

**Single source of truth**: The frontend reads degraded state **only** from the poller signal. Dashboard response models have no `degraded` field (YAGNI — no frontend consumer). One writer (poller), one reader (status bar), no divergence.

**Frontend signal propagation**:
1. Add `telemetryDegraded: Signal<boolean>` to `AppState` in `frontend/src/state/create-app-state.ts`, initialized to `false`.
2. Create a `useTelemetryHealth` hook in `frontend/src/hooks/use-telemetry-health.ts` that polls `/api/telemetry/status` every 30 seconds with exponential backoff on consecutive failures (30s → 60s → 120s cap). Reset to 30s on success. On page navigation (route change), poll immediately and reset backoff — this ensures the operator sees current status when actively checking. On fetch failure (network error, server unreachable), set `telemetryDegraded = true` — a failed health check is itself evidence of degradation. Wire this hook in `app.tsx` so it runs regardless of which page is active.
3. The status bar in `frontend/src/components/layout/status-bar.tsx` reads `telemetryDegraded` alongside `connection` and renders a degraded indicator (e.g., amber dot with "DB degraded" label) when true. When both WebSocket is disconnected AND telemetry is degraded, "Disconnected" takes visual precedence since WS-down implies stale everything.

**Lifecycle**: The poller starts when the app mounts and stops on unmount. It runs regardless of which page is active, so the status bar always reflects current telemetry health.

**Response model**: `TelemetryStatusResponse` in `models.py` with a single `degraded: bool` field.

**Files changed**:
- `src/hassette/web/routes/telemetry.py` — new `/telemetry/status` endpoint
- `src/hassette/web/models.py` — `TelemetryStatusResponse`
- `frontend/src/api/endpoints.ts` — `getTelemetryStatus()` function + type
- `frontend/src/hooks/use-telemetry-health.ts` — new poller hook with backoff
- `frontend/src/state/create-app-state.ts` — `telemetryDegraded` signal
- `frontend/src/app.tsx` — wire poller hook
- `frontend/src/components/layout/status-bar.tsx` — degraded indicator rendering

### 4. Health Endpoint Consolidation (FR-4, FR-5, FR-6)

**Remove `/healthz`**: Delete the endpoint function from `src/hassette/web/routes/health.py`.

**Add 503 to `/health`**: Use FastAPI's `Response` parameter to set the status code while preserving Pydantic serialization for both paths:

```python
@router.get(
    "/health",
    response_model=SystemStatusResponse,
    responses={503: {"model": SystemStatusResponse}},
)
async def get_health(runtime: RuntimeDep, response: Response) -> SystemStatusResponse:
    status_data = runtime.get_system_status()
    if status_data.status != "ok":
        response.status_code = 503
    return status_data
```

This returns 503 for both `"degraded"` and `"starting"` states. The response body is always `SystemStatusResponse` JSON serialized through Pydantic regardless of status code. This is the idiomatic FastAPI pattern — no `JSONResponse` bypass needed.

**Update references**: Replace `/healthz` with `/health` in:
- `examples/docker-compose.yml`
- `docs/pages/getting-started/docker/snippets/docker-compose.yml`
- `docs/pages/getting-started/docker/snippets/full-docker-compose.yml`
- `docs/pages/getting-started/docker/troubleshooting.md` (3 references)

**Regenerate OpenAPI**: Run `scripts/export_schemas.py` to update `frontend/openapi.json`. The `/healthz` path will disappear and `/health` will gain the 503 response definition.

**Files changed**:
- `src/hassette/web/routes/health.py` — remove healthz, modify health
- `examples/docker-compose.yml`
- `docs/pages/getting-started/docker/snippets/docker-compose.yml`
- `docs/pages/getting-started/docker/snippets/full-docker-compose.yml`
- `docs/pages/getting-started/docker/troubleshooting.md`
- `frontend/openapi.json` (regenerated)

### 5. Reactive Truncation Detection (FR-7)

**Approach: Single ResizeObserver + document.fonts.ready.**

Replace the `checkTruncation` ref callback in `frontend/src/components/shared/log-table.tsx` with two distinct trigger paths that share one recheck function:

1. **A `recheckTruncation()` function** that:
   - Queries all `.ht-log-message__text` elements within the table
   - Builds a new `Set<string>` of row keys where `scrollWidth > clientWidth`
   - Compares to the current `truncatedRows` set (size first, then contents)
   - Only updates the signal if the set changed
   - Note: expanded rows have `text-overflow: ellipsis` removed by CSS, so `scrollWidth === clientWidth` for them. The `|| isExpanded` guard in the render path (`canExpand = truncatedRows.value.has(rowKey) || isExpanded`) is load-bearing — it keeps expanded rows collapsible even when `recheckTruncation()` doesn't include them. This must be documented with a code comment.

2. **Trigger path A — Viewport resize**: A single `ResizeObserver` created in a mount-only `useEffect` (empty dependency array). Observes individual `.ht-log-message__text` elements rather than the scroll container, since the scroll container may not resize when the viewport changes (fixed dimensions, overflow clipping). The observer callback calls `recheckTruncation()`. Cleanup disconnects the observer on unmount.

3. **Trigger path B — Data changes**: A separate `useEffect` with a dependency on the visible entry count (e.g., `sorted.length`) that: (a) calls `recheckTruncation()` after render (wrapped in `requestAnimationFrame` to ensure layout is complete), and (b) observes any new `.ht-log-message__text` elements that weren't in the DOM at mount time so they participate in subsequent viewport resizes. This handles new log entries arriving and filter/sort changes.

4. **Font load detection**: On mount, `document.fonts.ready.then(() => recheckTruncation())` triggers one re-evaluation after all fonts have loaded.

**Row key mapping**: The existing `checkTruncation(key)` ref callback knows the row key because it's a closure. The new approach needs a way to map DOM elements back to row keys. Use a `data-row-key` attribute on each `.ht-log-message__text` element, then read it in `recheckTruncation()`.

**Files changed**:
- `frontend/src/components/shared/log-table.tsx` — replace truncation detection system

## Alternatives Considered

### Conditional aggregation SQL (rejected)

Instead of separate queries, use `COUNT(DISTINCT CASE WHEN instance_index = 0 THEN l.id END)` within the existing query structure. Rejected: makes the SQL harder to read and harder to modify for the eventual handler deduplication follow-up. Separate queries are simpler even though there are more round trips.

### Dashboard-driven degraded signal (rejected)

Have dashboard.tsx read the degraded flag from its own API responses and write `appState.telemetryDegraded`. Rejected: the dashboard page is rarely visited, so the signal would almost always be stale. A dedicated status endpoint provides always-current data and serves as a public API for external tools.

### Calling all dashboard endpoints from the poller (rejected)

Poll all three dashboard endpoints every 30s to derive degraded state. Rejected: wasteful — the dashboard queries are heavier than needed for a health check. A dedicated lightweight status endpoint is more efficient.

### SELECT 1 for status endpoint (rejected)

Use `SELECT 1` as the telemetry status health check. Rejected: `SELECT 1` tests database connectivity but not query health. A corrupt index or schema mismatch would pass `SELECT 1` but fail real queries, creating false-green status. The status endpoint must hit the same tables the dashboard queries use.

### Always-expandable rows for log table (rejected per spec)

Remove truncation detection entirely and let every row be expandable. Simpler but shows expand affordance on short messages. Rejected by spec non-goal.

## Test Strategy

### Unit / Integration Tests

**Telemetry aggregation** (`tests/integration/test_telemetry_query_service.py`):
- New test: multi-instance app with activity distributed across instances 0, 1, 2. Verify `total_invocations` sums across all, `handler_count` reflects instance 0 only.
- New test: single-instance app produces equivalent results (within float tolerance) to current behavior.
- New test: session-scoped variant aggregates correctly across instances within a session.
- Existing tests must pass unchanged.

**Degraded flag** (`tests/integration/test_web_api.py`):
- Existing `sqlite3.Error` fallback tests updated to assert `degraded=True` on the response.
- New test: successful response has `degraded=False`.
- New test: `OSError` triggers degraded response.
- New test: `ValueError` (connection closed) triggers degraded response and logs at WARNING.

**Telemetry status endpoint** (`tests/integration/test_web_api.py`):
- New test: `/api/telemetry/status` returns `degraded: false` when DB is healthy.
- New test: `/api/telemetry/status` returns `degraded: true` when DB is unavailable.

**Health endpoint** (`tests/integration/test_web_api.py`):
- Migrate existing `/healthz` tests to `/health`.
- New test: `/health` returns 200 with `status: "ok"` when healthy.
- New test: `/health` returns 503 with `status: "degraded"` when WebSocket is disconnected.
- New test: `/health` returns 503 with `status: "starting"` during startup.
- New test: `/healthz` returns 404.

### E2E Tests

**Truncation detection** (`tests/e2e/`):
- Test: log messages truncated at narrow viewport show expand affordance.
- Test: widening viewport removes expand affordance from messages that now fit.
- Test: expand affordance appears after font load (if testable via Playwright).

**Status bar degraded indicator**: Difficult to E2E test (requires simulating DB failure). Cover via integration tests on the backend endpoint; frontend rendering is verified visually.

### Manual Verification

- Docker health check behavior with updated docker-compose (503 on degraded, 200 on ok).
- Status bar degraded indicator appearance/disappearance.

## Open Questions

- **Signal propagation architecture**: Resolved — dedicated `/api/telemetry/status` endpoint with representative query, polled by `useTelemetryHealth` hook in app shell. Single source of truth for degraded state.
- **CHANGELOG entry for `/healthz` removal**: Should be a migration guide with before/after docker-compose snippets, not just a line item. Decision deferred to implementation.
- **ResizeObserver throttling**: Browser's native batching should suffice. If performance issues arise during testing, add `requestAnimationFrame` gating. Decision deferred to implementation.
- **Status endpoint query choice**: The representative query must exercise the same join path the dashboard uses (listeners → handler_invocations) to catch index corruption or schema issues that a single-table read would miss. E.g., `SELECT COUNT(*) FROM listeners l LEFT JOIN handler_invocations hi ON hi.listener_id = l.id LIMIT 1`. Exact query chosen during implementation, but it must touch both tables via the join.
- A follow-up issue should be filed for proper deduplication of handler/job registration counts across instances (from spec open questions).

## Impact

**Backend files** (~4):
- `src/hassette/core/telemetry_query_service.py` — query restructure (highest complexity)
- `src/hassette/web/models.py` — TelemetryStatusResponse
- `src/hassette/web/routes/telemetry.py` — 3 catch block changes + new status endpoint
- `src/hassette/web/routes/health.py` — endpoint removal + 503 behavior

**Frontend files** (~7):
- `frontend/src/api/endpoints.ts` — type updates + new endpoint function
- `frontend/src/hooks/use-telemetry-health.ts` — new poller hook with backoff
- `frontend/src/state/create-app-state.ts` — new signal
- `frontend/src/app.tsx` — wire poller hook
- `frontend/src/components/layout/status-bar.tsx` — degraded indicator
- `frontend/src/components/shared/log-table.tsx` — ResizeObserver rewrite
- `frontend/src/pages/dashboard.tsx` — no changes needed (poller handles status bar)

**Documentation / config** (~5):
- 3 docker-compose files
- `docs/pages/getting-started/docker/troubleshooting.md`
- `frontend/openapi.json` (regenerated)

**Tests** (~2-3):
- `tests/integration/test_telemetry_query_service.py` — new multi-instance tests
- `tests/integration/test_web_api.py` — updated + new tests
- `tests/e2e/` — new truncation tests

**Blast radius**: Moderate. Changes span backend queries, API models, frontend state, and documentation. Each change is isolated to its own area with minimal cross-cutting. The telemetry SQL restructure and the ResizeObserver lifecycle are the highest-risk areas.

**Dependencies**: No new libraries or packages needed.
