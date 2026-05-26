---
task_id: "T04"
title: "Rewire BusService to delegate to extracted modules"
status: "planned"
depends_on: ["T01", "T02", "T03"]
implements: ["FR#4", "AC#1", "AC#2", "AC#5"]
---

## Summary
Modify `src/hassette/core/bus_service.py` to use the three extracted modules. This is the integration task: construct `EventFilter` and `DurationHoldManager` in `__init__`, replace inline method calls with delegations, and delete the now-extracted methods. The public API surface remains unchanged — external consumers don't need any modifications.

## Prompt
1. In `bus_service.py` `__init__`:
   - Construct `EventFilter` with `self.hassette.config.bus_excluded_domains`, `self.hassette.config.bus_excluded_entities`, and `self.logger`
   - Construct `DurationHoldManager` with:
     - `executor=self._executor`
     - `config_resolver=lambda: self.hassette.config.lifecycle.event_handler_timeout_seconds` (MUST be a lambda, not a captured value)
     - `state_reader=self._read_entity_state` (a method that absorbs ResourceNotReadyError — see step 2)
     - `remove_listener=self.remove_listener`
     - `router=self.router`
     - `task_bucket=self.task_bucket`
     - `logger=self.logger`
   - Remove `self._setup_exclusion_filters()` call and all exclusion-related instance attributes

2. Rewrite `_read_entity_state` to absorb error handling (becomes the `state_reader` callback):
   - Wrap `state_proxy.states.get(entity_id)` with try/except for `ResourceNotReadyError` and generic Exception
   - Return None on any failure, log at appropriate level
   - This combines the logic from the old `_read_entity_state` (bare read) and `read_current_state` (error-handled read)

3. Replace delegation points:
   - `dispatch()`: replace `self._should_skip_event(...)` with `self._event_filter.should_skip(...)`
   - `_dispatch()`: replace `self._make_tracked_invoke_fn(topic, event, listener)` with `build_tracked_invoke_fn(listener, event, topic, self._executor, lambda: self.hassette.config.lifecycle.event_handler_timeout_seconds, is_synthetic=False)`. For the duration path, delegate to `self._duration_hold.start_duration_timer(...)`.
   - `add_listener()`: delegate duration wiring to `self._duration_hold.create_cancel_listener(...)` where currently `self._create_cancel_listener(...)` is called. Delegate immediate fire task logic (but keep the spawn + done-callback in `add_listener` since dispatch tracking stays here).
   - `duration_timers_active` property: delegate to `self._duration_hold.duration_timers_active`

4. Delete extracted methods from `bus_service.py`:
   - `_setup_exclusion_filters`, `_should_skip_event` (moved to EventFilter)
   - `_make_tracked_invoke_fn` (moved to invocation.py)
   - `_immediate_fire_task`, `start_duration_timer`, `start_remaining_duration_timer`, `_create_cancel_listener`, `_hold_matches`, `_make_synthetic_state_event` (moved to DurationHoldManager)
   - Module-level `read_current_state`, `compute_elapsed` (moved/absorbed)

5. Delete moved constants: `_SYSTEM_LOG_SKIP_EVENT_TYPE`, `_SYSTEM_LOG_SKIP_DOMAIN`, `_SYSTEM_LOG_SKIP_LEVEL`

6. Update imports at top of `bus_service.py`:
   - Add: `from hassette.bus.invocation import build_tracked_invoke_fn`
   - Add: `from hassette.bus.duration_hold import DurationHoldManager`
   - Add: `from hassette.core.event_filter import EventFilter`
   - Remove imports that are no longer needed (e.g., `uuid4` if only used by `_make_synthetic_state_event`)

7. Update existing tests that call `_make_tracked_invoke_fn` directly:
   - `tests/unit/core/test_bus_service_timeout.py` — rewrite to call `build_tracked_invoke_fn()` directly with mock executor and config_resolver
   - `tests/unit/core/test_bus_service_error_handler.py` — rewrite to call `build_tracked_invoke_fn()` directly with mock executor and config_resolver
   - `tests/unit/core/test_bus_service_public_accessors.py` — update fixture if needed (BusService constructor still takes same params, but verify `make_mock_hassette()` provides the config fields EventFilter needs)

8. Run the full test suite: `timeout 300 uv run pytest -n 2 -x` to verify all behavioral invariants hold.

## Focus
- The `add_listener` method (bus_service.py:121-175) is the trickiest integration point. It currently:
  - Wires duration timer via `duration_config.attach_timer(...)` — this stays
  - Creates cancel listener via `self._create_cancel_listener(listener)` → delegate to `self._duration_hold.create_cancel_listener(listener)`
  - Spawns immediate fire task and wires dispatch tracking — the spawn and `_on_dispatch_done` callback stay in BusService, but the task body delegates to `self._duration_hold.immediate_fire_task(listener)`
- `_dispatch` (bus_service.py:617-671) has two paths: duration (delegates to manager) and non-duration (stays inline). The invoke_fn is built by `build_tracked_invoke_fn` in both cases.
- The `config_resolver` lambda MUST be `lambda: self.hassette.config.lifecycle.event_handler_timeout_seconds` — not a captured value. This is critical for hot-reload correctness.
- External consumers (`bus/bus.py`, `core/app_handler.py`, `core/service_watcher.py`, etc.) should need ZERO changes — verify with grep after.
- Target: `bus_service.py` should be under 500 lines after this task.
- The `docstring` reference in `core/commands.py:48` mentioning `BusService._make_tracked_invoke_fn()` should be updated to reference `build_tracked_invoke_fn` in `bus/invocation.py`.

## Verify
- [ ] FR#4: All public methods on BusService still exist with same signatures; `grep -n "bus_service\." src/hassette/` shows no broken references
- [ ] AC#1: `wc -l src/hassette/core/bus_service.py` shows under 500 lines
- [ ] AC#2: `timeout 300 uv run pytest -n 2 -x` passes (full suite)
- [ ] AC#5: No changes needed in `src/hassette/bus/bus.py`, `src/hassette/core/app_handler.py`, `src/hassette/core/service_watcher.py`, `src/hassette/core/runtime_query_service.py`, `src/hassette/core/state_proxy.py`, `src/hassette/test_utils/harness.py`, `src/hassette/test_utils/simulation.py`
