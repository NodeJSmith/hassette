---
task_id: "T01"
title: "Add Bus.wait_for() method with future registry and cleanup"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "FR#8", "FR#9", "FR#10", "FR#11", "AC#1", "AC#2", "AC#3", "AC#4", "AC#5"]
---

## Summary
Add the `wait_for` method to `Bus` — the core primitive that suspends a coroutine until a matching event arrives. Includes the `_wait_for_futures` registry, the `_on_listener_removed` cleanup extension, auto-generated naming via `id(fut)`, logging at DEBUG (match/timeout) and WARNING (shutdown cleanup count, threshold crossing at 20), and unit tests for every FR.

## Target Files
- modify: `src/hassette/bus/bus.py`
- read: `src/hassette/bus/listeners.py`
- read: `src/hassette/core/websocket_service.py`
- read: `src/hassette/exceptions.py`
- read: `tests/unit/bus/conftest.py`
- create: `tests/unit/bus/test_wait_for.py`

## Prompt
Add `Bus.wait_for(topic, *, where=None, timeout, name=None)` to `src/hassette/bus/bus.py`. Follow the `send_and_await_response` Future-bridge pattern from `websocket_service.py:549-578`.

### Implementation steps

1. **Add `_wait_for_futures: dict[int, asyncio.Future]` to `Bus.__init__()`** — parallel to `WebsocketService._response_futures`. Keyed by listener `db_id`.

2. **Add `wait_for` method** (async, returns `Event[Any]`):
   - Create `fut = self.hassette.loop.create_future()`.
   - Define handler closure: `def _handler(event): if not fut.done(): fut.set_result(event)`.
   - Generate name if not provided: `f"_wait_for_{id(fut):x}"`.
   - Register via `await self._on_internal(topic=topic, handler=_handler, once=True, where=where, name=name, ...)`. Pass the remaining `_on_internal` kwargs as their defaults (no debounce, throttle, timeout, etc.).
   - Store `self._wait_for_futures[subscription.listener.db_id] = fut`.
   - Check threshold: if `len(self._wait_for_futures) >= 20` and previous count was below, log WARNING.
   - `try: return await asyncio.wait_for(fut, timeout=timeout)` / `finally: self._wait_for_futures.pop(db_id, None); subscription.cancel()`.
   - Log at DEBUG on successful match. On `asyncio.TimeoutError`, log at DEBUG before re-raising.
   - Do NOT wrap with `guard_await` — `wait_for` returns `Event[Any]`, not `Subscription`.

3. **Extend `_on_listener_removed`** — after the existing body, add:
   ```python
   fut = self._wait_for_futures.pop(listener.db_id, None)
   if fut is not None and not fut.done():
       fut.cancel()
   ```
   Log at WARNING when cancelling during shutdown (include count of futures cancelled).

4. **Unit tests** in `tests/unit/bus/test_wait_for.py`. Use the existing `hassette_with_bus` / `bus` fixture from `tests/unit/bus/conftest.py` and the `mock_add_listener` context manager. Test each FR:
   - FR#1: Dispatch a matching event → future resolves with that event
   - FR#2: Dispatch event before `wait_for` call → does not resolve (only new events match)
   - FR#3: No matching event → `asyncio.TimeoutError` after timeout
   - FR#4: `timeout=None` accepted (verify no timeout enforcement)
   - FR#5: Auto-generated name (`_wait_for_` prefix) when `name=` omitted
   - FR#6: User-provided name passed through to listener
   - FR#7: Listener is removed after firing (once=True auto-cleanup)
   - FR#8: Call `_on_listener_removed` on the listener → future is cancelled, caller gets `CancelledError`
   - FR#9: WhereClause filtering works (predicate matches/rejects)
   - FR#10: `wait_for` return is NOT wrapped in `guard_await`
   - FR#11: WARNING logged when pending futures cross threshold of 20
   - Multiple concurrent waits on same topic resolve independently

Write a Google-style docstring on `Bus.wait_for` — parameter descriptions, return type, exceptions raised (`asyncio.TimeoutError`, `CancelledError`).

See `## Convention Examples` in context.md for the patterns to follow.

## Focus
- `_on_internal` signature is large — pass only the parameters `wait_for` needs (`topic`, `handler`, `once=True`, `where`, `name`), defaulting the rest. Check `bus.py:531-624` for the full parameter list and their defaults.
- The handler closure takes a single `event` parameter — `HandlerInvoker.create()` builds a `ParameterInjector` that matches automatically.
- `_require_name` at `bus.py:128-130` checks `name` on every registration path. `wait_for` bypasses this by always supplying a name (auto-generated or user-provided) before reaching `_on_internal`.
- `subscription.listener.db_id` is a valid integer immediately when the awaited `_on_internal` call returns — no registration task to await.
- The `_on_listener_removed` callback at `bus.py:174-201` is already used for telemetry bookkeeping. Extend it, don't replace it.
- For the threshold warning, track whether we're already above the threshold to avoid repeated warnings. A simple `_above_threshold: bool` flag (or just checking `len(...) == 20` for crossing detection) is sufficient.

## Verify
- [ ] FR#1: `await bus.wait_for("test_topic", timeout=5)` returns the matching event when dispatched
- [ ] FR#2: Events dispatched before the `wait_for` call do not resolve the wait
- [ ] FR#3: `wait_for` raises `asyncio.TimeoutError` when no matching event arrives within timeout
- [ ] FR#4: `timeout=None` is accepted and does not raise
- [ ] FR#5: Omitting `name=` registers a listener with `_wait_for_` prefix
- [ ] FR#6: Providing `name=` uses that name for the listener
- [ ] FR#7: The listener is removed after once-fire
- [ ] FR#8: `_on_listener_removed` cancels the future; caller receives `CancelledError`
- [ ] FR#9: WhereClause predicates filter events correctly
- [ ] FR#10: Return value is not wrapped in `guard_await`
- [ ] FR#11: WARNING logged when pending futures count crosses 20
- [ ] AC#1: Full wait_for call with `P.EntityId` and `P.StateTo` predicates returns the matching event
- [ ] AC#2: TimeoutError raised on expiry
- [ ] AC#3: Pre-dispatch events do not resolve the wait
- [ ] AC#4: Shutdown/removal cancels the future with CancelledError
- [ ] AC#5: Auto-generated name works without `name=` argument
