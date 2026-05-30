---
task_id: "T15d"
title: "Async-adapt integration state-proxy and harness tests"
status: "done"
depends_on: ["T04"]
implements: ["AC#1"]
---

## Summary
State-proxy and app-harness integration tests register handlers directly and fail on the now-async registration API (T04). Adapt them.

## Prompt
**Files (write targets):** `tests/integration/test_state_proxy.py`, `tests/integration/test_app_test_harness.py`, `tests/integration/test_app_harness_simulation.py`.

1. Add `await` to every DIRECT `bus.on_*` / `scheduler.run_*` / `schedule` / `add_job` call in test bodies and local fixtures.
2. Add `name=` where missing (required for `on()`).
3. Swap mocked registration `Mock` → `AsyncMock`.
4. Leave registrations inside app `on_initialize` (harness already awaits them).
5. `test_state_proxy.py` references `bus._registered_keys` — keep it working; the attribute is removed in T15k, not here.

## Focus
- Mechanical edit by grep — do not read all three files (~1.7k lines) fully into context.
- No production-code changes.
- Gate command: `tests/integration/test_state_proxy.py tests/integration/test_app_test_harness.py tests/integration/test_app_harness_simulation.py`.

## Verify
- [ ] All three files collect and pass
- [ ] No await/Mock async errors remain in these files
