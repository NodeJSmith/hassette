---
task_id: "T02"
title: "Split health endpoints and add liveness/readiness models"
status: "done"
depends_on: ["T01"]
implements: ["FR#4", "FR#5", "FR#6", "FR#8", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7", "AC#8", "AC#9"]
---

## Summary
Reshape `/api/health` to always return 200 while serving, and add `/api/health/live` (process-responds liveness, no checks) and `/api/health/ready` (200 only when status is `ok`). Add the two small response models, regenerate the OpenAPI schema and frontend types, and confirm `hassette status` prints all three states without an error envelope. This is what actually stops the reboot loop — supervisors get a liveness signal that ignores HA.

## Prompt
Implement the endpoint split described in `design.md` → Architecture → "Endpoints" and "Models", following the Convention Example in `context.md`.

1. **`src/hassette/web/models.py`** — add two response models near `SystemStatusResponse` (~line 64). A liveness model (e.g. `LivenessResponse` with a `status` field) and a readiness model (e.g. `ReadinessResponse` with `status` and `ready: bool`). Do NOT change `SystemStatusResponse` or the `SystemHealthStatus` literal (`models.py:36`).

2. **`src/hassette/web/mappers.py`** — add mapper function(s) for the new model(s) if the readiness model needs to be built from `SystemStatus` (mirror `system_status_response_from` at `mappers.py:107`). The liveness model is a constant body and may not need a mapper.

3. **`src/hassette/web/routes/health.py`** — reshape and extend:
   - `GET /api/health` — remove the `if status_data.status == "starting": response.status_code = 503` rule (`health.py:20-21`) AND the now-stale comment above it (`health.py:19`: `# degraded (WS down, apps running) is still functional — only starting is not ready`). The handler returns the `SystemStatusResponse` body and sets no status code → always 200 while serving. Drop the `503` entry from `responses=` for this route. Once the conditional is gone, the `response` parameter is unused by this handler — remove it. Keep the `Response` import (the new `/api/health/ready` route still uses it).
   - `GET /api/health/live` — new route returning the liveness model at 200 with no conditional, no dependency check, no service-state reduction. Reaching the handler means the loop can serve.
   - `GET /api/health/ready` — new route returning the readiness model; set `response.status_code = 503` when `get_system_status().status != "ok"`, else 200. This is the only one of the three with a status-code conditional.

4. **Schema + frontend regeneration** — per `.claude/rules/frontend-worktree.md`:
   ```bash
   cd frontend && npm install        # once per worktree
   cd .. && uv run python scripts/export_schemas.py --types
   cd frontend && npm run build
   ```
   This regenerates `openapi.json`, `frontend/src/api/generated-types.ts`, `ws-schema.json`, and `ws-types.ts`. Commit the regenerated artifacts.

5. **CLI (`src/hassette/cli/commands/status.py`)** — `status.py:12` calls `client.get("/api/health", SystemStatusResponse)`. Because `/api/health` now returns 200 for `degraded`/`starting`, the client no longer hits the error path for those states. Verify the display logic prints `ok`, `degraded`, and `starting` correctly. Add/extend a test confirming a non-`ok` status prints the status object, not an error envelope.

6. **Tests** — per `design.md` → Test Strategy:
   - `tests/integration/web_api/test_endpoints.py` (`TestHealthEndpoints`, ~lines 30–46): `test_health_returns_503_when_starting` (~:39) must now expect **200** — also remove its now-dead `_state_proxy.is_ready.return_value = False` line (proxy_ready no longer drives status after T01) and rely on `ever_connected` defaulting to `False` from `create_hassette_stub` to produce `starting`; `test_health_returns_200_when_degraded` (~:30) must drive `websocket_service.ever_connected` (the `proxy_ready` fallback is gone — without the latch attribute it would now report `starting`). Add cases: `/api/health/live` returns 200 regardless of WS/service state; `/api/health/ready` returns 200 only for `ok`, 503 for `degraded`/`starting`.
   - Confirm the frontend build passes and existing frontend `/api/health` tests still pass (they mock the unchanged response shape; none assert `starting → 503`).

## Focus
- `health.py` is short (22 lines) — current imports: `APIRouter`, `Response`, `RuntimeDep`, `system_status_response_from`, `SystemStatusResponse`. The router is `APIRouter(tags=["health"])`.
- `RuntimeDep` is the injected runtime query service (`hassette.web.dependencies`). `/api/health/live` needs no dependency at all.
- `SystemStatusResponse` fields (`models.py:64-75`): `status`, `websocket_connected`, `uptime_seconds`, `entity_count`, `app_count`, `services_running`, `services`, `version`, `boot_issues`, `log_records_dropped` — unchanged.
- Gap note (verified, no change needed): `tests/system/conftest.py:304` `wait_for_web_server` accepts `status_code in (200, 503)`, so the always-200 reshape doesn't break server-readiness polling. Frontend mocks (`frontend/src/test/handlers.ts:177`, `frontend/src/pages/diagnostics.test.tsx`) mock the unchanged shape and 200/500/hang scenarios, not `starting → 503` specifically.
- CLI test fixtures: `tests/unit/cli/conftest.py:60,141` register `GET /api/health → 200 {"status": "ok"}`. Extend for a non-`ok` 200 case if needed for the FR#8 test.
- The pre-push hook (`tools/check_schemas_fresh.py`) checks `ws-schema.json`/`openapi.json` freshness; CI also git-diffs `generated-types.ts`. Regenerate and commit or the build fails.

## Verify
- [ ] FR#4: `GET /api/health/live` returns 200 with the liveness body, with no dependency or service-state check in the handler.
- [ ] FR#5: `GET /api/health/ready` returns 200 when `get_system_status().status == "ok"` and 503 otherwise.
- [ ] FR#6: `GET /api/health` returns 200 for `ok`, `degraded`, and `starting`; the handler sets no 503.
- [ ] FR#8: `hassette status` against a `degraded`/`starting` instance prints the status object without an error envelope or non-zero exit attributable to the health code.
- [ ] AC#3: `GET /api/health` returns 200 with body `status == "degraded"` for a booted, WS-disconnected instance.
- [ ] AC#4: `GET /api/health/ready` returns 503 for `degraded`/`starting` and 200 for `ok`.
- [ ] AC#5: `GET /api/health/live` returns 200 while the WS is disconnected and during the startup window (response independent of HA/service state).
- [ ] AC#6: `GET /api/health` never returns 503 from the handler.
- [ ] AC#7: `openapi.json`, `frontend/src/api/generated-types.ts`, `ws-schema.json`, and `ws-types.ts` regenerate cleanly and `npm run build` passes.
- [ ] AC#8: `hassette status` prints `degraded`/`starting` without a non-zero exit attributable to the health code.
- [ ] AC#9: `GET /api/health` returns 200 with body `status == "ok"` when the WS is connected.
