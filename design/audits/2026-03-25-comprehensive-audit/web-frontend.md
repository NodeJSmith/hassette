# Web & Frontend Layer Audit — Hassette

**Auditor:** Frontend Developer Agent (Opus 4.6)
**Date:** 2025-03-25
**Scope:** Backend web layer (`src/hassette/web/`), Preact SPA (`frontend/`), API contract, WebSocket pipeline, build system

---

## Summary

The Hassette web layer is well-architected for a project of this scope. The backend is cleanly organized into domain-specific route modules with shared dependency injection and typed Pydantic response models. The Preact SPA is minimal and purposeful, using signals for state management, a clean hook abstraction for data fetching, and a well-considered WebSocket reconnection strategy.

**Strengths:**
- Consistent dependency injection via `Annotated[..., Depends()]` aliases
- All API responses have Pydantic `response_model` declarations
- Frontend signal-based state avoids unnecessary re-renders
- WebSocket handling is robust: exponential backoff, handshake timeout, clean disconnect detection
- Excellent CSS token discipline: no raw hex values in `global.css`, full dark/light theming
- Good test coverage: 14 frontend test files covering hooks, components, state, and utils
- `prefers-reduced-motion` media query respected
- localStorage access is fully wrapped with try/catch and key prefixing

**Areas of concern:** 5 findings, none critical. The main risks are around the SPA catch-all path traversal check, a hardcoded stub endpoint, and some missing error handling on telemetry routes.

---

## Findings

### 1. SPA Catch-All Path Traversal Check Is Insufficient -- HIGH

**Location:** `src/hassette/web/app.py:88-90`

**Description:**
The SPA catch-all route serves arbitrary files from the `_SPA_DIR` directory. The path traversal check uses:

```python
candidate = _SPA_DIR / path
if candidate.is_file() and _SPA_DIR in candidate.resolve().parents:
    return FileResponse(str(candidate))
```

The check `_SPA_DIR in candidate.resolve().parents` verifies the resolved path has `_SPA_DIR` as a parent, which is correct in principle. However, `Path.parents` does not include the path itself -- if `path` resolves to exactly `_SPA_DIR` (e.g., via a symlink), this check would fail. More importantly, `_SPA_DIR / path` can resolve `..` sequences before `.resolve()` strips them, and the `is_file()` check runs on the unresolved path on some platforms.

The real issue is that `_SPA_DIR in candidate.resolve().parents` will fail if `_SPA_DIR` itself is a symlink (because `resolve()` follows symlinks but the comparison uses the unresolved `_SPA_DIR`). Additionally, the check does not account for `_SPA_DIR` being the resolved path itself (only parents are checked, not identity).

**Recommendation:**
Use a stricter containment check that resolves both sides and includes identity:

```python
resolved = candidate.resolve()
spa_resolved = _SPA_DIR.resolve()
if resolved.is_file() and (resolved == spa_resolved or spa_resolved in resolved.parents):
    return FileResponse(str(resolved))
```

Alternatively, use `resolved.is_relative_to(spa_resolved)` (Python 3.9+), which is the idiomatic approach and handles all edge cases.

---

### 2. `/api/bus/metrics` Returns Hardcoded Zeros -- HIGH

**Location:** `src/hassette/web/routes/bus.py:32-41`

**Description:**
The `get_bus_metrics_summary` endpoint returns a response with all fields set to zero and does not accept or use any dependencies:

```python
@router.get("/bus/metrics", response_model=BusMetricsSummaryResponse)
async def get_bus_metrics_summary() -> BusMetricsSummaryResponse:
    return BusMetricsSummaryResponse(
        total_listeners=0, total_invocations=0,
        total_successful=0, total_failed=0,
        total_di_failures=0, total_cancelled=0,
    )
```

This is clearly a stub. It appears in the OpenAPI docs and would confuse any API consumer. The SPA does not appear to call this endpoint, but it's still part of the public API surface.

**Recommendation:**
Either implement the endpoint by aggregating data from the telemetry service (similar to how `dashboard_kpis` works), or remove it from the router until it's functional. If keeping it as a stub, add a deprecation notice or exclude it from OpenAPI docs via `include_in_schema=False`.

---

### 3. Telemetry Routes Lack Error Handling for DB Failures -- MEDIUM

**Location:** `src/hassette/web/routes/telemetry.py:54-141`

