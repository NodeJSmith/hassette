---
task_id: "T02"
title: "Remove overview-only backend routes and tests"
status: "planned"
depends_on: []
implements: ["FR#5", "FR#6", "AC#4", "AC#5"]
---

## Summary
Remove the four overview-only backend routes from the telemetry router and their associated response models, query methods, and tests. Preserve the app grid and health/system status routes which serve other pages. Verify that all remaining pages and API consumers continue to function.

## Prompt
1. **Remove four routes** from `src/hassette/web/routes/telemetry.py`:
   - `GET /telemetry/dashboard/kpis` (line ~307) — `DashboardKpisResponse`
   - `GET /telemetry/dashboard/activity` (line ~385) — `list[ActivityFeedEntry]`
   - `GET /telemetry/dashboard/errors` (line ~487) — `DashboardErrorsResponse`
   - `GET /telemetry/dashboard/framework-summary` (line ~541) — `FrameworkSummaryResponse`

2. **Remove response models** from `src/hassette/web/models.py` (or wherever they're defined): `DashboardKpisResponse`, `ActivityFeedEntry`, `DashboardErrorsResponse`, `FrameworkSummaryResponse`. Grep to confirm they're not used elsewhere.

3. **Remove query methods** from `src/hassette/core/telemetry_query_service.py` if any are exclusively used by the deleted routes. Grep each method name to verify no other callers exist. Methods that may be overview-only: `get_dashboard_kpis`, `get_dashboard_errors`, `get_activity_feed`, `get_framework_summary` (verify exact names by reading the route handlers).

4. **Update backend tests**: Remove tests for the deleted routes and models from:
   - `tests/integration/test_dashboard_api.py` — contains tests for both overview-only routes AND the preserved `/health` route (`TestVersionInHealth`, lines ~54-122). Delete overview-only test classes but KEEP health-route tests. Move health-route tests to another test file if needed.
   - `tests/integration/test_dashboard_telemetry.py` (~18KB) — integration tests for the deleted query methods (`get_activity_feed`, `get_recent_errors`, etc.). Delete entirely after confirming all tested methods are removed.
   - `tests/unit/core/test_dashboard_models.py` — imports `DashboardKpisResponse` directly. Delete after the model is removed.
   - `tests/integration/test_web_api.py` — remove only tests for deleted routes
   - `tests/system/test_web_api.py` — remove only tests for deleted routes

5. **Preserve these routes** (verify they still work after the removal):
   - `GET /telemetry/dashboard/app-grid` — serves `getDashboardAppGrid`, consumed by `apps.tsx`
   - `GET /health` — serves `getSystemStatus`, consumed by `diagnostics.tsx`

6. **Regenerate schemas** after model removal: `uv run python scripts/export_schemas.py` and regenerate frontend types.

7. **Run tests**: `timeout 300 uv run pytest tests/ -x -n 2 --dist loadscope -q --no-header -m "not e2e and not system" --ignore=tests/test_docker_integration.py` to confirm no regressions.

## Focus
- All four routes are in `src/hassette/web/routes/telemetry.py`. They're decorated with `@router.get("/dashboard/...")`.
- The app-grid route (`/telemetry/dashboard/app-grid`) must NOT be removed — it's used by apps.tsx.
- Response models may be in `src/hassette/web/models.py` or `src/hassette/core/telemetry_models.py` — grep for the exact class names.
- Query methods live in `src/hassette/core/telemetry_query_service.py`. Each route handler calls a specific method — read the route handlers to find the method names, then grep to verify they have no other callers.
- `test_dashboard_api.py` is NOT entirely overview-specific — `TestVersionInHealth` (lines ~54-122) covers the preserved `/health` route. Read it and keep those tests.
- `test_dashboard_telemetry.py` (~18KB) covers the query methods being deleted. Read it to confirm all tested methods are overview-only before deleting.
- `test_dashboard_models.py` imports deleted response models — will fail at import time if not removed.

## Verify
- [ ] FR#5: The four overview-only backend routes are removed and return 404
- [ ] FR#6: `GET /telemetry/dashboard/app-grid` and `GET /health` still return 200 with correct data
- [ ] AC#4: The apps page and diagnostics page function identically (their API calls succeed)
- [ ] AC#5: No orphaned backend routes, response models, or query methods remain from the overview
