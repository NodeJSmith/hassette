---
task_id: "T15f"
title: "Update telemetry query-service tests for unified executions"
status: "done"
depends_on: ["T10", "T11"]
implements: ["FR#10", "AC#1"]
---

## Summary
T10 unified the query service onto the single `executions` table and replaced `get_handler_invocations`/`get_job_executions` with `get_executions` (kind-filtered). The telemetry query-service tests still call the deleted methods, read the old tables, and assert the old row shapes. Update them to the unified API and schema.

## Prompt
**Files (write targets):** `tests/integration/telemetry/test_telemetry_query_service.py`, `tests/integration/telemetry/test_telemetry_query_service_aggregates.py`, `tests/integration/telemetry/test_telemetry_query_service_misc.py`, `tests/integration/telemetry/test_telemetry_execution_id.py`, `tests/integration/telemetry/test_telemetry_timed_out.py`. The shared `tests/integration/telemetry/helpers.py` already writes to `executions` (fixed in T08) — extend it only if a needed insert helper is missing.

1. Replace calls to removed query methods with `get_executions(..., kind="handler"|"job")` (or the unified accessor that T10 introduced — read `src/hassette/core/telemetry/` to confirm the current surface).
2. Update assertions to the unified `Execution` model shape (`kind`, `listener_id`, `job_id`) instead of `HandlerInvocation`/`JobExecution`.
3. Update any direct SQL / table-name references from `handler_invocations`/`job_executions` to `executions`.
4. `test_telemetry_execution_id.py`: the 3 execution-id tests persist to `executions` but read via the old query methods — point them at the unified read path (see [[deferred-items]] T08→T10 entry).

## Focus
- Read `src/hassette/core/telemetry/{query_service,execution_queries,helpers}.py` first to learn the actual unified query surface — do not guess method names.
- Gate command: `tests/integration/telemetry/test_telemetry_query_service.py tests/integration/telemetry/test_telemetry_query_service_aggregates.py tests/integration/telemetry/test_telemetry_query_service_misc.py tests/integration/telemetry/test_telemetry_execution_id.py tests/integration/telemetry/test_telemetry_timed_out.py`.

## Verify
- [ ] FR#10: query tests assert unified executions with `kind`
- [ ] All listed files collect and pass
- [ ] No references to `handler_invocations`/`job_executions` tables or removed query methods remain in these files
