# Design: Bus Sync Routing

**Date:** 2026-05-19
**Status:** archived
**Scope-mode:** expand

## Problem

The event bus wraps synchronous in-memory operations (dictionary lookups, list appends, list filtering) in background tasks, introducing ordering bugs and unnecessary complexity.

When a caller cancels an existing handler and immediately registers a replacement, both operations are dispatched as independent background tasks. The removal and addition can execute in any order, causing the replacement to be silently dropped or both handlers to coexist. This makes sequential handler management (cancel-then-resubscribe, handler replacement) unreliable.

The complexity compounds: every new feature that touches handler lifecycle inherits the ordering risk and must reason about task interleaving for operations that have no inherent concurrency requirement. Concretely, a handler replacement API (if_exists) cannot be built safely because remove-then-add ordering is not guaranteed, and the cancel-then-resubscribe pattern in the state proxy has a latent race condition. The in-memory routing table holds no external I/O — the only genuinely asynchronous operation is database persistence for telemetry, which is a separate concern.

## Goals

- Sequential handler operations (remove then add, bulk remove then re-register) execute in deterministic order with no interleaving
- In-memory routing operations complete immediately when the caller's code resumes — no background task, no deferred execution
- Database persistence remains decoupled from routing — a persistence failure does not prevent event delivery
- The routing table has no locking overhead — operations are protected by the runtime's cooperative scheduling guarantees
- Tests prove ordering guarantees that would fail under the previous design

## Non-Goals

- **Handler replacement API (if_exists)**: This change enables deterministic if_exists by making routing synchronous, but the if_exists API itself is a separate feature
- **Tightening database registration**: Making persistence less fire-and-forget (e.g., awaited inline, prerequisite for "fully registered") is a separate initiative
- **Thread-safety for free-threaded runtimes**: The synchronous routing model relies on cooperative scheduling (no preemption between non-await code). Adapting for free-threaded Python is out of scope

## User Scenarios

### App Developer: Automation Author

- **Goal:** Register event handlers during app initialization and have them receive events immediately
- **Context:** Writing an `on_initialize` method in a hassette app

#### Register a handler

1. **Call a registration method (e.g., on_state_change)**
   - Sees: a subscription object returned synchronously
   - Decides: nothing — registration is a single call
   - Then: the handler is immediately routable; database persistence happens in background

#### Cancel and replace a handler

1. **Cancel the existing subscription**
   - Sees: the subscription's cancel method returns
   - Decides: nothing
   - Then: the handler is immediately removed from the routing table — no pending removal
2. **Register a replacement handler**
   - Sees: a new subscription returned
   - Then: the replacement is immediately routable; the old handler is guaranteed gone

### Framework Internals: State Proxy, Shutdown, Reconciliation

- **Goal:** Manage handler lifecycle with deterministic ordering during reconnection, shutdown, and app reload
- **Context:** Internal framework code that must cancel, re-register, or query handlers in sequence

#### Cancel-then-resubscribe on reconnection

1. **Cancel existing event subscription**
   - Then: handler is immediately removed from routing table
2. **Register new subscription**
   - Then: new handler is immediately routable — no race with pending removal

#### Shutdown cleanup

1. **Remove all handlers for an app**
   - Then: all handlers are immediately removed — no background task to await
   - Then: shutdown proceeds without waiting for routing cleanup

#### Reconciliation query

1. **Query all handlers for an app**
   - Sees: the complete list of currently-routed handlers, returned immediately
   - Decides: which handlers to retire based on database records
   - Then: reconciliation proceeds with an accurate snapshot

## Functional Requirements

- **FR#1** Adding a handler to the routing table completes before the registration call returns to the caller
- **FR#2** Removing a handler from the routing table completes before the removal call returns to the caller
- **FR#3** Querying handlers for an owner returns the result directly, not via a deferred computation
- **FR#4** Database registration for a handler is initiated as a background operation after routing completes
- **FR#5** A database registration failure does not remove the handler from the routing table or prevent event delivery
- **FR#6** A completion signal is available for callers that need to know when database persistence has been attempted
- **FR#7** Bulk removal of all handlers for an owner completes before the call returns
- **FR#8** Routing table mutation and query operations complete atomically without explicit locking, relying on the runtime's cooperative scheduling guarantee
- **FR#9** Cancel-listener route insertion for duration timers completes immediately (no background task)
- **FR#10** Event dispatch reads from the routing table synchronously, then spawns handler execution as background tasks

