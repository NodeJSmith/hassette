---
task_id: "T15g"
title: "Update telemetry framework, globals, and web_api tests"
status: "done"
depends_on: ["T08", "T10", "T11"]
implements: ["FR#10", "AC#1"]
---

## Summary
The framework-telemetry, health-aggregate, global-jobs, and web_api telemetry tests assert behaviors the unified schema changes: sentinel-filtering and orphan-null-FK rows are eliminated by the FK-mutex CHECK and synchronous registration (design: "zero orphan records, zero sentinel filtering"), counters/aggregates now come from one `executions` table, and the REST endpoints return the unified `Execution` shape.

## Prompt
**Files (write targets):** `tests/integration/telemetry/test_framework_telemetry.py`, `tests/integration/telemetry/test_health_aggregates_and_global_listeners.py`, `tests/integration/telemetry/test_global_jobs_and_service_info.py`, `tests/integration/web_api/test_telemetry.py`.

1. `test_framework_telemetry.py`: remove the 4 sentinel/orphan tests that the unified CHECK eliminates — `test_sentinel_filtering_listener_id_zero`, `test_sentinel_filtering_session_id_zero`, `test_pre_registration_orphan_persisted_with_null_listener_id`, `test_queue_persistence_via_drain_and_persist` (see [[deferred-items]] T08→T09 entry; T09 already removed the analogous command-executor tests). Update remaining counter/table assertions to `executions`.
2. Update aggregate/global tests to the unified table and `Execution` shape (`kind`, `listener_id`, `job_id`).
3. `web_api/test_telemetry.py`: update endpoint paths to the unified routes (`/telemetry/executions`, `/telemetry/listener/{id}/executions`, `/telemetry/job/{id}/executions`) and response shapes; `kind` query param is validated `Literal["handler","job"]` (invalid → 422).

## Focus
- Read `src/hassette/web/routes/telemetry.py` and `src/hassette/web/models.py` to confirm endpoint paths and response models before editing assertions.
- Deleting tests for eliminated behavior is correct here — do not try to keep sentinel/orphan coverage alive.
- Gate command: `tests/integration/telemetry/test_framework_telemetry.py tests/integration/telemetry/test_health_aggregates_and_global_listeners.py tests/integration/telemetry/test_global_jobs_and_service_info.py tests/integration/web_api/test_telemetry.py`.

## Verify
- [ ] FR#10: web_api tests hit unified endpoints and assert `kind`
- [ ] Sentinel/orphan tests removed (behavior eliminated by design)
- [ ] All listed files collect and pass
