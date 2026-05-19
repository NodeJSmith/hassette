# Context: Bus Sync Routing

## Problem & Motivation
The Bus event system wraps synchronous in-memory operations (dictionary lookups, list appends, list filtering) in asyncio tasks via TaskBucket.spawn(). This creates two problems: (1) ordering bugs — cancel-then-resubscribe races because remove and add are independent tasks that can execute in either order, and (2) unnecessary complexity — Router operations are pure dict/list mutations wrapped in async+lock for no I/O reason. The only genuinely async operation is DB registration for telemetry. This blocks features like if_exists and makes every handler lifecycle feature inherit the ordering risk.

## Visual Artifacts
None.

## Key Decisions
1. Router methods become plain `def` — the FairAsyncRLock is removed entirely. Correctness argument: asyncio's cooperative scheduler guarantees atomicity between await points; Router operations have no await points.
2. BusService performs routing synchronously (immediate dict mutation), then spawns a background task only for DB registration. This mirrors the Scheduler's proven `dequeue_job` pattern.
3. `Bus.add_listener` returns `None`; `_on_internal` captures the DB task from `bus_service.add_listener` for `Subscription.registration_task`.
4. The `once=True` DB-before-route ordering is intentionally removed for architectural simplicity. Orphan invocation records are handled by the existing execution layer.
5. `_register_in_db` catches `BaseException` (not just `Exception`) to handle `CancelledError` from `RegistrationTracker` timeout, ensuring `registration_task` always resolves cleanly (AC#6).
6. The `is_cancelled` guard in `Router.add_route` is removed — with sync routing, the route is inserted before `Subscription` is returned, so `cancel()` cannot have been called yet.

## Constraints & Anti-Patterns
- Do NOT introduce thread-safe locking as a replacement for the async lock.
- Do NOT couple routing and DB registration into a single operation.
- Do NOT make public Bus registration methods async — `on_state_change(...)` must work from synchronous `on_initialize`.
- Do NOT implement if_exists — this change enables it but the API is a separate feature.
- Do NOT tighten DB registration (make it less fire-and-forget) — separate initiative.
- All methods public (no underscore prefixes) — this is a personal project convention.

## Design Doc References
- `## Architecture` — full implementation details for Router, BusService, Bus, cancel-listener, dispatch path, caller migration
- `## Edge Cases` — once=True regression, shutdown during pending DB, concurrent reload, cancel-listener timing, dispatch-pending counter
- `## Key Constraints` — three prohibited approaches
- `## Test Strategy` — ordering tests, contract tests, test migration, Router structural tests
- `## Impact` — complete file list with change descriptions

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

### Cancel-listener resolved Future
**Source:** `src/hassette/bus/listeners.py:209-212` (via `bus_service.py`)
```python
resolved: asyncio.Future[None] = asyncio.get_running_loop().create_future()
resolved.set_result(None)
return Subscription(cancel_listener, unsubscribe, registration_task=resolved)
```

### Bus collision detection (sync validation before delegation)
**Source:** `src/hassette/bus/bus.py:193-202`
```python
if not listener.options.once:
    natural_key = self._listener_natural_key(listener)
    if natural_key in self._registered_keys:
        key_str = natural_key[-1] or listener.identity.handler_name
        raise ValueError(...)
    self._registered_keys.add(natural_key)
```
