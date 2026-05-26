---
task_id: "T01"
title: "Extract build_tracked_invoke_fn to bus/invocation.py"
status: "planned"
depends_on: []
implements: ["FR#2", "AC#3", "AC#4"]
---

## Summary
Create `src/hassette/bus/invocation.py` containing the `build_tracked_invoke_fn` module-level function. This is the foundation other tasks depend on — DurationHoldManager and BusService both call this function. Extract the logic from `BusService._make_tracked_invoke_fn` (bus_service.py:673-715) into a standalone function with explicit parameters instead of `self` access.

## Prompt
1. Create `src/hassette/bus/invocation.py` with:
   - A module-level function `build_tracked_invoke_fn(listener, event, topic, executor, config_resolver, is_synthetic=False)` that returns `Callable[[], Awaitable[None]]`
   - The function body is the `execute_fn` closure from `bus_service.py:687-713`, adapted to use the explicit parameters instead of `self._executor` and `self.hassette.config.lifecycle.event_handler_timeout_seconds`
   - `config_resolver` is `Callable[[], float | None]` — called lazily at fire time (not capture time) to preserve hot-reload correctness for debounced handlers
   - Timeout resolution logic: `listener.options.timeout_disabled` → None; `listener.options.timeout` → that value; else → `config_resolver()`
   - Error handler resolution: `listener.invoker.app_error_handler_resolver`
   - Constructs `InvokeHandler` command and calls `await executor.execute(cmd)`

2. Imports needed:
   - `from hassette.core.commands import InvokeHandler`
   - `from hassette.bus.listeners import Listener`
   - `from hassette.events.base import Event`
   - Type imports under `TYPE_CHECKING`: `CommandExecutor`, `Awaitable`, `Callable`

3. Write unit tests in `tests/unit/bus/test_invocation.py`:
   - Test timeout resolution: disabled → None, per-listener → value, config default → config_resolver() return value
   - Test InvokeHandler construction with correct fields (listener_id read lazily from listener.db_id)
   - Test that executor.execute is called with the constructed command
   - Test is_synthetic flag propagation
   - Use mock executor (AsyncMock) and mock config_resolver

4. Do NOT modify `bus_service.py` yet — that happens in T04.

## Focus
- The existing `_make_tracked_invoke_fn` is at `src/hassette/core/bus_service.py:673-715`
- `InvokeHandler` dataclass is at `src/hassette/core/commands.py:16-57`
- The `config_resolver` must be a callable, not a value — the lazy-read guarantee is load-bearing for debounced handlers (see design doc Architecture section)
- `core/commands.py` imports from `bus/listeners.py` — verified non-circular with `bus/invocation.py` importing `core/commands.py`
- Follow the module docstring pattern from `src/hassette/core/registration_tracker.py` — brief one-line summary of what the module encapsulates

## Verify
- [ ] FR#2: `build_tracked_invoke_fn` exists as a module-level function in `src/hassette/bus/invocation.py` with the 6-parameter signature
- [ ] AC#3: `uv run pyright` reports no new type errors
- [ ] AC#4: `uv run pytest tests/unit/bus/test_invocation.py` passes (confirms no circular imports at import time)