**Description:**
Most telemetry endpoints (`app_health`, `app_listeners`, `app_jobs`, `handler_invocations`, `job_executions`) call the `TelemetryQueryService` directly without try/except. If the SQLite telemetry database is locked, corrupt, or experiencing I/O errors, these endpoints will raise unhandled `500` errors with raw tracebacks in the response.

The `dashboard_app_grid` endpoint at line 181 does handle this gracefully:

```python
try:
    summaries = await telemetry.get_all_app_summaries(session_id=session_id)
except Exception:
    logger.warning("Failed to fetch app summaries for dashboard grid", exc_info=True)
    summaries = {}
```

But the per-app telemetry endpoints do not follow this pattern.

**Recommendation:**
Add consistent error handling across all telemetry endpoints. Either:
- Wrap each in try/except and return a 503 with a structured error message
- Add a FastAPI exception handler for telemetry service exceptions
- Use a middleware or dependency that catches DB errors centrally

---

### 4. Frontend Type Definitions Are Manually Maintained -- MEDIUM

**Location:** `frontend/src/api/endpoints.ts`, `frontend/src/api/ws-types.ts`

**Description:**
The frontend defines all API response types manually (e.g., `AppManifest`, `ListenerData`, `DashboardKpis`, `WsServerMessage`). The `package.json` has a `types` script that uses `openapi-typescript` to generate types from `openapi.json`, but the generated file (`src/api/types.ts`) is not imported anywhere. Instead, all endpoint functions use hand-written interfaces.

The `ws-types.ts` header mentions "A CI conformance test validates these match the exported ws-schema.json," which is good, but the REST API types have no such validation. This means:
- If a backend model gains a new field, the frontend won't know about it
- If a field type changes (e.g., `int` to `float`), there's no compile-time or CI check
- The `openapi-typescript` tooling is set up but unused

**Recommendation:**
Either:
1. Import and use the generated `types.ts` file from `openapi-typescript`, wrapping endpoint functions with those types
2. Add a CI step that compares the hand-written types against the OpenAPI spec (similar to the WS schema conformance test)
3. At minimum, add a comment documenting why manual types are preferred and link to the backend model locations

---

### 5. `healthz` Endpoint Bypasses Pydantic Serialization -- MEDIUM

**Location:** `src/hassette/web/routes/health.py:16-32`

**Description:**
The `/api/healthz` endpoint constructs raw JSON strings instead of using Pydantic models:

```python
return Response(
    content='{"status":"ok","ws":"connected"}',
    media_type="application/json",
    status_code=200,
)
```

This is noted as "backwards-compatible" in the docstring. However:
- It bypasses FastAPI's serialization and validation pipeline
- It won't appear correctly in OpenAPI docs (no `response_model`)
- If the response shape needs to change, it's easy to introduce JSON syntax errors in the string literal

**Recommendation:**
Create a small Pydantic model (e.g., `HealthzResponse`) and return it normally. If exact backwards compatibility is critical, verify the field names match. This is low-risk to change since it's a health check endpoint.

---

### 6. LogTable Component Is 295 Lines with Mixed Concerns -- MEDIUM

**Location:** `frontend/src/components/shared/log-table.tsx:1-295`

**Description:**
The `LogTable` component handles filtering (level, app, search text), sorting (4 columns with direction toggling), live-pause detection, initial data fetching, WebSocket entry merging with seq-based deduplication, row expansion state, and table rendering. At 295 lines it's within the project's 400-line guideline, but the single function body mixes data fetching, filtering logic, sort logic, and UI rendering.

The component also accesses `reconnectVersion.value` directly in the render body (line 70) to trigger refetches via `useEffect`, which is an unusual pattern that could confuse maintainers -- most refetch-on-reconnect behavior in the codebase goes through `useApi`'s built-in `reconnectVersion` tracking.

**Recommendation:**
Extract the filtering and sorting logic into a custom hook (e.g., `useLogFiltering`) that returns the sorted/filtered entries and the filter controls. This would:
- Make the component easier to test (filter logic can be tested independently)
- Reduce the cognitive load of reading the component
- Keep the render function focused on layout

---

### 7. No Rate Limiting on App Mutation Endpoints -- MEDIUM

**Location:** `src/hassette/web/routes/apps.py:34-61`

**Description:**
The `start_app`, `stop_app`, and `reload_app` endpoints accept POST requests without any rate limiting, authentication, or CSRF protection. While the CORS middleware restricts cross-origin requests, same-origin requests from any browser tab or script can trigger app restarts.

