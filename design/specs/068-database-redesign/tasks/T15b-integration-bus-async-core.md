---
task_id: "T15b"
title: "Async-adapt integration bus core tests"
status: "done"
depends_on: ["T04"]
implements: ["AC#1"]
---

## Summary
The public bus registration API is now `async` (T04). `tests/integration/bus/test_bus.py` registers handlers directly and fails with "coroutine 'Bus.on_state_change' was never awaited" / "object Mock can't be used in 'await' expression". Adapt it (plus the bus integration `conftest.py`/`helpers.py`) to the async contract.

## Prompt
**Files (write targets):** `tests/integration/bus/test_bus.py`, `tests/integration/bus/conftest.py`, `tests/integration/bus/helpers.py`. Leave the other `tests/integration/bus/*.py` files to T15c.

1. Add `await` to every DIRECT `bus.on_state_change/on_attribute_change/on_call_service/on_component_loaded/on` call in test bodies and helpers.
2. Add `name=` to any registration missing it (now required for `on()`).
3. Where a `bus`/`scheduler`/service registration method is mocked with `Mock`, switch to `AsyncMock`.
4. Calls made inside an app's `on_initialize` (via the harness) are already awaited by the app — leave those untouched.

## Focus
- Work by grepping for the call patterns and editing targeted lines — do NOT read the whole 789-line file into context at once.
- Do NOT modify production code. `Bus._registered_keys` is retained until T15k — keep any references working.
- Gate command: `tests/integration/bus/test_bus.py`.

## Verify
- [ ] `tests/integration/bus/test_bus.py` collects and passes
- [ ] No "coroutine was never awaited" / "Mock can't be used in await" warnings or errors remain in this file
