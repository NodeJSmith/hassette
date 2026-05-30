---
task_id: "T15a"
title: "Rewrite unit bus tests to name=-required contract"
status: "done"
depends_on: ["T03", "T04"]
implements: ["AC#1"]
---

## Summary
`bus.on()` now requires `name=` (raises `ListenerNameRequiredError`) and the registration API is async (T04). The unit bus tests in `tests/unit/bus/test_bus.py` still assert the old "name optional" contract and register without `name=`. Rewrite them to the new contract and dedupe against `tests/unit/bus/test_t03_registration_errors.py`, which already covers the name= validation.

## Prompt
**Files (write targets):** `tests/unit/bus/test_bus.py` only. Other `tests/unit/bus/*.py` were adapted during T04 and pass — do not touch them unless this task's gate shows a regression there.

1. Rewrite registrations that call `bus.on(...)` / `bus.on_state_change(...)` etc. WITHOUT `name=` to pass an explicit `name=`. Add `await` to every direct async registration call.
2. Delete or rewrite `test_name_none_by_default` (asserts the now-invalid "name optional" contract).
3. `test_registered_keys_cleared_on_reinit` references `Bus._registered_keys` — that attribute is still present (its removal is T15k). Keep the test working against `_registered_keys` for now; do NOT remove the attribute here.
4. Dedupe: if a test here now duplicates a case in `test_t03_registration_errors.py` (e.g. "registering without name raises"), remove the duplicate from `test_bus.py` and leave the canonical one in the t03 file.

## Focus
- Async recipe: add `await` to direct `bus.on*`/`scheduler.run*`/`schedule`/`add_job` calls; swap mocked registration `Mock` → `AsyncMock`. Calls inside an app's `on_initialize` are already awaited by the app — leave those.
- `_registered_keys` is intentionally retained until T15k. See [[deferred-items]] (T03 entry).
- Gate command: `tests/unit/bus/test_bus.py tests/unit/bus/test_t03_registration_errors.py`.

## Verify
- [ ] `tests/unit/bus/test_bus.py` collects and passes
- [ ] No test asserts name= is optional
- [ ] No duplication of name= validation between test_bus.py and test_t03_registration_errors.py
