# Web Stack Audit — 2026-03-24

Systematic assessment of the Hassette web stack: backend (`src/hassette/web/`, core web services) and frontend (`frontend/` Preact SPA).

**Scope:** ~2,988 LOC backend, ~5,156 LOC frontend, 43 backend integration tests, 850+ lines of frontend tests.

## Critical (high impact, fix soon)

### 1. Hardcoded zero in dashboard KPI: avg_job_duration_ms always shows 0

`src/hassette/web/routes/telemetry.py:185` — Job duration KPI hardcoded to `0.0` instead of computed from job executions. The companion `avg_handler_duration_ms` on line 184 is computed correctly. Users see a permanently-zero metric, undermining trust in all dashboard metrics.

**Issue:** [#393](https://github.com/NodeJSmith/hassette/issues/393)

### 2. API contract drift: frontend ListenerData missing ~16 backend fields

`frontend/src/api/endpoints.ts:60-72` vs `src/hassette/web/models.py:301-327` — Backend `ListenerWithSummary` returns 27 fields (including `di_failures`, `debounce`, `throttle`, `predicate_description`, `min/max_duration_ms`), but frontend `ListenerData` only declares 11. Advanced handler metrics are silently discarded. Related to #388 (OpenAPI codegen) but the specific data loss is worth tracking separately.

**Issue:** [#394](https://github.com/NodeJSmith/hassette/issues/394)

## Concerning (accumulating risk)

### 3. Dead code: compute_app_grid_health() never called

`src/hassette/web/telemetry_helpers.py:153-181` — This function duplicates logic inlined in `routes/telemetry.py:192-237`. Grep confirms zero imports. Left behind during a refactor where the route was changed to build `DashboardAppGridResponse` directly.

**Issue:** [#395](https://github.com/NodeJSmith/hassette/issues/395)

### 4. Stub endpoint /scheduler/history returns empty array

`src/hassette/web/routes/scheduler.py:52-59` — Exposed in OpenAPI, accepts `limit`/`app_key`/`instance_index` params (all `# noqa: ARG001`), always returns `[]`. Needs either implementation via `TelemetryQueryService.get_job_executions()` or removal.

**Issue:** [#396](https://github.com/NodeJSmith/hassette/issues/396)

### 5. Frontend error responses never parsed

`frontend/src/api/client.ts:26-27` — Throws `ApiError(response.status, response.statusText)` without reading the response body. FastAPI's `HTTPException` returns `{"detail": "App foo not found"}` but users see generic "Not Found" instead.

**Issue:** [#397](https://github.com/NodeJSmith/hassette/issues/397)

### 6. No schema validation tests in CI + stale ws-schema.json

`frontend/ws-schema.json` and `frontend/openapi.json` have no CI test validating they match backend models. The ws-schema.json has already drifted: `ConnectedWsMessage` is missing `timestamp` in its `required` array (the Pydantic model and frontend types both have it). The `ws-types.ts` header claims "A CI conformance test validates these" — that test doesn't exist.

**Issue:** [#398](https://github.com/NodeJSmith/hassette/issues/398)

### 7. Broad except Exception in telemetry (silent dashboard failures)

`src/hassette/web/routes/telemetry.py:202` — Database errors, timeouts, and coding mistakes all silently return empty summaries with no user-visible error.

**Already covered by:** [#292](https://github.com/NodeJSmith/hassette/issues/292)

### 8. Component test coverage: 0/25 frontend components tested

Hooks and utilities have excellent coverage (100%), but no component-level tests exist. Complex components like `LogTable` (186 lines), `ManifestList` (102 lines), and `ActionButtons` (77 lines) contain significant logic only tested through E2E flows.

**Issue:** [#399](https://github.com/NodeJSmith/hassette/issues/399)

### 9. Silent WebSocket message drops for slow clients

`src/hassette/core/runtime_query_service.py:318-328` — Queue saturation logged at DEBUG only, no metrics counter, no backpressure. Operators can't tell when clients are falling behind.

**Issue:** [#400](https://github.com/NodeJSmith/hassette/issues/400)

### 10. Missing response_model on mutation endpoints

`routes/apps.py` (start/stop/reload), `routes/services.py`, `routes/config.py` return bare dicts without response models. OpenAPI shows `object` instead of specific fields.

**Issue:** [#401](https://github.com/NodeJSmith/hassette/issues/401)

### 11. Return type annotation mismatch on /bus/listeners

`src/hassette/web/routes/bus.py:15-21` — `response_model=list[ListenerMetricsResponse]` but return annotation is `-> list[ListenerSummary]`. Not a runtime bug (FastAPI uses response_model for serialization) but confuses type checkers.

**Issue:** [#402](https://github.com/NodeJSmith/hassette/issues/402)

## Worth noting (low urgency, no issues filed)

- **Naming drift:** Backend uses "listeners" (Bus API term), frontend uses "handlers" (domain term). Same concept, different names across the stack.
- **WebSocket nesting depth 4** in `routes/ws.py:42-60` — message handling could be extracted for readability.

## Positive findings

### Backend
- Clean FastAPI routing patterns with consistent response shapes
- Proper async/await throughout with no blocking calls
- Good dependency injection via `RuntimeDep` / `TelemetryDep`
- 43 integration tests passing with solid endpoint coverage
- WebSocket cleanup via `finally` blocks with proper unregistration

### Frontend
- Excellent signals-based state management with proper batching
- `useApi` hook handles race conditions, lazy loading, and reconnection refetches
- WebSocket exponential backoff with handshake timeout
- Strict TypeScript with discriminated unions for WS messages
- Minimal bundle: 3 prod deps (~10KB gzip)
- 850+ lines of focused tests on hooks and utilities

### Cross-stack
- API types are mostly well-aligned (the ListenerData gap being the notable exception)
- WebSocket message envelope is consistent (`{ type, data, timestamp }`)
- Error boundaries on all frontend pages
- Theme system works end-to-end (CSS tokens, localStorage, DOM attribute)

## Metrics

| Area | LOC | Tests | Test LOC |
|------|-----|-------|----------|
| Backend web (routes, models, deps) | 1,419 | 43 integration | ~1,200 |
| Core web services | 1,569 | unit + integration | ~1,500 |
| Frontend components | ~2,500 | 0 | 0 |
| Frontend hooks/utils/state | ~600 | 7 test files | 850+ |
| Frontend CSS | ~1,540 | — | — |
