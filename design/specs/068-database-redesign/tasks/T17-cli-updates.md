---
task_id: "T17"
title: "Update CLI commands for unified execution model and endpoints"
status: "done"
depends_on: ["T07", "T11"]
implements: ["FR#10", "AC#1"]
---

## Summary
The `hassette listener` and `hassette job` CLI commands consume the deleted execution models and the renamed detail endpoint. `T07` deletes `HandlerInvocation`/`JobExecution`; `T11` renames `/api/telemetry/handler/{id}/invocations` to `/api/telemetry/listener/{id}/executions`. Without this task, the CLI fails to import (`HandlerInvocation` is gone) and the `pyright` gate in T16 has no home for the fix. Update the CLI to the unified `Execution` model and the new endpoint paths.

## Prompt
**Step 1: Update `cli/commands/listener.py`:**
- Change the import on line 9 from `HandlerInvocation` to the unified `Execution` model (`from hassette.core.telemetry_models import Execution`).
- Change the detail endpoint from `/api/telemetry/handler/{listener_id}/invocations` to `/api/telemetry/listener/{listener_id}/executions`.
- Change `HandlerInvocation.model_validate(e)` to `Execution.model_validate(e)`.
- `LISTENER_INVOCATION_COLUMNS` reads `status`, `duration_ms`, `error_type`, `error_message`, `execution_start_ts`, `execution_id` — all present on the unified `Execution` model. Verify each column key still resolves.

**Step 2: Update `cli/commands/job.py`:**
- Change the import on line 9 from `JobExecution` to `Execution` (keep `JobSummary` — it stays split per the design).
- The endpoint path `/api/telemetry/job/{job_id}/executions` is unchanged (T11 keeps it), but the response shape is now the unified discriminated union — change `JobExecution.model_validate(e)` to `Execution.model_validate(e)`.
- Verify `JOB_EXECUTION_COLUMNS` keys resolve on the unified model.

**Step 3: Update CLI tests:**
- `tests/unit/cli/test_commands_listener.py` — update the mocked endpoint URL, the mocked response payload shape (unified `Execution` with `kind`), and any `HandlerInvocation` references.
- `tests/unit/cli/test_commands_job.py` — update mocked response shape and `JobExecution` references.
- `tests/system/test_cli_smoke.py` — verify the smoke test still drives `hassette listener <id>` / `hassette job <id>` against the new endpoints.

## Focus
- The CLI hits the REST API over HTTP — it does not import the query service or repository directly. The only backend coupling is the model classes (`telemetry_models`) and the endpoint URLs.
- `listener.py` and `job.py` use `# pyright: ignore[reportArgumentType]` on the `render_table` calls — keep those; the unified model is still structurally compatible with `render_table`.
- The `Column("app_key", "App")` keys stay `app_key` (no rename in this spec). This task only changes the model import, the detail endpoint path, and `model_validate` — not the column keys.

## Verify
- [ ] FR#10: `hassette listener <id>` and `hassette job <id>` consume the unified execution endpoint/model and render correctly
- [ ] AC#1: `timeout 300 uv run pytest tests/unit/cli/test_commands_listener.py tests/unit/cli/test_commands_job.py -n 2` passes
- [ ] `grep -rn "HandlerInvocation\|JobExecution" src/hassette/cli/` returns zero hits
