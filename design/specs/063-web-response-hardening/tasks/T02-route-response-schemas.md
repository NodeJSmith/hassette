---
task_id: "T02"
title: "Fix route response schemas and type annotations"
status: "planned"
depends_on: ["T01"]
implements: ["FR#2", "FR#9", "AC#2", "AC#10"]
---

## Summary
Ensure every route in the web layer has an explicit `response_model` parameter and correct return type annotation. Fix the `/logs/recent` return type mismatch, add `response_model` to `/events/recent` and `/services`, and document the `instance_index` parameter on all per-app telemetry routes. This task depends on T01 because the model fields must be typed before route annotations are meaningful.

## Prompt
1. **Fix `/api/events/recent`** in `src/hassette/web/routes/events.py` (17 lines total):
   - Add `response_model=list[EventEntry]` to the `@router.get` decorator
   - Change return type to `-> list[EventEntry]`
   - Convert returned dicts: `return [EventEntry.model_validate(e) for e in runtime.get_recent_events(limit=limit)]`
   - Verify the dict shape from `runtime.get_recent_events()` matches `EventEntry` fields by reading `src/hassette/core/runtime_query_service.py` for the buffer population code

2. **Fix `/api/services`** in `src/hassette/web/routes/services.py` (22 lines total):
   - Add `response_model=dict[str, Any]` to the `@router.get` decorator
   - This is decorator-only — the function body is already correct

3. **Fix `/api/logs/recent`** in `src/hassette/web/routes/logs.py`:
   - Change function signature from `-> list[dict]` to `-> list[LogEntryResponse]` (around line 36)
   - Add `model_validate` mapping: `return [LogEntryResponse.model_validate(r) for r in records]` — matching the pattern already at line 91 in `get_logs_by_execution`

4. **Add `instance_index` parameter descriptions** on all per-app telemetry routes in `src/hassette/web/routes/telemetry.py`:
   - Find all `instance_index: int = 0` parameters (lines ~121, 184, 234)
   - Change to `instance_index: int = Query(default=0, description="App instance index. Defaults to 0. Multi-instance apps have indices 0..N-1.")`
   - Also check `src/hassette/web/routes/bus.py` line 21 for the same pattern

5. **Audit all routes** — grep `src/hassette/web/routes/` for any remaining `@router.get` or `@router.post` without `response_model=`. Every route must have one.

## Focus
- `EventEntry` model already exists in `src/hassette/web/models.py` — it was defined but not used by the events route.
- The `/logs/recent` route at `logs.py:36` has `response_model=list[LogEntryResponse]` in the decorator (correct) but `-> list[dict]` in the signature (wrong). Both need to agree.
- The `Query` import from FastAPI is already used in `telemetry.py` — no new import needed there. May need importing in `bus.py`.
- `services.py` returns an opaque `dict[str, Any]` from Home Assistant — FastAPI accepts `dict[str, Any]` as a `response_model` and generates correct OpenAPI output.

## Verify
- [ ] FR#2: Every route in `src/hassette/web/routes/` has an explicit `response_model` parameter — run `grep -rn "router\.\(get\|post\|put\|delete\)" src/hassette/web/routes/` and confirm each has `response_model=`
- [ ] FR#9: Per-app telemetry endpoints (`/app/{app_key}/health`, `/app/{app_key}/listeners`, `/app/{app_key}/jobs`, `/bus/listeners`) have `description` on `instance_index` Query parameter
- [ ] AC#2: No route returns an untyped dict or list without a response_model declaration
- [ ] AC#10: `instance_index` parameter descriptions appear in the OpenAPI spec after schema regeneration (verified in T07)
