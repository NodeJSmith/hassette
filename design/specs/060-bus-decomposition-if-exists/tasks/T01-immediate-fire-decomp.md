---
task_id: "T01"
title: "Decompose _immediate_fire_task into focused helpers"
status: "done"
depends_on: []
implements: ["FR#1", "AC#1", "AC#4", "AC#5"]
---

## Summary
Extract three helpers from `_immediate_fire_task` in `bus_service.py`: a state-read wrapper, an elapsed-time computation, and a duration-timer-start method. After extraction, `_immediate_fire_task` should be a ~45-line orchestrator that delegates to named helpers. All existing tests must pass without modification — this is pure refactoring.

## Prompt
Edit `src/hassette/core/bus_service.py` to decompose `_immediate_fire_task` (lines 307–439) into three helpers:

1. **`read_current_state(hassette, entity_id, listener, logger)`** — module-level async function. Extract the StateProxy read block (lines 335–350) that fetches current entity state, handles `ResourceNotReadyError` (returns None), and catches generic exceptions (logs error, returns None). Returns `HassStateDict | None`.

2. **`compute_elapsed(current_state, duration_config)`** — module-level function. Extract the elapsed-time calculation (lines 364–380) that computes how long the entity has been in its current state. Takes the current state dict and the duration config, returns `float`. For attribute listeners, returns 0.0 (they don't track elapsed time the same way).

3. **`start_remaining_duration_timer`** — method on BusService. Extract the `on_duration_fire_immediate` nested closure (lines 391–412) and the timer start call. The closure's captured variables (`listener`, `entity_id`, `invoke_fn`, `duration_config`) become explicit parameters. The method creates the callback internally and calls `duration_config.timer.start(callback, override_duration=remaining)`.

After extraction, rewrite `_immediate_fire_task` to call these helpers in sequence: validate entity_id → `read_current_state` → build synthetic event → check predicate → build invoke_fn → branch on duration (call `start_remaining_duration_timer`) vs. non-duration (dispatch + once-removal).

Verify the extraction preserves exact behavior by running:
```
timeout 300 uv run pytest tests/unit/bus/ tests/integration/test_bus.py tests/integration/test_bus_immediate.py tests/integration/test_bus_duration.py tests/unit/core/test_bus_service_timeout.py -n 2
```

## Focus
- `_immediate_fire_task` is at lines 307–439 in `src/hassette/core/bus_service.py`.
- The nested closure `on_duration_fire_immediate` (lines 391–412) captures: `listener`, `entity_id`, `invoke_fn` (created at line 360), and `self` (implicit). All captured variables must become explicit parameters on `start_remaining_duration_timer`.
- Existing helpers already called: `_make_synthetic_state_event` (lines 280–295), `_make_tracked_invoke_fn` (lines 666–709), `_read_entity_state` (lines 567–570), `_hold_matches` (lines 297–305). These are NOT being moved — `_immediate_fire_task` still calls them.
- `read_current_state` and `compute_elapsed` are module-level (no `self`). `start_remaining_duration_timer` is a method because it needs `self._read_entity_state`, `self._hold_matches`, `self.remove_listener`.
- No underscore prefix on the new module-level functions.
- `test_bus_service_timeout.py:95` calls `svc._dispatch()` directly — unrelated to this task but confirms the test suite exercises these paths.

## Verify
- [ ] FR#1: `_immediate_fire_task` delegates state reading to `read_current_state`, elapsed-time to `compute_elapsed`, and duration timer to `start_remaining_duration_timer`
- [ ] AC#1: `_immediate_fire_task` is under 50 lines; each extracted helper is under 30 lines
- [ ] AC#4: All existing bus unit and integration tests pass without modification
- [ ] AC#5: No new parameters, return types, or public API changes are introduced