For a home automation framework that may be exposed on a local network, rapid-fire start/stop/reload cycles could destabilize the system.

**Recommendation:**
Add one or more of:
- A simple in-memory rate limiter (e.g., 1 action per app per 5 seconds)
- An optional API key header for mutation endpoints
- CSRF token validation for browser-originated requests

This is medium severity because the app is typically run on a trusted local network, but it's worth addressing before any addon/public deployment.

---

### 8. CORS Configuration Allows Credentials with Configurable Origins -- LOW

**Location:** `src/hassette/web/app.py:54-59`

**Description:**
The CORS middleware is configured with `allow_credentials=True` and origins pulled from `hassette.config.web_api_cors_origins`. If a user configures `["*"]` as the origin list, Starlette's CORS middleware will reject it (credentials + wildcard is invalid per spec), but the error would be confusing. The current code doesn't validate or warn about this combination.

**Recommendation:**
Add a startup validation that warns if `web_api_cors_origins` contains `"*"` while credentials are enabled. Alternatively, document the restriction clearly.

---

### 9. Frontend Error Boundary Resets on Location Change Only -- LOW

**Location:** `frontend/src/components/layout/error-boundary.tsx:12-14`

**Description:**
The `ErrorBoundary` resets errors when `resetKey` (which is the current location) changes:

```tsx
useEffect(() => {
    if (error) resetError();
}, [resetKey, resetError]);
```

