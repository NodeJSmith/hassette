# Design: Bus.wait_for()

**Date:** 2026-09-17
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-09-17-wait-for-event-consumption/research.md

## Problem

Hassette's `call_service` is fire-and-forget by default. A bedtime automation's entire "TTS speak → 13 HA calls → play white noise" sequence completed in 14–20ms — none of the calls block. App authors who need sequential logic (call a service, wait for the effect, then proceed) must hand-roll the composition: snapshot state before the call, arm a one-shot listener, fire the command, await the listener with a timeout. Getting the ordering wrong (arm after fire) is a silent race that works locally but fails under real latency. The framework provides no primitive for "suspend this coroutine until a matching event arrives."

## Goals

- App authors can await a single matching event from the Bus without hand-rolling listener-to-future wiring.
- The primitive composes naturally with `call_service` via the documented arm-before-fire pattern.
- Pending waits are cleaned up on Bus shutdown — no hanging coroutines.
- One-shot waits don't require inventing a telemetry-meaningful name.

## Non-Goals

- `call_and_wait` composition (filed as #2286 — depends on this primitive).
- `state_check_now` parameter to match pre-existing state before blocking (future enhancement).
- `stream()` async iterator for multi-event consumption (Tier 3 from prior art brief).
- `since=` / timestamp filtering for stale-event discrimination.
- Custom timeout exception with richer context (standard `asyncio.TimeoutError` is sufficient for v1).

## User Scenarios

### App author: Automation developer

- **Goal:** Write sequential automations that wait for physical effects before proceeding.
- **Context:** Inside an `App.on_initialize()` or event handler, after calling a Home Assistant service.

#### Wait for a state change

1. **Arm a wait before a service call**
   - Sees: `bus.wait_for()` in the API
   - Decides: Which topic and predicate to match
   - Then: Creates an `asyncio.Task` wrapping `wait_for`, calls the service, awaits the task

2. **Event arrives and resolves the wait**
   - Sees: The matched `Event` object returned
   - Then: Proceeds with the next step in the automation

3. **Timeout expires without a match**
   - Sees: `asyncio.TimeoutError` raised
   - Decides: Whether to retry, skip, or abort

#### Simple one-shot wait (no service call)

1. **Wait for a sensor reading or external event**
   - Sees: `bus.wait_for()` suspends until the event arrives
   - Then: Uses the event data to drive the next action

## Functional Requirements

- **FR#1** `Bus.wait_for(topic, *, where=None, timeout, name=None)` suspends the calling coroutine until an event matching `topic` and `where` is dispatched through the Bus, then returns that event.
- **FR#2** `wait_for` only matches events dispatched after the call — pre-existing state does not resolve the wait.
- **FR#3** If no matching event arrives within `timeout` seconds, `asyncio.TimeoutError` is raised.
- **FR#4** `timeout` is a mandatory parameter with no default. `None` is accepted to mean "no timeout" for power users.
- **FR#5** `name` is optional. When omitted, an auto-generated name derived from the future's identity (e.g., `_wait_for_7f8a3b2c`) is used for the underlying listener registration.
- **FR#6** When a user-provided `name` is passed, it is used as the listener name (same semantics as other Bus registration methods).
- **FR#7** The underlying listener uses `once=True` and is automatically removed after firing or on cancellation/timeout.
- **FR#8** On listener removal due to shutdown or explicit cancellation, the associated `wait_for` future is cancelled — callers receive `CancelledError` and are unblocked. (On successful once-fire, the handler has already resolved the future with `set_result` before removal fires, so the `not fut.done()` guard skips cancellation.)
- **FR#9** `wait_for` accepts the same `where` parameter as other Bus registration methods (`WhereClause` — predicates, conditions, accessors).
- **FR#10** `wait_for` does not use `guard_await` — it returns `Event[Any]`, not `Subscription`, and Python's own coroutine-not-awaited warning covers the forgotten-await case.
- **FR#11** When the number of pending `wait_for` futures on a Bus instance crosses a threshold (20), a WARNING is logged. This makes a leak from a buggy retry loop observable without adding backpressure machinery.

## Edge Cases

- **Shutdown during wait:** A coroutine suspended on `wait_for` when Bus shuts down receives `CancelledError` via `fut.cancel()`. Cleanup is driven by the existing `_on_listener_removed` callback, which fires on all listener removal paths (shutdown, explicit cancel, once-fire).
- **Multiple concurrent waits for the same topic:** Each `wait_for` call creates its own independent listener and future. Multiple concurrent waits on the same topic are allowed and resolve independently.
- **Predicate that never matches:** The wait eventually times out (FR#3). If `timeout=None`, the wait persists until shutdown cleanup (FR#8).
- **Event dispatched between registration and await (simple case):** Safe for direct `await self.bus.wait_for(...)` — registration completes (including the DB write in `BusService.add_listener`) before the wait begins, so the listener is routable before any event could match. The future is created before the handler can fire.
- **Event dispatched during arm-before-fire composition:** The `create_task(wait_for(...))` then `call_service(...)` recipe has a theoretical race window: the task starts but may not have completed the `_on_internal` DB write (making the listener routable) before `call_service`'s WebSocket round-trip completes and triggers the event. In practice the local SQLite write (~1ms) wins against the WS round-trip (~10ms+), but this is not guaranteed under load. The race-free composition primitive is #2286 (`call_and_wait`), which awaits registration before firing the action.
- **`wait_for` called during Bus shutdown:** If shutdown's listener removal fires before the `wait_for` registration completes (the future isn't in `_wait_for_futures` yet), a `timeout=None` wait could hang until the process exits. This is a known limitation consistent with the existing `TaskBucketSealedError` force-terminal precedent — the window is the duration of the `_on_internal` DB write (~1ms), and only matters with `timeout=None`. Practical risk is near-zero for a self-hosted tool.
- **Auto-generated name collisions:** Names use `id(fut)`, which is unique among concurrently-live Python objects. A collision requires two futures with the same memory address alive at the same time, which CPython's allocator prevents. After a future is garbage-collected its `id` may be reused, but the old listener is already removed by then.

## Acceptance Criteria

- **AC#1** `await bus.wait_for("state_changed", where=P.EntityId("light.kitchen") & P.StateTo("on"), timeout=5)` returns the matching event when one is dispatched. (FR#1, FR#9)
- **AC#2** `wait_for` raises `asyncio.TimeoutError` when no matching event arrives within the timeout. (FR#3)
- **AC#3** Events dispatched before the `wait_for` call do not resolve the wait. (FR#2)
- **AC#4** On Bus shutdown (or explicit listener removal), a suspended `wait_for` caller receives `CancelledError` and is unblocked. (FR#8)
- **AC#5** `wait_for` works without a `name=` argument — the listener is registered with an auto-generated name. (FR#5)
- **AC#6** The arm-before-fire composition pattern (`create_task(wait_for(...))`, then `call_service(...)`, then `await task`) correctly resolves when the service call triggers the expected event. (FR#1, FR#2)
- **AC#7** System test: calling a real HA service (e.g., toggling `input_boolean`) and `wait_for`-ing the resulting `state_changed` event through the full WebSocket pipeline resolves correctly. (FR#1)
- **AC#8** System test: `wait_for` with a short timeout against a real HA instance raises `TimeoutError` when no matching event arrives. (FR#3)
- **AC#9** System test: shutting down hassette while a `wait_for` is pending against a real HA instance unblocks the caller. (FR#8)

## Key Constraints

- Do not modify `ListenerNameRequiredError` validation or `_require_name` — generate the name at the `wait_for` level and pass it through to `_on_internal`.
- Do not use `guard_await` on `wait_for` — the return type is `Event[Any]`, not `Subscription`.
- Do not add a `state_check_now` parameter — only match events arriving after registration. Users who need "already true or wait" check `self.states.get()` before calling `wait_for`.
- Cleanup uses `fut.cancel()` via the existing `_on_listener_removed` callback — no separate shutdown loop, no new exception type.

## Dependencies and Assumptions

- Depends on the existing `once=True` listener infrastructure being correct and complete (it is — used extensively today).
- Assumes Bus shutdown (`on_shutdown` → `remove_all_listeners`) runs before the event loop closes — pending futures must be resolvable, not dropped.
- The `hassette.testing.wait_for` naming collision is accepted — different namespaces (`hassette.testing` vs `hassette.bus`), different semantics (polling predicate vs event-driven future).

## Architecture

### Core implementation: `Bus.wait_for()`

Add to `Bus` (in `src/hassette/bus/bus.py`):

1. **Future registry** — `_wait_for_futures: dict[int, asyncio.Future[Event]]` on `Bus.__init__()`. Keyed by listener `db_id`.

2. **`wait_for` method** — follows the `send_and_await_response` pattern:
   - Create an `asyncio.Future`.
   - Define a handler closure that calls `future.set_result(event)` (guarded by `future.done()` to avoid double-set from any race).
   - Generate a name if not provided: `f"_wait_for_{id(fut):x}"` (stateless, unique for the future's lifetime).
   - Call `await self._on_internal(topic=topic, handler=closure, once=True, where=where, name=name, ...)` to register through the existing pipeline.
   - Register the future in `_wait_for_futures[subscription.listener.db_id]`.
   - `try: return await asyncio.wait_for(future, timeout=timeout)` / `finally: _wait_for_futures.pop(db_id, None); subscription.cancel()`.
   - Log at DEBUG when a `wait_for` future resolves (matched event) and when it times out. The `_on_listener_removed` cleanup path logs at WARNING when cancelling pending `wait_for` futures during shutdown, including the count of futures cancelled.
   - Log at WARNING when `len(_wait_for_futures)` crosses the threshold of 20 (FR#11). Check the count after each registration; log once per crossing (not on every subsequent call while above threshold).

3. **Cleanup via `_on_listener_removed`** — extend the existing `Bus._on_listener_removed` callback (already wired via `register_removal_callback`, fires on every listener death — shutdown, explicit cancel, once-fire) to cancel any associated future:
   ```python
   fut = self._wait_for_futures.pop(listener.db_id, None)
   if fut is not None and not fut.done():
       fut.cancel()
   ```
   This replaces the originally proposed separate shutdown loop. Using `fut.cancel()` (raises `CancelledError`, a `BaseException`) instead of `set_exception()` — `CancelledError` cannot be silently swallowed by `except Exception:` handlers in app code, which is more correct for shutdown behavior. No new exception type needed.

### Existing code leverage

| Sub-problem | Existing code | Coverage |
|---|---|---|
| One-shot listener registration | `_on_internal(once=True)` in `bus.py:531-624` | Full — reuse as-is |
| Future-bridge pattern | `WebsocketService.send_and_await_response` in `websocket_service.py:549-578` | Full — follow same shape |
| Predicate/condition filtering | `WhereClause`, `P`, `C`, `A` | Full — reuse as-is |
| Listener removal cleanup | `Bus._on_listener_removed` callback in `bus.py:174-201`, wired via `register_removal_callback` | Full — extend with future cancellation |
| Auto-generated listener name | (none) | None — new code needed |
| Documentation recipe | (none) | None — new content needed |

### Handler signature

The handler closure for `wait_for` takes a single `event` parameter. `HandlerInvoker.create()` builds a `ParameterInjector` from the handler's actual signature, so the closure's signature is matched automatically — no special handling needed.

### No new exception type

Cleanup uses `fut.cancel()` — callers receive standard `CancelledError`. No `BusShutdownError` needed. The `WebsocketService._response_futures` pattern uses `set_exception` because retry logic reads the exception type; `wait_for` has no retry logic, so the distinction adds complexity without value.

## Implementation Preferences

- Follow the `send_and_await_response` pattern from `WebsocketService` exactly — create future, register before action, await with timeout, cleanup in `finally`. (Not `send_and_wait`, which adds retry logic on top.)
- Go through `_on_internal` for registration — do not create listeners directly. This ensures predicates, DB registration, and auto-cleanup all work.
- Auto-generate names at the `wait_for` level, not by modifying `_on_internal` or `_require_name`.
- Use `asyncio.wait_for(future, timeout=timeout)` for timeout enforcement — the standard library handles `None` (no timeout) correctly.

## Replacement Targets

No existing code is being replaced. This is purely additive — app authors currently hand-roll the pattern; the framework provides no equivalent.

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

`_on_listener_removed` is wired via `register_removal_callback` and fires on every listener death — shutdown, explicit cancel, and once-fire. `wait_for` extends this callback to cancel the associated future (guarded by `not fut.done()` so successful matches aren't affected). This replaces the `WebsocketService._response_futures` `set_exception` pattern — `wait_for` has no retry logic that reads exception types, so `fut.cancel()` is simpler and produces an unswallowable `CancelledError`.

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

## Alternatives Considered

**Option B: `call_and_wait` on Api** — A domain-specific convenience (`Api.call_and_wait(domain, service, entity_id=, target_state=, timeout=)`) for the common "call service, confirm entity reached target." Rejected because it creates Api→Bus coupling and is opinionated about what "confirm" means. Filed separately as #2286 for future consideration.

**Option C: Bus.wait_for() with no documented composition recipe** — Ship the primitive only and let users discover the arm-before-fire pattern. Rejected because the arm-before-fire ordering is the exact class of bug that prompted the issue; documenting the pattern is part of solving the problem.

**`asyncio.Event` instead of `asyncio.Future`** — Use an `Event` with a side-channel for the matched event object. Rejected because `Future` directly carries the result value and composes with `asyncio.wait_for` for timeout enforcement.

## Test Strategy

### Required Test Types

- **Unit tests** — `wait_for` method behavior in isolation: future resolution, timeout, shutdown cleanup, name auto-generation, `guard_await` bypass, concurrent waits.
- **Integration tests** — real Bus wiring via `HassetteHarness`: emit events, confirm `wait_for` returns the correct event; arm-before-fire composition with `call_service`.
- **System tests** — real HA instance via Docker: event resolution through the full WS pipeline, timeout under real latency, shutdown cancellation mid-wait.

### Existing Tests to Adapt

No existing tests affected. `wait_for` is a new method with no overlap with existing listener tests.

### New Test Coverage

| Behavior | Layer | FR |
|---|---|---|
| Future resolves on matching event | Unit | FR#1 |
| Only matches events after registration | Unit | FR#2 |
| TimeoutError on expiry | Unit | FR#3 |
| timeout=None accepted (no timeout) | Unit | FR#4 |
| Auto-generated name when name= omitted | Unit | FR#5 |
| User-provided name used when given | Unit | FR#6 |
| Listener auto-removed after firing | Unit | FR#7 |
| Shutdown unblocks pending waits with CancelledError | Unit | FR#8 |
| WhereClause filtering works | Unit | FR#9 |
| No guard_await wrapping | Unit | FR#10 |
| Multiple concurrent waits resolve independently | Unit | FR#1 |
| WARNING logged when pending futures exceed threshold | Unit | FR#11 |
| Real Bus event dispatch resolves wait_for | Integration | FR#1 |
| Arm-before-fire composition with call_service | Integration | FR#1, FR#2 |
| Real HA service call + wait_for through WS | System | FR#1 |
| Timeout under real HA latency | System | FR#3 |
| Shutdown mid-wait against real HA | System | FR#8 |

### Tests to Remove

No tests to remove.

## Smoke Test

**Surface:** Python REPL or test script running against a live hassette instance connected to HA.

**Scenario:** In an app's `on_initialize`, call `self.api.call_service("input_boolean", "turn_on", entity_id="input_boolean.test")`, then `await self.bus.wait_for("state_changed", where=P.EntityId("input_boolean.test") & P.StateTo("on"), timeout=10)`. Expect the wait to resolve with the `state_changed` event within a few hundred milliseconds.

**Success:** The event is returned, the listener is cleaned up, and the app proceeds to the next step.

## Documentation Updates

- **`docs/pages/core-concepts/bus/methods.md`** — Add `wait_for` method documentation with signature, parameter descriptions, and usage examples.
- **`docs/pages/core-concepts/bus/methods.md` or new recipe page** — Document two composition recipes: (1) the single-stage arm-before-fire pattern (call service, wait for state change), and (2) the two-stage "confirm started, then wait for idle" pattern that was the actual production bug (snapshot state, wait for state to leave idle, call service, wait for state to return to idle). The second recipe is critical — a single `wait_for(state == idle)` is insufficient for media-player-style automations where the pre-existing state already matches.
- **API docstring** on `Bus.wait_for` — parameter descriptions, return type, exceptions raised.
- **`CLAUDE.md`** — Update Bus section to mention `wait_for` as a one-shot await primitive.

## Impact

### Changed Files

- **modify** `src/hassette/bus/bus.py` — add `wait_for` method, `_wait_for_futures` registry, extend `_on_listener_removed` for future cleanup
- **create** `tests/unit/bus/test_wait_for.py` — unit tests
- **create** `tests/integration/bus/test_wait_for.py` — integration tests
- **modify** `tests/system/` — add system test(s) for wait_for
- **modify** `docs/pages/core-concepts/bus/methods.md` — add wait_for docs and recipe

### Behavioral Invariants

- All existing Bus registration methods (`on`, `on_state_change`, `on_attribute_change`, `on_call_service`) must continue working identically.
- `Bus.on_shutdown()` must still call `remove_all_listeners()` — the new future cleanup is additive, not a replacement.
- `_require_name` validation must remain enforced for all existing registration methods.

### Blast Radius

- **Bus** — the only component modified. No other services, resources, or app-level APIs are affected.
- **Telemetry** — `wait_for` listeners will appear in the telemetry DB as regular listeners (via `_on_internal`). When using auto-generated names (the default), they'll be distinguishable by their `_wait_for_*` prefix. User-provided `name=` values appear as-is, indistinguishable from other named listeners.
- **Monitoring UI** — `wait_for` listeners will appear in the listener list view. No frontend changes needed — they're regular listeners from the UI's perspective.

## Open Questions

(None — all decisions resolved during discovery and research.)
