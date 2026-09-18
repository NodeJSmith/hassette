# Context: Bus.wait_for()

## Problem & Motivation
Hassette's `call_service` is fire-and-forget. A bedtime automation's "TTS speak → 13 HA calls → play white noise" sequence completed in 14–20ms — none of the calls block. App authors who need sequential logic must hand-roll the composition: create a future, register a one-shot listener, fire the command, await the future with a timeout. Getting the ordering wrong (arm after fire) is a silent race. The framework needs a primitive for "suspend this coroutine until a matching event arrives."

## Visual Artifacts
None.

## Key Decisions
1. **Follow the `send_and_await_response` Future-bridge pattern** from `WebsocketService` — create future, register before action, await with timeout, cleanup in `finally`. Not `send_and_wait`, which adds retry logic.
2. **Go through `_on_internal(once=True)`** for registration — reuses the full listener pipeline (predicates, DB registration, auto-cleanup). No new listener type.
3. **Cleanup via existing `_on_listener_removed` callback** — extend it to cancel futures, rather than a separate shutdown loop. Fires on all removal paths (shutdown, explicit cancel, once-fire). Uses `fut.cancel()` (not `set_exception`).
4. **No new exception type** — callers get standard `CancelledError` on shutdown. `WebsocketService` uses `set_exception` because retry logic reads the type; `wait_for` has no retry logic.
5. **Stateless name generation** — `f"_wait_for_{id(fut):x}"` instead of a counter field.
6. **Only match new events** — pre-existing state does not resolve the wait. Events dispatched before the `wait_for` call are ignored. There is no parameter to change this behavior in v1.
7. **Threshold warning at 20 pending futures** — makes a leak from a buggy retry loop observable.

## Constraints & Anti-Patterns
- Do NOT modify `ListenerNameRequiredError` validation or `_require_name` — generate the name at the `wait_for` level.
- Do NOT use `guard_await` — `wait_for` returns `Event[Any]`, not `Subscription`.
- Do NOT add a `state_check_now` parameter — that's a future enhancement.
- Do NOT add `BusShutdownError` or any new exception type.
- Do NOT create a separate shutdown cleanup loop — use `_on_listener_removed`.
- `call_and_wait` composition is out of scope (#2286).
- The arm-before-fire composition pattern via `create_task` has a theoretical race window (documented, accepted). The race-free composition is #2286.

## Design Doc References
- `## Architecture` — core implementation details, code leverage table, handler signature, cleanup mechanism
- `## Functional Requirements` — 11 FRs defining wait_for behavior
- `## Edge Cases` — shutdown, concurrent waits, registration race, auto-name collisions
- `## Test Strategy` — unit, integration, and system test requirements
- `## Documentation Updates` — docs pages and recipes to write
- `## Convention Examples` — send_and_await_response pattern, _on_listener_removed, _on_internal delegation, once=True guard

## Convention Examples

### Future-bridge pattern (send_and_await_response)

**Source:** `src/hassette/core/websocket_service.py:549-578`

```python
fut = self.hassette.loop.create_future()
self._response_futures[msg_id] = fut
try:
    await self.send_json(**payload)
    return await asyncio.wait_for(fut, timeout=self.resp_timeout_seconds)
finally:
    self._response_futures.pop(msg_id, None)
```

### Listener removal callback (cleanup hook)

**Source:** `src/hassette/bus/bus.py:174-201`

`_on_listener_removed` is wired via `register_removal_callback` and fires on every listener death — shutdown, explicit cancel, and once-fire. `wait_for` extends this callback to cancel the associated future (guarded by `not fut.done()` so successful matches aren't affected).

### Bus registration via _on_internal

**Source:** `src/hassette/bus/bus.py:531-624`

All public registration methods (`on`, `on_state_change`, etc.) delegate to `_on_internal` with `once=True/False` and the appropriate parameters. `wait_for` follows this same delegation pattern.

### once=True guard in HandlerInvoker.dispatch

**Source:** `src/hassette/bus/listeners.py:267-294`

```python
if self.once and self.fired:
    return
if self.once:
    self.mark_fired()
```

### Bus unit test pattern

**Source:** `tests/unit/bus/test_bus.py`

Function-scoped `hassette_with_bus` → `bus` fixture. Tests use `mock_add_listener(bus)` context manager to stub `bus_service.add_listener`. Direct `await bus.on(...)` calls, assert on `subscription.listener` fields.
