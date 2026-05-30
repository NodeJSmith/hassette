---
task_id: "T15k"
title: "Collapse redundant Bus._registered_keys into _registered_handler_names"
status: "planned"
depends_on: ["T15a", "T15b", "T15c", "T15d", "T15e"]
implements: ["AC#1"]
---

## Summary
`Bus._registered_keys` (a `set`) is redundant with `_registered_handler_names` (a `dict`) for membership checks (see [[deferred-items]] T03 entry). It was retained through the async-test adaptation so expected-red name= failures stayed as assertion failures rather than `AttributeError`s. Now that the bus/state tests are rewritten (T15a–T15e), remove it.

## Prompt
**This task DOES change production code** (the only T15 sub-task that does).

**Files (write targets):** `src/hassette/bus/bus.py` (primary), plus any residual test references to `_registered_keys`.

1. In `src/hassette/bus/bus.py`, replace every membership/insert/clear use of `_registered_keys` with the equivalent on `_registered_handler_names` (the dict already holds the same keys). Remove the `_registered_keys` attribute and its initialization.
2. Update the tests that still reach into `_registered_keys` to assert against `_registered_handler_names` instead: at minimum `tests/unit/bus/test_bus.py` (`test_registered_keys_cleared_on_reinit`), `tests/unit/bus/test_bus_timeout_threading.py`, `tests/integration/test_state_proxy.py`. Grep the repo for `_registered_keys` and fix every hit.
3. Confirm no production code outside `bus.py` reads `_registered_keys`.

## Focus
- This is a behavior-preserving refactor: membership semantics must be identical (the dict's keys are the same handler-name keys the set held). Pin behavior by running the bus + state-proxy suites before and after.
- Run AFTER T15a–T15e so no test depends on the attribute existing.
- Gate command: `tests/unit/bus/ tests/integration/bus/ tests/integration/test_state_proxy.py`.

## Verify
- [ ] `grep -rn "_registered_keys" src/ tests/` returns nothing
- [ ] Bus unit + integration suites and `test_state_proxy.py` pass
- [ ] No behavior change to registration/deregistration membership
