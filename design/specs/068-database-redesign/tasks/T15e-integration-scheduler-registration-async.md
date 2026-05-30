---
task_id: "T15e"
title: "Async-adapt remaining integration registration tests"
status: "planned"
depends_on: ["T04"]
implements: ["AC#1"]
---

## Summary
The remaining top-level integration tests that register via the bus/scheduler directly — scheduler, registration, drain, file-watcher, source-capture, hot-reload — need the async-everywhere adaptation (T04).

## Prompt
**Files (write targets):** `tests/integration/test_scheduler.py`, `tests/integration/test_scheduler_error_handler.py`, `tests/integration/test_registration.py`, `tests/integration/test_drain_iterative.py`, `tests/integration/test_file_watcher.py`, `tests/integration/test_source_capture_integration.py`, `tests/integration/test_hot_reload.py`.

1. Add `await` to every DIRECT `bus.on_*` / `scheduler.run_*` / `schedule` / `add_job` call in test bodies and local fixtures.
2. Add `name=` where missing (required for `on()`).
3. Swap mocked registration `Mock` → `AsyncMock`.
4. Leave registrations inside app `on_initialize` (harness already awaits them).
5. **Re-scan before finishing:** `grep -rl "never awaited\|can't be used in 'await'"` is not reliable; instead run the gate, and for any remaining integration test outside the T15b/c/d file sets that fails with an await/Mock async error, fix it here. Note any file you touched that is not listed above.

## Focus
- Mechanical edit by grep — do not read whole files into context.
- No production-code changes.
- Gate command: `tests/integration/test_scheduler.py tests/integration/test_scheduler_error_handler.py tests/integration/test_registration.py tests/integration/test_drain_iterative.py tests/integration/test_file_watcher.py tests/integration/test_source_capture_integration.py tests/integration/test_hot_reload.py`.

## Verify
- [ ] All listed files collect and pass
- [ ] No await/Mock async errors remain in these files
