---
task_id: "T07"
title: "Update CLI, docs, and remaining test gaps"
status: "planned"
depends_on: ["T03", "T04"]
implements: ["FR#2", "FR#3", "AC#2"]
---

## Summary

Update the CLI module to handle the new `in_current_config` field on `AppManifestListResponse`. Update documentation (web/CLAUDE.md classification table, project CLAUDE.md if needed). Fix remaining test files that reference changed functions/models but weren't covered in earlier tasks. Update E2E mock fixtures.

## Target Files

- modify: `src/hassette/cli/client.py`
- modify: `src/hassette/cli/commands/app.py`
- modify: `tests/e2e/mock_fixtures.py`
- modify: `tests/unit/cli/test_commands_app.py`
- modify: `tests/unit/cli/test_commands_status.py`
- modify: `tests/integration/test_dashboard_without_ha.py`
- modify: `tests/integration/test_hot_reload.py`
- modify: `tests/integration/web_api/test_endpoints.py`
- modify: `tests/integration/web_api/test_validation.py`
- modify: `tests/integration/telemetry/test_global_jobs_and_service_info.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- modify: `tests/system/test_startup_without_ha.py`
- read: `src/hassette/web/models.py` (updated models from T04)

## Prompt

### CLI updates

1. **`cli/client.py`** (line 21, 194): Imports and uses `AppManifestListResponse`. The response now includes `in_current_config` on each manifest. No breaking change expected (new field with default), but verify the client still deserializes correctly.

2. **`cli/commands/app.py`** (line 17, 54): The `app` command fetches and renders manifests as a table. If the table should show `in_current_config` or filter out removed apps, add that logic. If not, verify it handles the new field gracefully.

### Documentation

Update `src/hassette/web/CLAUDE.md` **only if T03 did not already do this** — T03 also lists this file as a target. Check whether the classification table already has the new spine query as Category B before editing. If already updated, skip.

Check the project root `CLAUDE.md`'s Architecture section — if the description of `AppRegistry` or `RuntimeQueryService` references "web routes use get_all_manifests_snapshot()", update it to reflect the DB-spine change.

### Remaining test updates

These test files reference changed functions/models and need updates:

- `tests/e2e/mock_fixtures.py` (line 788): Mocks `get_manifest_snapshot()` — update to mock the DB query instead, or keep the mock if the registry method is still called.
- `tests/integration/test_dashboard_without_ha.py` (line 108): Uses `get_full_snapshot()` — verify this test still passes since the registry behavior is unchanged; update assertions if the test validates web response shape.
- `tests/integration/test_hot_reload.py` (line 236): Uses `get_full_snapshot()` — verify and update if needed.
- `tests/integration/web_api/test_endpoints.py`: Mocks `get_manifest_snapshot()` — update for DB-backed path.
- `tests/integration/web_api/test_validation.py`: References `dashboard_app_grid` — verify assertions match new response shape.
- `tests/integration/telemetry/test_global_jobs_and_service_info.py`: Mocks `get_full_snapshot()` — verify compatibility.
- `tests/unit/core/test_runtime_query_service.py`: Mocks `get_full_snapshot()` — the method still exists on the registry, so this may not need changes.
- `tests/unit/cli/test_commands_app.py`, `test_commands_status.py`: Use `AppManifestListResponse` or `DashboardAppGridEntry` — update for new fields.
- `tests/system/test_startup_without_ha.py` (line 39): Uses `get_full_snapshot()` — verify this system test passes.

For each: read the test, determine if the change breaks it, and fix if needed. Many of these may be compatible as-is (the registry methods are unchanged), but the response model shape changes could cause assertion failures.

## Focus

- The CLI module is production code the design doc's Impact section missed — it's a gap-check finding. Handle `in_current_config` gracefully.
- E2E mock fixtures mock the internal API (not HTTP endpoints) — they may need updating if `get_manifest_snapshot()` is no longer the path the web routes use. But the method still exists on `AppRegistry`, so E2E tests that mock it for the detail page endpoint are fine.
- `test_dashboard_without_ha.py` is a full integration test that boots hassette without HA and checks the dashboard. After this change, the dashboard queries DB — this test should still work since `bootstrap_apps()` persists manifests to DB before the web layer starts.
- System tests run with real components — they should pass without changes if the lifecycle is correct, but verify.

## Verify

- [ ] FR#2: Dashboard grid integration tests pass with DB-only apps showing.
- [ ] FR#3: Apps list integration tests pass with DB-only apps showing.
- [ ] AC#2: All integration tests confirm seeded/DB-only apps appear in both endpoints.
