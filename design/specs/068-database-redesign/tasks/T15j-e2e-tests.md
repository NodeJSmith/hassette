---
task_id: "T15j"
title: "Update e2e tests and add unified WS execution_completed test"
status: "done"
depends_on: ["T11", "T12", "T13"]
implements: ["FR#10", "FR#11", "AC#2", "AC#3"]
---

## Summary
End-to-end tests (`tests/e2e/`, Playwright against a real backend + built frontend) reference old handler/job endpoint URLs, the old per-type WS messages, and pre-unification test-data builders. Update them and add a new test for the unified `execution_completed` WS notification carrying `kind`.

## Prompt
**Files (write targets):** `tests/e2e/mock_fixtures.py`, `tests/e2e/test_url_routing.py`, `tests/e2e/test_websocket.py`, and any other `tests/e2e/*.py` that references the old endpoints/WS shapes (re-scan via grep for `invocation`, `handler/`, `/job/`, `invocation_completed`).

1. Update endpoint URLs (old handler/job paths → `/telemetry/executions`, `/telemetry/listener/{id}/executions`, `/telemetry/job/{id}/executions`).
2. Update WS message assertions to the unified `execution_completed` type with the `kind` field.
3. Update `mock_fixtures.py` data builders to the unified `Execution` model (`kind`, `listener_id`, `job_id`); add `name=` to any listener registrations in fixtures.
4. **Add a new e2e test** (FR#11): a unified `execution_completed` WS notification with `kind` reaches the frontend and updates the activity feed.

## Focus
- **Do NOT run the full Playwright e2e suite in this task's gate** — per the HYBRID strategy, `uv run nox -s e2e` (green) and the AC#3 manual verification are owned by T16. Here, verify collection/import only: `cd frontend && npm install` (worktree needs node_modules) then `uv run pytest -m e2e --collect-only -q`. Note in your output that the full e2e run is deferred to T16.
- Read `src/hassette/web/routes/telemetry.py`, `src/hassette/web/models.py`, and the frontend WS types (regenerated in T12/T13) to confirm the unified shapes before editing assertions.

## Verify
- [ ] FR#10/FR#11: e2e tests target unified endpoints and the unified `execution_completed` WS message with `kind`
- [ ] New e2e test for unified WS notification exists
- [ ] `tests/e2e/` collects without import errors (full run deferred to T16)
