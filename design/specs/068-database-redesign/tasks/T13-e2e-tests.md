---
task_id: "T13"
title: "Update e2e and system tests for unified schema"
status: "planned"
depends_on: ["T06", "T07", "T09", "T10", "T11"]
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
- `tests/integration/web_api/test_validation.py` — `dropped_no_session` assertions
- `tests/unit/test_schema_migration.py` — schema structure validation
- `tests/unit/core/conftest.py` — CREATE TABLE statements for test DB

## Focus
- E2e tests run with Playwright against a real backend — the schema must be correct before these pass.
- System tests use Docker — run via `uv run nox -s system` and `uv run nox -s e2e`.
- `test_database_service_migrations.py` validates migration ordering and content — this needs to verify the new 001.sql.
- `test_schema_migration.py` (unit) validates schema structure — update expected table/column names.

## Verify
- [ ] FR#10: E2e test verifies unified execution endpoint returns correct data
- [ ] FR#11: E2e test verifies WS `execution_completed` notification reaches frontend
- [ ] AC#2: `uv run nox -s e2e` passes
- [ ] AC#3: Manual verification: handlers page shows unified list, detail pages load, activity feed updates
