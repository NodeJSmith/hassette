---
task_id: "T02"
title: "Update tests for new signatures and domain derivation"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "AC#1", "AC#2", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7", "AC#9"]
---

## Summary

Update all test files that reference the old signatures: `"homeassistant"` domain default assertions, `"toggle_service"` method name strings, and missing `**data` coverage on `turn_off`/`toggle`. Add new tests for domain derivation (derived and explicit override paths) and `**data` forwarding on `turn_off`/`toggle`. Verify the Pyright probe still works with `domain: str | None`.

## Target Files

- modify: `tests/unit/test_recording_api.py`
- modify: `tests/unit/test_recording_sync_facade.py`
- modify: `tests/unit/test_api_coroutine_conversion.py`
- modify: `tests/unit/test_sync_entity_facade.py`
- modify: `tests/unit/test_entity_coroutine_conversion.py`
- modify: `tests/unit/test_forgotten_await_completeness.py`
- modify: `tests/pyright_probes/forgotten_await_probe.py`
- modify: `tests/integration/test_sync_facades.py`
- read: `tests/integration/test_app_harness_simulation.py`
- read: `tests/integration/test_drain_iterative.py`
- read: `tests/integration/test_app_test_harness.py`

## Prompt

Update test files to match the new method signatures from T01. The changes fall into three categories: (A) rename `toggle_service` → `toggle`, (B) update `"homeassistant"` domain assertions to derived domains, (C) add new test coverage.

### A. Rename `toggle_service` → `toggle`

**`tests/unit/test_recording_api.py`:**
- Rename `test_toggle_service_records_call` → `test_toggle_records_call` (line 97)
- Rename `test_toggle_service_accepts_strenum` → `test_toggle_accepts_strenum` (line 375)
- Change all `api.toggle_service(...)` calls to `api.toggle(...)`
- Change all `assert call.method == "toggle_service"` to `assert call.method == "toggle"`

**`tests/unit/test_recording_sync_facade.py`:**
- Rename `test_sync_toggle_service_records_with_correct_shape` → `test_sync_toggle_records_with_correct_shape` (line 92)
- Change `api.sync.toggle_service(...)` to `api.sync.toggle(...)`
- Change `assert call.method == "toggle_service"` to `assert call.method == "toggle"`
- Update the parametrized list at line 267 and line 288: change `"toggle_service"` to `"toggle"`

**`tests/unit/test_api_coroutine_conversion.py`:**
- Line 33: Change `lambda a: a.toggle_service("switch.fan")` to `lambda a: a.toggle("switch.fan")`, update `id="toggle_service"` to `id="toggle"`
- Line 67: Same change for the sync facade parametrize

**`tests/unit/test_sync_entity_facade.py`:**
- Lines 253, 272: Change `("toggle", "toggle_service")` tuple to `("toggle", "toggle")` in the parametrized test data — this maps entity method name to API method name

**`tests/unit/test_entity_coroutine_conversion.py`:**
- No code changes needed — tests reference `BaseEntity.toggle` (already correct name). Verify the docstring comments at lines 4, 7 still read correctly.

**`tests/unit/test_forgotten_await_completeness.py`:**
- Line 89: Change `"toggle_service"` to `"toggle"` in the method name list
- Line 219: Change key `"toggle_service"` to `"toggle"` and lambda `api.toggle_service(...)` to `api.toggle(...)`

**`tests/pyright_probes/forgotten_await_probe.py`:**
- Verify that `api.turn_on("light.kitchen")` probe (line 126) still triggers `reportUnusedCoroutine` with the new `domain: str | None = None` signature. No code change expected, but run the probe to confirm.

