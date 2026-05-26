---
task_id: "T03"
title: "Extract DurationHoldManager to bus/duration_hold.py"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#5", "FR#6", "AC#3", "AC#4", "AC#6"]
---

## Summary
Create `src/hassette/bus/duration_hold.py` containing the `DurationHoldManager` class and the `compute_elapsed` module-level function. This is the largest extraction (~220 lines) and handles the duration hold lifecycle: immediate fire, full/remaining timer start, cancel listener creation, and hold predicate matching. Depends on T01 because it imports `build_tracked_invoke_fn` from the sibling invocation module.

## Prompt
1. Create `src/hassette/bus/duration_hold.py` with:
   - Module docstring (one line)
   - `DurationHoldManager` class with `__init__` accepting:
     - `executor: CommandExecutor` — passed through to `build_tracked_invoke_fn`
     - `config_resolver: Callable[[], float | None]` — lazy timeout reader, passed through to `build_tracked_invoke_fn`
     - `state_reader: Callable[[str], HassStateDict | None]` — reads entity state, returns None on failure (all error handling absorbed by caller)
     - `remove_listener: Callable[[Listener], None]` — idempotent listener removal
     - `router: Router` — for cancel listener route insertion
     - `task_bucket: TaskBucket` — for spawning background tasks
     - `logger: logging.Logger`
   - Instance attribute: `duration_timers_active: int = 0` (exposed as property)
   - Methods moved from BusService (preserve logic unchanged):
     - `async immediate_fire_task(listener)` — from `bus_service.py:330-403`
     - `start_duration_timer(listener, entity_id, duration_config, invoke_fn)` — from `bus_service.py:440-481`
     - `start_remaining_duration_timer(listener, entity_id, duration_config, invoke_fn, remaining)` — from `bus_service.py:405-438`
     - `create_cancel_listener(main_listener)` — from `bus_service.py:177-226`
     - `hold_matches(listener, event)` — from `bus_service.py:320-328`
     - `make_synthetic_state_event(entity_id, current_state)` — from `bus_service.py:303-318`

2. Move `compute_elapsed` (bus_service.py:922-946) as a module-level function — logic unchanged.

3. In `immediate_fire_task`: replace `self._make_tracked_invoke_fn(...)` with a direct call to `build_tracked_invoke_fn(listener, event, topic, self.executor, self.config_resolver, is_synthetic=True)`. Replace `self._read_entity_state(entity_id)` with `self.state_reader(entity_id)`. Replace `self.remove_listener(listener)` with `self.remove_listener(listener)`.

4. In `start_duration_timer` and `start_remaining_duration_timer`: replace `self._read_entity_state` with `self.state_reader`. Replace `self.remove_listener` with `self.remove_listener`. Timer fire callbacks do NOT touch dispatch tracking.

5. In `create_cancel_listener`: use `self.router.add_route(...)` directly. Use `self.task_bucket` for the cancel listener's task_bucket parameter.

6. Write unit tests in `tests/unit/bus/test_duration_hold.py`:
   - Test `DurationHoldManager` is constructable with mock callbacks (sync test)
   - Test `immediate_fire_task` calls `state_reader`, builds invoke_fn, dispatches (async test)
   - Test `immediate_fire_task` returns early when `state_reader` returns None (async test)
   - Test `start_duration_timer` increments `duration_timers_active` and starts timer
   - Test `hold_matches` delegates to hold_predicate or falls back to listener.matches
   - Test `create_cancel_listener` inserts route and returns Subscription (async test)
   - Test `compute_elapsed` edge cases (attribute listener → 0.0, missing last_changed → 0.0)

7. Do NOT modify `bus_service.py` yet — that happens in T04.

## Focus
- `immediate_fire_task` is the most complex method (~70 lines). Read it carefully at `bus_service.py:330-403`. It has multiple branches: entity not found, predicate doesn't match, duration with elapsed >= duration, duration with remaining, non-duration immediate.
- `create_cancel_listener` calls `asyncio.get_running_loop().create_future()` — tests that call it must be async.
- Duration timer `on_duration_fire` closures decrement `self._duration_timers_active` in `finally` — preserve this.
- The `on_duration_fire` closures call `self.remove_listener(listener)` when `listener.options.once` is True — this is the idempotent `remove_listener` callback.
- `DurationTimer` class is at `src/hassette/bus/duration_timer.py` — do not modify it.
- `Listener.create_cancel_listener` class method is at `src/hassette/bus/listeners.py` — used by `create_cancel_listener`.
- Import `build_tracked_invoke_fn` from `.invocation` (sibling import).

## Verify
- [ ] FR#1: `DurationHoldManager` exists with all 6 methods listed in the design doc Architecture section
- [ ] FR#5: Constructor accepts `executor`, `config_resolver`, `state_reader`, `remove_listener`, `router`, `task_bucket`, `logger` (no BusService reference)
- [ ] FR#6: `compute_elapsed` exists as a module-level function in `duration_hold.py`
- [ ] AC#3: `uv run pyright` reports no new type errors
- [ ] AC#4: `uv run pytest tests/unit/bus/test_duration_hold.py` passes (no circular imports)
- [ ] AC#6: Unit tests construct `DurationHoldManager` with mock callbacks without importing BusService
