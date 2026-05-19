---
task_id: "T02"
title: "Restructure BusService for sync routing with async DB only"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#7", "FR#9", "FR#10", "AC#7", "AC#8"]
---

## Summary
Restructure BusService so that routing operations (add/remove/query) execute synchronously and immediately, while only DB registration remains as a fire-and-forget background task. This is the core architectural change — splitting the old `_register_then_add_route` into sync routing + async DB, making remove/get methods fully synchronous, updating cancel-listener wiring, and adjusting the dispatch path.

## Prompt
Modify `src/hassette/core/bus_service.py`:

**1. Restructure `add_listener`:**
- Duration timer wiring stays unchanged (already sync).
- Call `self.router.add_route(listener.topic, listener)` synchronously (no task spawn).
- Extract DB registration logic from `_register_then_add_route` into a new `_register_in_db(listener, reg)` async method. Build the `ListenerRegistration` struct via a new `_build_registration(listener)` helper.
- Spawn `_register_in_db` as the only background task. Track via `_reg_tracker.prune_and_track`.
- Return `asyncio.Task[None] | None` — the DB registration task (needed by `Bus._on_internal` for `registration_task`).
- `_register_in_db` must catch `BaseException` (not just `Exception`) to handle `CancelledError` from `RegistrationTracker` timeout.

**2. Delete `_register_then_add_route`** — its logic is split between sync routing in `add_listener` and async DB in `_register_in_db`.

**3. Handle immediate-fire:** The `if listener.duration_config.immediate:` block (spawning `_immediate_fire_task`) stays after the sync route insertion. It's genuinely async and belongs as a spawned task.

**4. Make `remove_listener` fully synchronous:**
```python
def remove_listener(self, listener: Listener) -> None:
    listener.cancel()
    self.router.remove_listener_by_id(listener.topic, listener.listener_id)
```

**5. Make `_remove_listener_by_id` synchronous** — direct call to `self.router.remove_listener_by_id(topic, listener_id)`, no task spawn.

**6. Make `remove_listeners_by_owner` synchronous:**
```python
def remove_listeners_by_owner(self, owner: str) -> None:
    removed = self.router.clear_owner(owner)
    for listener in removed:
        listener.cancel()
```

**7. Make `get_listeners_by_owner` synchronous:**
```python
def get_listeners_by_owner(self, owner: str) -> list[Listener]:
    return self.router.get_listeners_by_owner(owner)
```

**8. Update `_create_cancel_listener`:**
- Replace the task-spawned route insertion with sync `self.router.add_route(cancel_listener.topic, cancel_listener)`.
- Remove `_dispatch_pending` increment and `_on_dispatch_done` callback for cancel-listener route insertion.
- Update the `unsubscribe` closure to call `self.router.remove_listener_by_id(...)` directly (sync).

**9. Update `dispatch`:**
- Change `listeners = await self.router.get_topic_listeners(route)` to `listeners = self.router.get_topic_listeners(route)` (sync call, no await).

**10. Remove the `once=True` special DB-before-route ordering.** All listeners get sync route insertion followed by async DB. Document this as a deliberate regression per the design doc Edge Cases section.

**11. Update docstrings** on all restructured methods (`add_listener`, `remove_listener`, `_remove_listener_by_id`, `remove_listeners_by_owner`, `get_listeners_by_owner`, `_create_cancel_listener`, `_register_in_db`) to reflect the new sync routing contract. Remove references to `asyncio.Task` returns, task spawning for routing, and the old `_register_then_add_route` flow.

Reference: design doc `## Architecture > ### BusService: immediate routing`, `### Cancel-listener route insertion`, `### Dispatch path`, `## Documentation Updates`.

## Focus
- `bus_service.py` is ~930 lines. The key methods to restructure are: `add_listener` (line 121), `_register_then_add_route` (line 223), `_create_cancel_listener` (line 157), `remove_listener` (line 473), `_remove_listener_by_id` (line 481), `remove_listeners_by_owner` (line 485), `get_listeners_by_owner` (line 499), `dispatch` (line 536).
- The `_build_registration` helper extracts lines 237-260 from `_register_then_add_route` into a reusable method.
- The `once=True` branch at lines 261-271 is deleted. The `else` branch at lines 273-282 is also deleted — its route insertion moves to `add_listener` (sync), its DB logic moves to `_register_in_db`.
- `_dispatch_pending` is only incremented for genuine async work: handler dispatch tasks and immediate-fire tasks. NOT for route insertions (now sync).
- `tests/unit/core/test_bus_service_timeout.py` — `remove_listener` mock needs updating (no `add_done_callback` return).

## Verify
- [ ] FR#1: `add_listener` calls `router.add_route` synchronously before returning — the route is in the table when the method returns
- [ ] FR#2: `remove_listener` calls `router.remove_listener_by_id` synchronously — the route is removed when the method returns
- [ ] FR#3: `get_listeners_by_owner` returns `list[Listener]` directly with no task spawn
- [ ] FR#4: DB registration is spawned as a background task via `task_bucket.spawn` after sync route insertion
- [ ] FR#5: `_register_in_db` catches `BaseException` — a DB failure does not affect the already-inserted route
- [ ] FR#7: `remove_listeners_by_owner` calls `router.clear_owner` synchronously — all routes are removed when the method returns
- [ ] FR#9: `_create_cancel_listener` calls `router.add_route` synchronously with no `_dispatch_pending` increment
- [ ] FR#10: `dispatch` calls `self.router.get_topic_listeners(route)` without `await`, then spawns handler execution tasks
- [ ] AC#7: `_create_cancel_listener` does not increment `_dispatch_pending` or call `_on_dispatch_done` for route insertion
- [ ] AC#8: `dispatch` reads the routing table synchronously (no `await` between topic lookup and task creation)