**`tests/integration/test_sync_facades.py`:**
- Check for any `toggle_service` references and update to `toggle`. The test at line 38 calls `self.api.sync.turn_on(...)` — verify it still works (no `domain=` change needed since the test doesn't assert on domain).

### B. Update domain assertions

**`tests/unit/test_recording_api.py`:**
- Line 39: `assert call.kwargs == {"entity_id": "light.test", "domain": "homeassistant", "brightness": 150}` → change `"homeassistant"` to `"light"` (derived from `"light.test"`)
- Line 94: `"domain": "homeassistant"` → `"domain": "switch"` (derived from `"switch.fan"`)
- Line 104: `"domain": "homeassistant"` → `"domain": "light"` (derived from `"light.kitchen"`)
- Line 535: Comment referencing `"domain": "homeassistant"` → update to derived domain

**`tests/unit/test_recording_sync_facade.py`:**
- Line 54: `"domain": "homeassistant"` → `"domain": "light"` (derived from `"light.kitchen"`)
- Line 78: `assert call.kwargs["domain"] == "homeassistant"` → `"light"` (derived from `"light.test"`)
- Line 89: `"domain": "homeassistant"` → `"domain": "switch"` (derived from `"switch.fan"`)
- Line 100: `"domain": "homeassistant"` → `"domain": "light"` (derived from `"light.kitchen"`)

### C. New test coverage

Add the following new tests to `tests/unit/test_recording_api.py`:

1. **Domain derivation test**: `test_turn_on_derives_domain_from_entity_id` — call `api.turn_on("light.kitchen")` with no `domain` arg, assert `call.kwargs["domain"] == "light"`.

2. **Explicit domain override test**: `test_turn_on_uses_explicit_domain` — call `api.turn_on("light.kitchen", domain="homeassistant")`, assert `call.kwargs["domain"] == "homeassistant"`.

3. **turn_off with **data test**: `test_turn_off_captures_extra_data` — call `api.turn_off("light.kitchen", transition=2)`, assert `call.kwargs["transition"] == 2`.

4. **toggle with **data test**: `test_toggle_captures_extra_data` — call `api.toggle("light.kitchen", transition=1)`, assert `call.kwargs["transition"] == 1`.

5. **Domain derivation on turn_off**: `test_turn_off_derives_domain_from_entity_id` — call `api.turn_off("switch.fan")`, assert `call.kwargs["domain"] == "switch"`.

6. **Domain derivation on toggle**: `test_toggle_derives_domain_from_entity_id` — call `api.toggle("light.bedroom")`, assert `call.kwargs["domain"] == "light"`.

### Integration tests (read-only check)

Read `tests/integration/test_app_harness_simulation.py`, `tests/integration/test_drain_iterative.py`, and `tests/integration/test_app_test_harness.py`. These use `self.api.turn_on(...)` and `harness.api_recorder.assert_called("turn_on", ...)`. Verify they still pass — the domain derivation should be transparent to these tests since they don't assert on `domain` in their recorder checks. If any do assert on `domain="homeassistant"`, update them.

### Verification

Run `ptest tests/unit/test_recording_api.py tests/unit/test_recording_sync_facade.py tests/unit/test_api_coroutine_conversion.py tests/unit/test_sync_entity_facade.py tests/unit/test_entity_coroutine_conversion.py tests/unit/test_forgotten_await_completeness.py tests/integration/test_sync_facades.py -n 4 -v` to verify all updated tests pass.

## Focus

- Domain assertions are the most error-prone change — each test hardcodes a specific entity_id, and the derived domain must match the prefix. Double-check each entity_id → derived domain mapping.
- The `test_sync_entity_facade.py` parametrized data at lines 253 and 272 maps `(entity_method_name, api_method_name)` — the entity method is `"toggle"` and the api method was `"toggle_service"`, now both are `"toggle"`.
- `test_forgotten_await_completeness.py` has two separate locations: a list of method names (line 89) and a dict of lambdas (line 219). Both must be updated.
- Integration tests in `tests/integration/` that call `self.api.turn_on(...)` without explicit domain should work unchanged — domain derivation is transparent. But verify by reading the assertion patterns.
- The `harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")` pattern does not check domain, so it should pass without changes.

## Verify

- [ ] FR#1: New test `test_turn_on_derives_domain_from_entity_id` passes — `turn_on("light.kitchen")` records `domain="light"`
- [ ] FR#2: New test `test_turn_on_uses_explicit_domain` passes — `turn_on("light.kitchen", domain="homeassistant")` records `domain="homeassistant"`
- [ ] FR#3: All `toggle_service` references renamed to `toggle` — `grep -r "toggle_service" tests/` returns only comments/docstrings, no code
- [ ] FR#4: New tests `test_turn_off_captures_extra_data` and `test_toggle_captures_extra_data` pass
- [ ] FR#5: `RecordingApi.toggle` records under method name `"toggle"` (existing test updated)
- [ ] AC#1: Test verifies `turn_on("light.kitchen")` dispatches to domain `"light"`
- [ ] AC#2: Test verifies `turn_on("light.kitchen", domain="homeassistant")` dispatches to `"homeassistant"`
- [ ] AC#3: No test references `toggle_service` as a method call
- [ ] AC#4: Test verifies `turn_off` forwards `**data`
- [ ] AC#5: Test verifies `toggle` forwards `**data`
- [ ] AC#6: Test verifies `toggle` records under `"toggle"` method name
- [ ] AC#7: Test verifies `turn_off` captures `**data` in kwargs
- [ ] AC#9: `ptest tests/unit/test_recording_api.py tests/unit/test_recording_sync_facade.py tests/unit/test_api_coroutine_conversion.py tests/unit/test_sync_entity_facade.py tests/unit/test_entity_coroutine_conversion.py tests/unit/test_forgotten_await_completeness.py tests/integration/test_sync_facades.py -n 4` all pass
