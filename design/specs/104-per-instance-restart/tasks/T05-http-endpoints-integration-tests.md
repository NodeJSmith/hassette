---
task_id: "T05"
title: "Add per-instance HTTP endpoints and integration tests"
status: "planned"
depends_on: ["T04"]
implements: ["FR#6", "AC#6", "AC#7", "AC#10"]
---

## Summary
Add per-instance HTTP endpoints (`POST /apps/{app_key}/instances/{index}/start|stop|reload`) following the existing `_run_app_action` pattern. Add integration tests for the HTTP endpoints and for the end-to-end selective restart flow, including a DB-row-survival test that verifies sibling instances' telemetry rows are not affected by a per-instance reload. Regenerate OpenAPI schema and TypeScript types.

## Target Files
- modify: `src/hassette/web/routes/apps.py`
- modify: `tests/integration/web_api/test_endpoints.py`
- modify: `tests/integration/test_apps.py` (integration test for selective restart with DB verification)
- modify: `openapi.json` (regenerated)
- modify: `frontend/src/api/generated-types.ts` (regenerated)
- read: `src/hassette/core/app_handler.py` (facade delegates from T04)
- read: `src/hassette/web/models.py` (ActionResponse model)
- modify: `docs/pages/` (update relevant multi-instance app documentation pages to mention per-instance restart behavior)
- read: `design/specs/104-per-instance-restart/design.md` (Edge Cases, Smoke Test, Documentation Updates)

## Prompt
### HTTP Routes (`src/hassette/web/routes/apps.py`)

Add three per-instance endpoints following the existing `_run_app_action` pattern:

```python
@router.post(
    "/apps/{app_key}/instances/{index}/reload",
    status_code=202,
    response_model=ActionResponse,
    responses={409: {"description": "App bootstrap not yet released"}},
)
async def reload_instance(app_key: str, index: int, hassette: HassetteDep, request: Request) -> ActionResponse:
    return await _run_app_action(
        "reload", app_key, hassette, request,
        lambda: hassette.app_handler.reload_instance(app_key, index, force_reload=True)
    )
```

Similarly for `start_instance` (with 409 response) and `stop_instance` (without 409 — `stop` skips admission, matching existing full app-key convention).

Add route-level validation: return 404 if `index` is out of range for the current manifest's instance count. Note: `_reload_instance_unlocked()` also re-validates after the lock (see T04), but the route-level check provides a fast user-facing 404 without waiting for lock acquisition.

The `reload` endpoint hardcodes `force_reload=True`, matching the existing full app-key HTTP reload convention.

### Integration Tests

**HTTP endpoint tests** (`tests/integration/web_api/test_endpoints.py`):
- `POST /apps/{app_key}/instances/{index}/reload` returns 202 for valid index
- `POST /apps/{app_key}/instances/{index}/stop` returns 202 for valid index
- `POST /apps/{app_key}/instances/{index}/start` returns 202 for valid index
- Out-of-range index returns 404
- Pre-bootstrap start/reload returns 409

**Selective restart integration test** (`tests/integration/test_apps.py`):
- AC#7: Set up a 2-instance app via `HassetteHarness`, change one instance's config, call `apply_changes()`, verify only that instance reloaded while the other remained running
- AC#10: Same setup — before the reload, record the sibling instance's live listener/job row IDs from the DB. After `reload_instance()`, query the DB and assert the sibling's rows are unaffected (`retired_at IS NULL`, same `id`, no row-count change for that `instance_index`)

### Documentation Updates

Update docs-site pages covering app configuration and multi-instance apps to mention per-instance restart behavior. This includes:
- The new automatic selective restart (only changed instances restart on config change)
- The fallback to full restart when instance count changes
- The new per-instance HTTP endpoints

Check which pages under `docs/pages/` cover multi-instance app configuration and update them. The design doc's `## Documentation Updates` section specifies this ships in the same PR per `.claude/rules/design-completeness.md`.

### Schema Regeneration

After implementation, regenerate schemas and types:
```bash
uv run python scripts/export_schemas.py --types
```

This regenerates `openapi.json`, `generated-types.ts`, and related files. See `.claude/rules/frontend-worktree.md` for the full regeneration workflow.

## Focus
- The `_run_app_action` helper handles error translation, logging, and response construction — reuse it exactly.
- Route-level index validation should check `manifest.app_config` length via `normalize_configs()` — the same way the lifecycle methods do.
- The 409 response declaration on `start`/`reload` (but not `stop`) matches the existing convention at `web/routes/apps.py:182-207`.
- For AC#10, the test needs to:
  1. Bootstrap a 2-instance app with listeners/jobs on both instances
  2. Record the sibling's live DB row IDs (query the `listeners` and `scheduled_jobs` tables for `instance_index = 0`)
  3. Call `reload_instance(app_key, 1)` (or the HTTP endpoint)
  4. Re-query and assert the sibling's rows are unchanged
- The `create_hassette_stub()` helper is for web API tests (MagicMock stub). `HassetteHarness` is for integration tests with real components. Use `HassetteHarness` for AC#7/AC#10.

## Verify
- [ ] FR#6: HTTP endpoints `POST /apps/{app_key}/instances/{index}/start|stop|reload` exist and return 202
- [ ] AC#6: Integration tests for all three per-instance HTTP endpoints verify 202 responses and correct lifecycle behavior
- [ ] AC#7: Integration test with `HassetteHarness` — 2-instance app, change one config, verify only that instance reloaded while the other remained running
- [ ] AC#10: Integration test — 2-instance app, record sibling's listener/job row IDs, call `reload_instance()` on the other index, query DB and assert sibling's rows are unaffected