## Edge Cases

- **Once-only handlers and database ordering**: The current code deliberately registers once-only handlers in the database before inserting their route (preventing orphan invocation records). This design removes that guarantee — all listeners, including once-only, get synchronous route insertion followed by asynchronous database registration. Once-only handlers may fire and be removed before their database row exists, producing a permanently unlinked invocation record (`listener_id=None`). This is a deliberate behavioral regression for architectural simplicity — the execution layer already handles orphan records, and the planned database registration tightening initiative will address this more broadly.
- **Shutdown during pending database registration**: If shutdown fires while a database registration task is still in-flight, the registration task may be cancelled. The handler was already removed from the routing table (FR#7), so no events are delivered. The incomplete DB record is acceptable — session cleanup handles orphans.
- **Concurrent app reload mid-dispatch**: An app reload triggers bulk removal (FR#7) while dispatch tasks are in-flight. Removal is immediate, so no new dispatch tasks are created for the removed handlers. In-flight dispatch tasks complete normally — the handler's cancelled flag prevents re-dispatch.
- **Cancel-listener registration timing**: With synchronous routing, the cancel-listener's route is active before `add_listener` returns. The previous design had a one-event-loop-iteration window where the cancel-listener wasn't yet routed. This window is eliminated.
- **Dispatch-pending counter accuracy**: Background tasks for handler execution and immediate-fire are counted. Synchronous route insertions are not counted — they complete inline and need no completion tracking.
- **Remove non-existent handler**: Removing a handler that has already been removed or was never registered is a no-op — the routing table filtering finds no matching entry and returns without error.
- **Query with no handlers registered**: Querying handlers for an owner with no registered handlers returns an empty list immediately.

## Acceptance Criteria

- **AC#1** A test demonstrates that cancelling a handler followed by registering a replacement results in exactly one handler routed — no race, no duplication (FR#1, FR#2)
- **AC#2** A test demonstrates that a handler receives events even when its database registration fails (FR#4, FR#5)
- **AC#3** A test demonstrates that querying handlers returns the current state immediately after a registration, not a stale snapshot (FR#1, FR#3)
- **AC#4** A test demonstrates that bulk removal returns synchronously and the routing table is empty afterward (FR#7)
- **AC#5** The routing table implementation contains no lock, no async primitives, and no await points in its mutation methods (FR#8)
- **AC#6** The completion signal resolves regardless of whether database registration succeeded or failed (FR#6)
- **AC#7** Cancel-listener route insertion does not increment the dispatch-pending counter (FR#9)
- **AC#8** Event dispatch retrieves matching handlers from the routing table synchronously, then spawns handler execution as background tasks — no await between topic lookup and task creation (FR#10)
- **AC#9** All existing tests pass with no regressions

## Key Constraints

- **Do not introduce thread-safe locking as a replacement for the removed async lock.** The correctness argument is: asyncio's cooperative scheduler guarantees that code between await points runs atomically. If the routing table methods have no await points, they cannot be interrupted. Adding a threading lock would be unnecessary overhead and would signal a misunderstanding of the concurrency model.
- **Do not couple routing and database registration into a single operation.** The independence of routing (immediate, must succeed) and registration (background, may fail) is a deliberate architectural contract, not an accident. Any change that makes routing conditional on registration success would break event delivery.
- **Do not make the public Bus registration methods async.** The entire point of synchronous routing is that `bus.on_state_change(...)` works from synchronous `on_initialize` methods. Making registration async would cascade `await` requirements to every user app.

## Dependencies and Assumptions

- **Cooperative scheduling guarantee**: Python's asyncio event loop is single-threaded. Code between await points cannot be preempted. This is the foundation for removing the lock.
- **TaskBucket**: Continues to own background DB registration tasks. Its spawn/track/await API is unchanged.
- **RegistrationTracker**: Continues to track per-app registration tasks for `await_registrations_complete`. No changes needed — it receives the DB task reference as before.
- **CommandExecutor**: Already handles invocations where `db_id` is None (orphan records). No changes needed.

## Architecture

The chosen approach — synchronous routing with asynchronous DB registration — directly mirrors the Scheduler's proven `dequeue_job` pattern. Routing operations are pure in-memory dict/list mutations with no I/O, so wrapping them in tasks adds concurrency without benefit. Making them synchronous eliminates ordering bugs by construction and removes the async lock that was protecting already-atomic operations. DB registration is the only operation that genuinely requires async I/O, so it remains as a fire-and-forget background task.

### Router: sync conversion

All methods on `Router` (`src/hassette/bus/router.py`) become plain `def` instead of `async def`. The `FairAsyncRLock` is removed. The `__init__` drops the lock. Each method body is unchanged — the operations were already synchronous under the lock.

The `is_cancelled` guard in `add_route` (line 43) becomes dead code: with synchronous routing, the route is inserted before the `Subscription` is returned to the caller, so `cancel()` cannot have been called. Remove the guard.

```python
class Router:
    def __init__(self) -> None:
        self.exact: dict[str, list[Listener]] = defaultdict(list)
        self.globs: dict[str, list[Listener]] = defaultdict(list)
        self.owners: dict[str, list[Listener]] = defaultdict(list)

    def add_route(self, topic: str, listener: Listener) -> None:
        if any(ch in topic for ch in GLOB_CHARS):
            self.globs[topic].append(listener)
        else:
            self.exact[topic].append(listener)
        self.owners[listener.identity.owner_id].append(listener)

    def remove_route(self, topic: str, predicate: Callable[[Listener], bool]) -> None:
        # ... same filtering logic across topic buckets + owners sync, no async/lock ...

    def remove_listener(self, listener: Listener) -> None:
        # ... delegates to remove_route with listener_id predicate ...

    def remove_listener_by_id(self, topic: str, listener_id: int) -> None:
        # ... delegates to remove_route with listener_id predicate ...

    def clear_owner(self, owner: str) -> list[Listener]:
        # ... same logic, returns removed listeners ...

    def get_topic_listeners(self, topic: str) -> list[Listener]:
        # ... same lookup/sort/dedup logic ...

    def get_listeners_by_owner(self, owner: str) -> list[Listener]:
        # ... same logic ...
```

### BusService: immediate routing

`BusService` (`src/hassette/core/bus_service.py`) restructures each method to perform routing synchronously and spawn tasks only for DB I/O.

**`add_listener`** — Split `_register_then_add_route` into two steps:

```python
def add_listener(self, listener: Listener) -> asyncio.Task[None] | None:
    # Duration timer wiring (already sync — unchanged)
    if listener.duration_config is not None and listener.duration_config.duration is not None:
        # ... attach_timer logic unchanged ...

    # Sync: insert route immediately
    self.router.add_route(listener.topic, listener)

    # Async: spawn DB registration as background task
    app_key = listener.identity.app_key or listener.identity.owner_id
    reg = self._build_registration(listener)
    task = self.task_bucket.spawn(self._register_in_db(listener, reg), name="bus:register_listener")
    self._reg_tracker.prune_and_track(app_key, task)
    return task
```

The new `_register_in_db` method contains only the DB write from the old `_register_then_add_route`:

```python
async def _register_in_db(self, listener: Listener, reg: ListenerRegistration) -> None:
    try:
        listener.mark_registered(await self._executor.register_listener(reg))
    except BaseException:
        # Catch BaseException (not just Exception) to handle CancelledError from
        # RegistrationTracker.await_complete() timeout. Ensures the task always
        # resolves cleanly, satisfying AC#6 (registration_task never raises).
        self.logger.exception(
            "Failed to register listener in DB for owner_id=%s topic=%s; "
            "listener will run without telemetry until next restart",
            listener.identity.owner_id,
            listener.topic,
        )
```

The `once=True` special ordering (DB before route) is removed — all listeners get sync route insertion followed by async DB. Once-only listeners may produce orphan invocation records if they fire before DB completes, which is already the documented contract for regular listeners.

**Immediate-fire** spawning (line 284-291) stays unchanged — it's genuinely async (reads state, dispatches handler). It is spawned after route insertion, same as before.

**`remove_listener`** — Becomes fully synchronous:

```python
def remove_listener(self, listener: Listener) -> None:
    listener.cancel()
    self.router.remove_listener_by_id(listener.topic, listener.listener_id)
```

No task spawn. No return value.

**`_remove_listener_by_id`** — Same pattern, no task:

```python
def _remove_listener_by_id(self, topic: str, listener_id: int) -> None:
    self.router.remove_listener_by_id(topic, listener_id)
```

**`remove_listeners_by_owner`** — Synchronous clear + cancel:

```python
def remove_listeners_by_owner(self, owner: str) -> None:
    removed = self.router.clear_owner(owner)
    for listener in removed:
        listener.cancel()
```

**`get_listeners_by_owner`** — Direct return:

```python
def get_listeners_by_owner(self, owner: str) -> list[Listener]:
    return self.router.get_listeners_by_owner(owner)
```

### Bus: public API changes

`Bus` (`src/hassette/bus/bus.py`) updates return types and restructures `_on_internal`.

**`add_listener`** — Returns None, discards the DB task. Retains the collision check (same as today — both `add_listener` and `_on_internal` guard against duplicates):

```python
def add_listener(self, listener: Listener) -> None:
    if not listener.options.once:
        natural_key = self._listener_natural_key(listener)
        if natural_key in self._registered_keys:
            raise ValueError(...)
        self._registered_keys.add(natural_key)
    self.bus_service.add_listener(listener)
```

**`_on_internal`** — Calls `bus_service.add_listener` directly to capture the DB task for `registration_task`:

```python
def _on_internal(self, ...) -> Subscription:
    # ... build listener (unchanged) ...

    # Collision check (same logic as add_listener)
    if not listener.options.once:
        natural_key = self._listener_natural_key(listener)
        if natural_key in self._registered_keys:
            raise ValueError(...)
        self._registered_keys.add(natural_key)

    def unsubscribe() -> None:
        self.remove_listener(listener)

    registration_task = self.bus_service.add_listener(listener)
    return Subscription(listener, unsubscribe, registration_task)
```

`bus_service.add_listener` returns `asyncio.Task[None] | None` — the DB registration task. `_on_internal` passes it to `Subscription` as the `registration_task`. This preserves the existing completion signal contract.

**`remove_listener`** — Returns None, preserves collision-key cleanup:

```python
def remove_listener(self, listener: Listener) -> None:
    self._registered_keys.discard(self._listener_natural_key(listener))
    self.bus_service.remove_listener(listener)
```

**`remove_all_listeners`** — Returns None:

```python
def remove_all_listeners(self) -> None:
    self._registered_keys.clear()
    self.bus_service.remove_listeners_by_owner(self.owner_id)
```

**`get_listeners`** — Direct return (no longer async):

```python
def get_listeners(self) -> list[Listener]:
    return self.bus_service.get_listeners_by_owner(self.owner_id)
```

### Cancel-listener route insertion

`_create_cancel_listener` (`bus_service.py:157-212`) currently spawns a task for route insertion and tracks it via `_dispatch_pending`. With synchronous routing:

```python
def _create_cancel_listener(self, main_listener: Listener) -> Subscription:
    # ... build cancel_listener (unchanged) ...

    # Sync route insertion — no task, no dispatch_pending tracking
    self.router.add_route(cancel_listener.topic, cancel_listener)

    def unsubscribe() -> None:
        cancel_listener.cancel()
        self.router.remove_listener_by_id(cancel_listener.topic, cancel_listener.listener_id)

    resolved: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    resolved.set_result(None)
    return Subscription(cancel_listener, unsubscribe, registration_task=resolved)
```

The `_dispatch_pending` increment and `_on_dispatch_done` callback are removed for cancel-listener route insertion — it's synchronous and needs no completion tracking.

Note: the `unsubscribe` closure also changes — `_remove_listener_by_id` is now synchronous (calls `router.remove_listener_by_id` directly), so the closure calls `router.remove_listener_by_id` directly instead of going through `_remove_listener_by_id` (which previously spawned a task).

### Dispatch path

`dispatch` (`bus_service.py:536-576`) calls `router.get_topic_listeners` — this becomes a synchronous call:

```python
async def dispatch(self, base_topic: str, event: Event[Any]) -> None:
    # ... skip/log checks unchanged ...
    routes = self._expand_topics(base_topic, event)
    chosen: dict[int, tuple[str, Listener]] = {}

    for route in routes:
        listeners = self.router.get_topic_listeners(route)  # sync now
        for listener in listeners:
            if listener.listener_id in chosen:
                continue
            if listener.matches(event):
                chosen[listener.listener_id] = (route, listener)

    # ... dispatch tasks unchanged — handler execution is genuinely async ...
```

`dispatch` itself stays `async def` because it spawns handler execution tasks. Only the Router query becomes synchronous.

### Caller migration

| Call site | Current | After |
|---|---|---|
| `Bus.on_shutdown` | `await self.remove_all_listeners()` | `self.remove_all_listeners()` |
| `Hassette.before_shutdown` (`core.py:620`) | `await self._bus.remove_all_listeners()` | `self._bus.remove_all_listeners()` |
| `reset_bus` (`test_utils/reset.py`) | `await bus.remove_all_listeners()` | `bus.remove_all_listeners()` |
| `StateProxy.subscribe_to_events` (`state_proxy.py:82`) | `self.state_change_sub.cancel()` (already sync) | No change — ordering bug is fixed by sync routing |
| `AppLifecycleService._reconcile` (`app_lifecycle_service.py:556`) | `await inst.bus.get_listeners()` | `inst.bus.get_listeners()` |
| `AppLifecycleService._reconcile` (`app_lifecycle_service.py:571`) | `await router.get_listeners_by_owner(...)` | `router.get_listeners_by_owner(...)` |

### Contract documentation (#781)

Add a docstring block to `_register_in_db` (the new DB-only method) and update `Subscription.registration_task`'s docstring to explicitly state:

> Routing (event delivery) and database registration (telemetry persistence) are independent operations. Route insertion is synchronous — the handler is immediately routable when registration returns. Database registration is asynchronous and may fail independently. A failed registration does not remove the handler from the routing table. The `registration_task` future resolves when the persistence attempt completes, regardless of outcome. Check `listener.db_id is not None` to confirm persistence succeeded.

Add a corresponding section to `docs/pages/core-concepts/bus/handlers.md` covering the routing vs registration independence contract.

## Convention Examples

### Scheduler sync dequeue pattern

**Source:** `src/hassette/core/scheduler_service.py:480-505`

```python
def dequeue_job(self, job: "ScheduledJob") -> bool:
    removed = self._job_queue.remove_item_sync(job)
    if removed:
        self.logger.debug("Dequeued job: %s", job)
        self.kick()
    else:
        self.logger.debug("Job not in heap (already popped by serve loop): %s", job)
    job._dequeued = True
    self._fire_removal_callbacks([job])
    return removed
```

Synchronous state mutation, no lock, no task. The reference pattern for Bus routing.

### Cancel-listener resolved Future

**Source:** `src/hassette/bus/listeners.py:209-212` (via `bus_service.py`)

```python
resolved: asyncio.Future[None] = asyncio.get_running_loop().create_future()
resolved.set_result(None)
return Subscription(cancel_listener, unsubscribe, registration_task=resolved)
```

Pattern for `registration_task` when no DB task exists. Already in use for cancel-listeners.

### Bus collision detection (sync validation before delegation)

**Source:** `src/hassette/bus/bus.py:193-202`

```python
if not listener.options.once:
    natural_key = self._listener_natural_key(listener)
    if natural_key in self._registered_keys:
        key_str = natural_key[-1] or listener.identity.handler_name
        raise ValueError(
            f"Duplicate listener registration detected for handler '{listener.identity.handler_name}' "
            f"on topic '{listener.topic}' (key={key_str!r}). "
            f"Add name= to disambiguate if intentional."
        )
    self._registered_keys.add(natural_key)
```

Synchronous validation that runs before any async work. Already established.

### Router dict operations under async wrapper

**Source:** `src/hassette/bus/router.py:32-50`

```python
async def add_route(self, topic: str, listener: "Listener") -> None:
    async with self.lock:
        if listener.is_cancelled:
            return
        if any(ch in topic for ch in GLOB_CHARS):
            self.globs[topic].append(listener)
        else:
            self.exact[topic].append(listener)
        self.owners[listener.identity.owner_id].append(listener)
```

Pure dict/list operations wrapped in async + lock. The async wrapper and lock are removed; the body is unchanged.

### StateProxy cancel-resubscribe (the ordering bug)

**Source:** `src/hassette/core/state_proxy.py:77-96`

```python
def subscribe_to_events(self) -> None:
    if self.state_change_sub is not None:
        self.state_change_sub.cancel()
        self.state_change_sub = None
    # ...
    self.state_change_sub = self.bus.on(topic=Topic.HASS_EVENT_STATE_CHANGED, handler=self._on_state_change)
```

`cancel()` is synchronous, but the underlying `remove_listener` previously spawned a task — the new `on()` could race with the pending removal. With synchronous routing, removal is immediate and the race is eliminated.

## Alternatives Considered

### Keep current structure, fix ordering via explicit await (Option B)

Keep all operations as-is (returning Tasks), but require callers to await the Task when ordering matters. For if_exists, make it a first-class method that internally awaits the remove before spawning the add.

**Rejected because:** `Subscription.cancel()` is synchronous and is called from synchronous contexts (e.g., inside `Listener.cancel()`, inside `_on_dispatch_done` callbacks). Making it async would cascade changes through the system. "Convention to await" is fragile — new callers will forget. The prior art research explicitly identifies this as an anti-pattern.

### Hybrid — sync Router but keep BusService task spawning (Option C)

Make Router methods synchronous but keep BusService spawning tasks that call the now-synchronous Router methods.

**Rejected because:** Still spawns tasks for synchronous work — ordering bugs remain. Neither fish nor fowl.

### Full async with explicit ordering — structured concurrency (Option D)

Make all BusService methods `async def`. Callers await them.

**Rejected because:** `Bus._on_internal()` calls `add_listener()` from synchronous context (called by `on_state_change`, `on_attribute_change`, etc. which are all `def`). Making `add_listener` `async def` would require making every registration method on Bus async, cascading `await` requirements to every user app's `on_initialize`. Massive breaking change.

## Test Strategy

### New ordering guarantee tests

- Cancel-then-add: cancel a subscription, immediately register a replacement, verify exactly one handler is routed (AC#1)
- Bulk remove then query: remove all handlers for an owner, immediately query, verify empty result (AC#3, AC#4)

### New contract tests (#781)

- DB failure doesn't affect routing: mock the DB executor to raise, verify the handler is still in the routing table and receives events (AC#2)
- `registration_task` resolves on DB failure: confirm `await sub.registration_task` completes and `listener.db_id is None` (AC#6)

### Existing test migration

- Update mocks in `tests/integration/test_core.py` — `remove_all_listeners` is now sync (no Task/Future return). **Error-path test** (`test_before_shutdown_finalizes_even_when_listener_removal_fails`): rewrite to use `Mock(side_effect=RuntimeError(...))` and `assert_called_once()` — the existing `try/except Exception` in `before_shutdown` handles synchronous exceptions correctly
- Update mocks in `tests/integration/test_state_proxy.py` — `remove_listeners_by_owner` is now sync
- Update `tests/unit/bus/conftest.py` — `mock_add_listener` returns resolved Future for `registration_task` compatibility
- Update `tests/unit/bus/test_bus_public_private_split.py` — `registration_task` tests work with new Task source
- Verify `tests/unit/core/test_bus_service_timeout.py` — `remove_listener` mock no longer needs `add_done_callback`

### Router-specific tests

- Verify Router methods are plain `def` (AC#5)
- Verify no `FairAsyncRLock` import in `router.py` (AC#5)

### Regression suite

Full test suite (`timeout 300 pytest -n 2`) must pass with no regressions (AC#9).

## Documentation Updates

- **`docs/pages/core-concepts/bus/handlers.md`**: Add "Registration vs Routing" section documenting the independence contract. Explain that routing is synchronous and immediate, DB registration is background and may fail. Include the `registration_task` + `db_id` guard pattern.
- **`Subscription.registration_task` docstring** (`bus/listeners.py`): Update to reflect the new architecture — routing is synchronous, `registration_task` tracks only DB persistence.
- **`Router` class docstring** (`bus/router.py`): Remove references to async operations and lock.
- **`BusService` method docstrings**: Update all changed methods to reflect sync routing.

## Impact

### Files modified

| File | Change |
|---|---|
| `src/hassette/bus/router.py` | Remove `FairAsyncRLock`, convert all methods to `def`, remove `is_cancelled` guard |
| `src/hassette/core/bus_service.py` | Restructure `add_listener` (sync route + async DB), make `remove_*` sync, make `get_listeners_by_owner` sync, update `_create_cancel_listener`, update `dispatch` Router call |
| `src/hassette/bus/bus.py` | Change return types to `None`/`list[Listener]`, restructure `_on_internal` |
| `src/hassette/bus/listeners.py` | Update `Subscription.registration_task` docstring |
| `src/hassette/core/core.py` | Remove `await` from `remove_all_listeners()` call |
| `src/hassette/core/state_proxy.py` | No code change needed — ordering bug is fixed by sync routing |
| `src/hassette/test_utils/reset.py` | Remove `await` from `remove_all_listeners()` call |
| `src/hassette/core/app_lifecycle_service.py` | Remove `await` from `get_listeners()` and `get_listeners_by_owner()` calls |
| `docs/pages/core-concepts/bus/handlers.md` | Add routing vs registration section |
| `tests/integration/test_core.py` | Update `remove_all_listeners` mocks |
| `tests/integration/test_state_proxy.py` | Update `remove_listeners_by_owner` mock |
| `tests/unit/core/test_bus_service_timeout.py` | Update `remove_listener` mock |
| `tests/unit/bus/conftest.py` | Update `mock_add_listener` fixture |
| `tests/unit/bus/test_bus_public_private_split.py` | Update `registration_task` tests |
| `tests/integration/test_dispatch_unification.py` | Replace `await bus_service._register_then_add_route(listener)` with `bus_service._register_in_db(listener, bus_service._build_registration(listener))` — method was deleted |
| `tests/unit/bus/test_bus_timeout_threading.py` | Remove `spec=["add_done_callback"]` from `add_listener` mock; update return to `None` or resolved Task |
| `tests/integration/test_registration.py` | Update spawn count assertion (empty-app_key path: 0 spawns); update task name from `"bus:add_listener"` to `"bus:register_listener"` |
| `tests/integration/test_bus.py` | Delete or rewrite `test_cancel_before_add_task_completes_*` tests — async gate pattern incompatible with sync routing; race is eliminated by construction |
| New test file(s) | Ordering guarantee tests, contract tests |

<!-- Gap check 2026-05-19: 2 gaps included — test_router.py (57 await removals) → T01, test_app_lifecycle_service.py (6 AsyncMock→Mock) → T04. False positives excluded: harness.py (web router, not Bus Router), duration_timer.py (docstring only), test_apps.py/test_bus_duration.py (use convenience API, no direct breaks). -->

### Blast radius

- **Router** — complete rewrite of method signatures (7 methods). Internal to framework; no user-facing API change.
- **BusService** — 5 methods restructured. Internal to framework.
- **Bus** — 4 method return types change. `add_listener` and `remove_listener` are rarely called directly by users (they use `on_state_change` etc. which go through `_on_internal`). `get_listeners` is used in tests.
- **Caller sites** — ~6 call sites lose `await`. All internal framework code.
- **Test mocks** — ~5 test files need mock updates. Straightforward type changes.

### Dependencies removed

- `fair_async_rlock` is no longer imported in `router.py`. It remains used by `SchedulerService` and `StateProxy`.

## Open Questions

- *(none — all questions from the research brief were resolved during discovery)*
