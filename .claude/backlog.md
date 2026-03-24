## Visual QA — 2026-03-23

### 1. Handler descriptions truncate the most important information — HIGH
App detail handler rows show full dotted-path strings that bury entity IDs mid-string. Ellipsis cuts off the most critical info. Extract entity ID as a separate visible field.

### 2. No way to enable a disabled app from the UI — HIGH
Disabled apps have no Enable button on detail page or apps list. Users must edit config files. Add Enable/Start button for disabled apps.

### 3. App detail sections lack visual rhythm — same spacing inside and between — HIGH
Inter-section gap (~16px) matches intra-section padding. Section boundaries are ambiguous. Double inter-section spacing to ~32px.

### 4. Action buttons dominate the apps list table — MEDIUM
Stop/Reload stacked vertically make rows ~80-90px. 12+ outlined colored buttons compete for attention. Side-by-side, ghost style, or overflow menu.

### 5. "Connected" bar wastes prime vertical real estate — MEDIUM
40px full-width bar communicates one bit (connected/not) that's true 99.9% of the time. Collapse to status dot in sidebar; reserve full bar for disconnected.

### 6. Empty sections waste space on app detail — MEDIUM
"Event Handlers (0 registered)" and "Scheduled Jobs (0 active)" take ~80px each for zero content. Collapse or make compact single line.

### 7. Stop button lacks visible hover feedback — MEDIUM
Destructive action shows no visible change on hover. No confirmation dialog either. Add hover state.

### 8. Status badge uses three different treatments for "running" — LOW
Dashboard cards: green text + dot. Apps list: green pill badge. App detail KPI: large green text. Unify to one treatment.

## Web Stack Audit — 2026-03-24

### 1. Hardcoded zero in dashboard KPI: avg_job_duration_ms always shows 0 — CRITICAL
`src/hassette/web/routes/telemetry.py:185` — Job duration KPI hardcoded to `0.0` instead of computed from job executions. Misleading metric on dashboard.

### 2. API contract drift: frontend ListenerData missing ~16 backend fields — CRITICAL
`frontend/src/api/endpoints.ts:60-72` vs `src/hassette/web/models.py:301-327` — Backend returns 27 fields, frontend declares 11. Advanced handler metrics silently discarded.

### 3. ConnectedWsMessage missing timestamp field — CRITICAL
`src/hassette/web/models.py:221-224`, `frontend/ws-schema.json:152-169` — Only WS message type without `timestamp`. Frontend code assuming `msg.timestamp` gets `undefined` on reconnect.

### 4. Dead code: compute_app_grid_health() never called + duplicate logic — HIGH
`src/hassette/web/telemetry_helpers.py:153-181` — Duplicates logic inlined in `routes/telemetry.py:192-237`. Never imported. Maintenance hazard.

### 5. Stub endpoint /scheduler/history returns empty array — HIGH
`src/hassette/web/routes/scheduler.py:52-59` — Exposed in OpenAPI, accepts params, always returns `[]`.

### 6. Frontend error responses never parsed — HIGH
`frontend/src/api/client.ts:16-30` — Backend `HTTPException(detail=...)` wraps as `{"detail": "..."}` but frontend only captures HTTP status text, not the detail field.

### 7. No schema validation tests in CI — HIGH
`frontend/openapi.json` and `frontend/ws-schema.json` have no CI test validating they match backend models. Schema drift happens silently.

### 8. Broad except Exception in telemetry: silent dashboard failures — HIGH
`src/hassette/web/routes/telemetry.py:202` — Database errors, timeouts, coding mistakes all silently return empty summaries. No user-visible error.

### 9. Component test coverage: 0/25 frontend components tested — HIGH
Hooks/utils at 100% but no component tests for LogTable, ManifestList, ActionButtons, or any page.

### 10. Silent WebSocket message drops for slow clients — HIGH
`src/hassette/core/runtime_query_service.py:318-328` — Queue saturation logged at DEBUG only, no metrics, no backpressure.

### 11. Naming drift: "listeners" (backend) vs "handlers" (frontend) — LOW
Same concept, different names across the stack. Creates confusion during cross-stack debugging.

### 12. Type mismatch in bus.py: response_model vs return type — LOW
`src/hassette/web/routes/bus.py:15-24` — `response_model=list[ListenerMetricsResponse]` but return type is `list[ListenerSummary]`.

### 13. Missing response_model on mutation endpoints — LOW
`routes/apps.py`, `routes/services.py`, `routes/config.py` return bare dicts. OpenAPI shows `object` instead of specific fields.

### 14. WebSocket nesting depth 4 — LOW
`src/hassette/web/routes/ws.py:42-60` — Message handling could be extracted for readability.
