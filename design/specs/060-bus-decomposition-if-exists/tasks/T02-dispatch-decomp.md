---
task_id: "T02"
title: "Decompose _dispatch duration path into named helper"
status: "done"
depends_on: []
implements: ["FR#2", "AC#2", "AC#4", "AC#5"]
---

## Summary
Extract the duration timer construction from `_dispatch` in `bus_service.py` into a named method `start_duration_timer`. After extraction, `_dispatch` should be a ~25-line method that builds the invoke function, checks cancellation, and branches on duration vs. non-duration. All existing tests must pass without modification.

## Prompt
Edit `src/hassette/core/bus_service.py` to decompose `_dispatch` (lines 577–664):

1. **`start_duration_timer`** — method on BusService. Extract the `on_duration_fire` nested closure (lines 624–653) and the timer start call. The closure's captured variables (`listener`, `entity_id`, `duration_config`, `invoke_fn`) become explicit parameters. The method creates the callback internally and calls `duration_config.timer.start(callback)` (no `override_duration` — this is the full-duration path, unlike `start_remaining_duration_timer` from T01 which passes `override_duration=remaining`).

After extraction, rewrite `_dispatch` to: build invoke_fn via `_make_tracked_invoke_fn` → check `listener.is_cancelled` → branch on duration (call `start_duration_timer`, return) vs. non-duration (dispatch via `listener.invoker.dispatch(invoke_fn)` + remove if once=True).

Verify the extraction preserves exact behavior by running:
```
timeout 300 uv run pytest tests/unit/bus/ tests/integration/test_bus.py tests/integration/test_bus_immediate.py tests/integration/test_bus_duration.py tests/unit/core/test_bus_service_timeout.py -n 2
```

## Focus
- `_dispatch` is at lines 577–664 in `src/hassette/core/bus_service.py`.
- The nested closure `on_duration_fire` (lines 624–653) captures: `listener`, `entity_id`, `duration_config`, `invoke_fn` (created at line 606), and `self` (implicit).
- `start_duration_timer` is structurally parallel to T01's `start_remaining_duration_timer` but differs: no `override_duration`, and the callback rechecks entity state differently. Do NOT unify them — the design explicitly rejects premature unification.
- `test_bus_service_timeout.py:95` calls `svc._dispatch("test.topic", event, listener)` directly. The signature is NOT changing so this test will still work.
- The non-duration path (lines 659–664) is simple: dispatch + once-removal. It stays inline in `_dispatch` — no extraction needed.

## Verify
- [ ] FR#2: `_dispatch` delegates duration timer construction and lifecycle to `start_duration_timer`, with no inline nested closure
- [ ] AC#2: `_dispatch` is under 30 lines after decomposition
- [ ] AC#4: All existing bus unit and integration tests pass without modification
- [ ] AC#5: No new parameters, return types, or public API changes are introduced
