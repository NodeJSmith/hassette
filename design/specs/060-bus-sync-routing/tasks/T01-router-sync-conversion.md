---
task_id: "T01"
title: "Convert Router methods to synchronous and remove async lock"
status: "planned"
depends_on: []
implements: ["FR#8", "AC#5"]
---

## Summary
Convert all Router methods from `async def` to plain `def` and remove the `FairAsyncRLock`. The Router's operations are pure in-memory dict/list mutations with no I/O — the async wrapper and lock add overhead without providing concurrency protection in asyncio's cooperative scheduler. This is the foundational change that all subsequent tasks build on.

## Prompt
Modify `src/hassette/bus/router.py`:

1. Remove the `from fair_async_rlock import FairAsyncRLock` import.
2. Remove `self.lock = FairAsyncRLock()` from `__init__`.
3. Convert all methods from `async def` to `def`: `add_route`, `remove_route`, `remove_listener`, `remove_listener_by_id`, `clear_owner`, `get_topic_listeners`, `get_listeners_by_owner`.
4. Remove all `async with self.lock:` blocks — keep the body code unchanged, just dedent one level.
5. Remove the `if listener.is_cancelled: return` guard from `add_route` (line 43). With synchronous routing, the route is inserted before `Subscription` is returned to the caller, so `cancel()` cannot have been called yet.
6. Update the `Router` class docstring to remove references to async operations and the lock.
7. Update `tests/unit/bus/test_router.py` — remove all `await` keywords before Router method calls (57 occurrences). Change any `async def test_*` functions that only call Router methods to plain `def test_*` if they have no other awaits. Update any `@pytest.mark.asyncio` markers accordingly.

Reference: design doc `## Architecture > ### Router: sync conversion`.

## Focus
- `src/hassette/bus/router.py` is 192 lines. All 7 public methods are `async def` with `async with self.lock:`. The lock protects operations that are already atomic in asyncio's single-threaded model.
- `remove_listener` (line 97) is a thin wrapper that calls `await self.remove_route(...)`. It must also become `def` — otherwise it will `await` a non-coroutine after `remove_route` is converted. It is not called by any production code outside the Router, but it must stay consistent.
- `tests/unit/bus/test_router.py` has 57 `await router.*` calls. This is the largest single-file test migration. Each `await` must be removed. Tests that become fully synchronous can drop `async def` and `@pytest.mark.asyncio`.
- The `remove_route` method (lines 52-82) has the most complex body — filtering across topic buckets and syncing the owners dict. The logic is unchanged; only the `async def` and `async with self.lock:` wrapper are removed.
- `FairAsyncRLock` remains used by `SchedulerService` and `StateProxy` — do NOT remove the package dependency, only the import in `router.py`.

## Verify
- [ ] FR#8: All Router mutation and query methods (`add_route`, `remove_route`, `remove_listener`, `remove_listener_by_id`, `clear_owner`, `get_topic_listeners`, `get_listeners_by_owner`) are plain `def` with no `await` in their bodies
- [ ] AC#5: `router.py` contains no `FairAsyncRLock` import, no lock attribute, no `async def`, and no `await` keyword
