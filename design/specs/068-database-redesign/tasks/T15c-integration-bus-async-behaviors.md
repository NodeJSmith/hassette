---
task_id: "T15c"
title: "Async-adapt integration bus behavior tests"
status: "done"
depends_on: ["T04"]
implements: ["AC#1"]
---

## Summary
Same async-everywhere adaptation as T15b, for the bus behavior suites: duration-hold, immediate-fire, and error-handler combinations. These register handlers directly and fail on the now-async registration API.

## Prompt
**Files (write targets):** `tests/integration/bus/test_bus_duration.py`, `tests/integration/bus/test_bus_immediate.py`, `tests/integration/bus/test_bus_error_handler.py`, `tests/integration/bus/test_bus_error_handler_combos.py`.

1. Add `await` to every DIRECT `bus.on_*` registration call in test bodies.
2. Add `name=` where missing (required for `on()`).
3. Swap mocked registration `Mock` → `AsyncMock`.
4. Leave registrations inside app `on_initialize` (harness already awaits them).

## Focus
- Mechanical edit by grep — do not read all four files fully into context.
- No production-code changes. `_registered_keys` retained until T15k.
- Gate command: `tests/integration/bus/test_bus_duration.py tests/integration/bus/test_bus_immediate.py tests/integration/bus/test_bus_error_handler.py tests/integration/bus/test_bus_error_handler_combos.py`.

## Verify
- [ ] All four files collect and pass
- [ ] No await/Mock async errors remain in these files