This means if a render error occurs on a page and the user clicks the same nav link (which doesn't change the location), the error state persists. The only way to recover is to navigate to a different page and back, or click the explicit "Retry" button.

This is minor because the "Retry" button covers it, but it could confuse users who expect clicking the same nav link to retry.

**Recommendation:**
Consider adding a retry counter or timestamp to the reset key, or make the nav items always trigger a re-render even for the current route.

---

### 10. Missing `error` Dependency in ErrorBoundary useEffect -- LOW

**Location:** `frontend/src/components/layout/error-boundary.tsx:12-14`

**Description:**
The `useEffect` that auto-resets the error boundary on route change reads `error` inside the callback but does not include it in the dependency array:

```tsx
useEffect(() => {
    if (error) resetError();
}, [resetKey, resetError]);
```

If `error` becomes truthy between renders without `resetKey` changing, the effect won't fire. In practice this is benign because `resetKey` is the primary trigger, but it's technically a stale-closure risk and would trigger the `react-hooks/exhaustive-deps` lint rule.

**Recommendation:**
Add `error` to the dependency array: `[error, resetKey, resetError]`. This is safe because `resetError()` clears the error state, preventing infinite loops.

---

### 11. `DashboardErrorsResponse.errors` Uses Inline Union Instead of Discriminated Type -- LOW

**Location:** `src/hassette/web/models.py:340-341`

**Description:**
The `DashboardErrorsResponse` model uses a plain inline union:

```python
errors: list[HandlerErrorEntry | JobErrorEntry]
```

Meanwhile, the standalone `RecentErrorEntry` type at line 242 uses a properly discriminated union:

```python
RecentErrorEntry = Annotated[HandlerErrorEntry | JobErrorEntry, Field(discriminator="kind")]
```

The `DashboardErrorsResponse` should reference `RecentErrorEntry` instead of re-stating the union, ensuring consistent discrimination behavior in the OpenAPI schema.

**Recommendation:**
Change to `errors: list[RecentErrorEntry]`.

---

### 12. Inline `style` Attributes in Several Components -- LOW

**Location:** Multiple frontend components

**Description:**
Several components use inline `style` attributes for layout:
- `error-feed.tsx:50` -- `style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block"`
- `manifest-row.tsx:61` -- `style={{ paddingLeft: "2rem" }}`
- `manifest-row.tsx:45` -- `style={{ marginLeft: "4px" }}`
- `log-table.tsx:205` -- `style={{ maxHeight: "600px", overflow: "auto" }}`
- `log-table.tsx:207` -- `style={{ position: "sticky", top: 0, background: "var(--ht-surface-sticky, var(--ht-bg))" }}`
- `not-found.tsx:3` -- `style={{ textAlign: "center", padding: "var(--ht-sp-10)" }}`
- `app-detail.tsx:80` -- `style={{ display: "inline-block" }}`

This contradicts the project's CSS architecture, which channels all styling through `ht-` prefixed classes referencing design tokens.

**Recommendation:**
Extract these into CSS classes in `global.css`. Some are one-off layout adjustments that could be utility classes (e.g., `ht-text-center`, `ht-pl-8`, `ht-truncate`).

---

### 13. Google Fonts Loaded from External CDN -- LOW

**Location:** `frontend/index.html:8-10`

**Description:**
The SPA loads DM Sans, JetBrains Mono, and Space Grotesk from Google Fonts via an external CDN link:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=..." rel="stylesheet" />
```

For a home automation UI that may run on an isolated local network (no internet access), this means fonts will fail to load and the UI will fall back to system fonts. The Vite config already has a `fonts` mount point (`_SPA_DIR / "fonts"`), suggesting self-hosted fonts were planned but not completed.

**Recommendation:**
Download the font files, place them in `frontend/public/fonts/`, and use `@font-face` declarations in `tokens.css`. This ensures the UI works fully offline, which is important for a Home Assistant addon deployment scenario.

---

### 14. Stale CLAUDE.md Documents htmx/Alpine.js Architecture -- LOW

**Location:** `src/hassette/web/CLAUDE.md`

**Description:**
The `CLAUDE.md` in the web directory extensively documents the old htmx/Alpine.js/Jinja2 template architecture (partials, macros, HTMX swaps, Alpine.js stores, idiomorph, live-updates.js). The codebase has migrated to a Preact SPA, but this documentation still references the legacy stack:

- Template directory layout with `base.html`, `macros/`, `pages/`, `partials/`
- Alpine.js component patterns (`logTable(config)`, `$store.ws`)
- HTMX partial loading patterns
- `live-updates.js` and `ws-handler.js`

This will confuse anyone (human or AI) using the CLAUDE.md for guidance.

**Recommendation:**
Rewrite the CLAUDE.md to document the Preact SPA architecture: component tree, state management via signals, data fetching via `useApi`, WebSocket integration, build pipeline, and CSS token system. Keep a brief "Legacy" section if the old templates still exist for reference, or remove it entirely if they've been deleted.

---

## Architecture Assessment

### Backend Web Layer -- Well Structured

The route organization by domain (`apps`, `bus`, `scheduler`, `telemetry`, `health`, etc.) is clean and scales well. The dependency injection system via `HassetteDep`, `RuntimeDep`, `TelemetryDep`, and `SchedulerDep` is consistent across all routes. The telemetry router correctly uses a sub-prefix (`/api/telemetry/...`) to namespace its endpoints.

The separation between `RuntimeQueryService` (live state) and `TelemetryQueryService` (historical DB queries) is a good architectural boundary that keeps the route handlers thin.

### Frontend -- Clean for Early Stage

The Preact SPA uses an effective minimal stack: Preact + Signals + wouter. No unnecessary dependencies. The `useApi` hook is well-designed with request deduplication (`requestIdRef`), lazy loading support, and automatic reconnection refetch. The `useDebouncedEffect` hook with `maxWaitMs` prevents starvation during rapid WebSocket updates -- a nuance that shows attention to real-world usage patterns.

The component tree is sensibly organized: `pages/` for route-level components, `components/layout/` for shell, `components/shared/` for reusable primitives, and domain-specific folders for `dashboard/`, `apps/`, and `app-detail/`.

### API Contract

The API is read-heavy and follows REST conventions well. All GET endpoints have `response_model` declarations. The mutation endpoints (`start`, `stop`, `reload`) return 202 with an `ActionResponse`, which correctly communicates async acceptance. The WebSocket protocol uses a clean `{type, data, timestamp}` envelope with a discriminated union, and the WS schema conformance test in CI is a strong practice.

### Build Pipeline

The Vite build outputs directly to `src/hassette/web/static/spa/`, which the Python app serves. The dev proxy setup in `vite.config.ts` correctly routes `/api/ws` before `/api` to handle WebSocket upgrades. The `openapi-typescript` tooling is available but not integrated into the workflow (see Finding 4).

---

## Severity Summary

| Severity | Count | Findings |
|----------|-------|----------|
| CRITICAL | 0 | -- |
| HIGH | 2 | #1 (path traversal), #2 (stub endpoint) |
| MEDIUM | 4 | #3 (telemetry error handling), #4 (manual types), #5 (healthz bypass), #6 (LogTable size), #7 (no rate limiting) |
| LOW | 7 | #8 (CORS), #9 (error boundary reset), #10 (missing dep), #11 (union type), #12 (inline styles), #13 (CDN fonts), #14 (stale docs) |
