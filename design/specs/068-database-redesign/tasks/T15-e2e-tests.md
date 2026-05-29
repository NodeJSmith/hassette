---
task_id: "T15"
title: "Update e2e and system tests for unified schema"
status: "planned"
depends_on: ["T08", "T09", "T11", "T12", "T13"]
implements: ["FR#10", "FR#11", "AC#2", "AC#3"]
---

## Summary
Update end-to-end and system tests to work with the unified execution endpoints, WS messages, and frontend routing. Verify the full stack integration.

## Prompt
**Step 1: Update e2e tests** — in `tests/e2e/`:
- Update any tests referencing handler/job endpoints by URL (old paths → new paths)
- Update WS message assertions for `execution_completed` unified type
- Update `mock_fixtures.py` test data builders for unified `Execution` model
- Add `name=` to any listener registrations in test fixtures

**Step 2: Update system tests** — in `tests/system/`:
- `conftest.py:262` — simplify `sub.listener.db_id is not None` gate (always true now)
- Update any system tests that reference `registration_task`
- Add `name=` to listener registrations in system test apps

**Step 3: Write new e2e test:**
- Test: unified WS `execution_completed` notification with `kind` field reaches frontend (FR#11)

**Step 4: Update integration tests not covered by earlier tasks:**
- `tests/integration/telemetry/test_telemetry_execution_id.py` — table name references
- `tests/integration/telemetry/test_framework_telemetry.py` — table name and counter assertions
- `tests/integration/database/test_database_service.py` — retention/cleanup table references
- `tests/integration/database/test_database_service_migrations.py` — migration validation
- `tests/integration/web_api/test_telemetry.py` — endpoint response shapes
- `tests/unit/test_schema_migration.py` — schema structure validation
- `tests/unit/core/conftest.py` — CREATE TABLE statements for test DB

**Step 5: ASYNC-EVERYWHERE test adaptation (added during T04, 2026-05-29).** The public bus/scheduler registration API is now `async`. Integration/system tests that register via `bus.on_*` / `scheduler.run_*` / `schedule` / `add_job` must `await` those calls AND use `AsyncMock` (not `Mock`) for any mocked `bus`/`scheduler`/service registration methods (a plain `Mock` raises `object Mock can't be used in 'await' expression`). Known-affected files (non-exhaustive — re-scan):
- `tests/integration/test_state_proxy.py` (currently failing: "coroutine 'Bus.on_state_change' was never awaited" + `await Mock`; also still references `bus._registered_keys` — keep working, that attr is retained)
- `tests/integration/test_app_test_harness.py`
- `tests/integration/test_drain_iterative.py`
- `tests/integration/bus/test_bus.py`
- `tests/system/apps/bus_handler_app.py`
- Also fold in the T03-deferred `tests/unit/bus/test_bus.py` rewrite (name=-required contract; the redundant `Bus._registered_keys` set can be collapsed into `_registered_handler_names` once these tests are rewritten — see [[deferred-items]]).

## Focus
- E2e tests run with Playwright against a real backend — the schema must be correct before these pass.
- System tests use Docker — run via `uv run nox -s system` and `uv run nox -s e2e`.
- `test_database_service_migrations.py` validates migration ordering and content — verify the new 001.sql.
- `test_schema_migration.py` (unit) validates schema structure — update expected table/column names.

## Verify
- [ ] FR#10: E2e test verifies unified execution endpoint returns correct data
- [ ] FR#11: E2e test verifies WS `execution_completed` notification reaches frontend
- [ ] AC#2: `uv run nox -s e2e` passes
- [ ] AC#3: Manual verification: handlers page shows unified list, detail pages load, activity feed updates
