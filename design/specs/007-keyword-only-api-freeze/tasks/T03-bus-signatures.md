---
task_id: "T03"
title: "Lock bus registration signatures, require name, add on_error passthrough"
status: "planned"
depends_on: []
implements: ["FR#2", "FR#3", "FR#9", "AC#1", "AC#3", "AC#5", "AC#6"]
---

## Summary
Add `*` to the 3 `on_homeassistant_*` methods, change `name` from `str | None = None` to `str` (required, no default) on all Bus registration methods, update the runtime check from `is None` to `not name` (extending rejection to empty strings), add `on_error` passthrough to 10 delegate methods, and update ~77 bus test call sites with explicit `name=`. Add new tests for keyword-only enforcement, empty-string rejection, and on_error passthrough across all 4 delegation chains.

## Target Files
- modify: `src/hassette/bus/bus.py`
- modify: `tests/unit/bus/test_registration_errors.py`
- modify: `tests/unit/bus/test_registration_parity.py`
- modify: `tests/integration/test_registration.py`
- modify: `tests/integration/bus/test_bus_error_handler_combos.py`
- modify: `tests/integration/bus/test_bus_immediate.py`
- modify: `tests/integration/test_app_test_harness.py`
- modify: `tests/unit/test_forgotten_await_completeness.py`
- read: `src/hassette/bus/options.py` (Options TypedDict for reference)

## Prompt
In `src/hassette/bus/bus.py`, make these changes:

**1. Add `*` to 3 methods** — `on_homeassistant_restart`, `on_homeassistant_start`, `on_homeassistant_stop` currently have no `*` separator. Add `*` after `self` to make `handler`, `where`, `kwargs`, `name` keyword-only, matching every sibling `on_*` method.

**2. Change `name` type on ALL registration methods** from `name: str | None = None` to `name: str` (no default). This affects: `on`, `on_state_change`, `on_attribute_change`, `on_call_service`, `on_component_loaded`, `on_service_registered`, `on_homeassistant_restart`, `on_homeassistant_start`, `on_homeassistant_stop`, `on_hassette_service_status`, `on_hassette_service_failed`, `on_hassette_service_crashed`, `on_hassette_service_started`, `on_websocket_connected`, `on_websocket_disconnected`, `on_app_state_changed`, `on_app_running`, `on_app_stopping`.

**3. Update runtime check** — find the `_require_name` method or the name check logic (currently checks `name is None`). Change it to check `not name` so empty strings are also rejected via `ListenerNameRequiredError`.

**4. Add `on_error` parameter** to these 10 delegate methods and forward it to their underlying primary:
- `on_homeassistant_restart`, `on_homeassistant_start`, `on_homeassistant_stop` → forward to `on_call_service(..., on_error=on_error)`
- `on_hassette_service_failed`, `on_hassette_service_crashed`, `on_hassette_service_started` → forward to `on_hassette_service_status(..., on_error=on_error)`
- `on_websocket_connected`, `on_websocket_disconnected` → forward to `on(..., on_error=on_error)`
- `on_app_running`, `on_app_stopping` → forward to `on_app_state_changed(..., on_error=on_error)`

The parameter type is `on_error: "BusErrorHandlerType | None" = None`. Check existing methods that already have `on_error` (e.g., `on_state_change`) for the exact type import and placement pattern.

**5. Update docstrings** on all changed methods: document `name` as required, add `on_error` parameter docs to the 10 delegate methods.

**6. Add new tests:**
- In `tests/unit/bus/test_registration_errors.py`: test `ListenerNameRequiredError` for empty string `name=""` (new behavior, AC#5)
- Representative test that `on_homeassistant_start(handler, ...)` with positional `handler` raises `TypeError` (AC#3)
- On_error passthrough tests — one per delegation chain (4 tests total):
  - `on_homeassistant_start` → verify `on_error` fires via `on_call_service`
  - `on_hassette_service_failed` → verify `on_error` fires via `on_hassette_service_status`
  - `on_websocket_connected` → verify `on_error` fires via `on()`
  - `on_app_running` → verify `on_error` fires via `on_app_state_changed`

**7. Bulk test update**: Add `name="test_xyz"` to all ~77 bus test call sites that currently omit `name=`. Use grep: `grep -rn 'bus\.\(on_state_change\|on_attribute_change\|on_call_service\|on_homeassistant\|on_component_loaded\|on_service_registered\|on_hassette_service\|on_websocket\|on_app_state\|on_app_running\|on_app_stopping\|on\b\)(' tests/ | grep -v 'name='`

## Focus
The `_require_name` function/method in bus.py handles the name validation. Find it and update the condition. The existing `ListenerNameRequiredError` message includes a code example — verify the example still makes sense after the type change.

The `BusSyncFacade` in `sync.py` is auto-generated — do NOT edit it. T04 handles regeneration.

For on_error passthrough: each delegate method currently accepts `**opts: Unpack[Options]` for shared behavioral params. `on_error` is NOT in `Options` — it must be added as an explicit parameter alongside `name`, `where`, `kwargs`. Check how `on_state_change` handles `on_error` for the exact pattern.

The `on_homeassistant_*` methods currently delegate to `on_call_service("homeassistant", ...)`. After adding `*`, the internal delegation in `bus.py` itself also needs keyword args if any are currently positional.

## Verify
- [ ] FR#2: `on_homeassistant_start(handler, ...)` with positional `handler` raises `TypeError`
- [ ] FR#3: `uv run pyright` reports error when any Bus method called without `name=`
- [ ] FR#9: `on_error` handler fires when passed to each of the 10 delegate methods
- [ ] AC#1: Pyright catches missing `name=` on Bus registration calls
- [ ] AC#3: Positional `handler` on `on_homeassistant_start` raises `TypeError`
- [ ] AC#5: `ListenerNameRequiredError` raised when `name=""` passed (new: empty string rejection)
- [ ] AC#6: `on_error` fires on all 4 delegation chains
