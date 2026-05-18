---
task_id: "T03"
title: "Extract Router to src/hassette/bus/router.py"
status: "planned"
depends_on: ["T01"]
implements: ["FR#9", "AC#8"]
---

## Summary
Move the Router class from the bottom of `src/hassette/core/bus_service.py` (lines 894-1066) to a new `src/hassette/bus/router.py` module. Update BusService to import from the new location. Verify zero imports from core/ or the service layer. Write a focused unit test for Router operations.

## Prompt
Read the design doc section "Router extraction".

**Step 1: Create `src/hassette/bus/router.py`** by moving the `Router` class from `src/hassette/core/bus_service.py:894-1066`. The class has these dependencies (all available without core/ imports):
- `FairAsyncRLock` — external package (`fair_async_rlock`)
- `Listener` type — from `hassette.bus.listeners` (use TYPE_CHECKING guard)
- `GLOB_CHARS` — from `hassette.utils.glob_utils`
- `fnmatch` — stdlib
- `defaultdict` — stdlib
- `Callable` — typing

**Step 2: Remove Router from bus_service.py.** Replace with: `from hassette.bus.router import Router`.

**Step 3: Do NOT export Router from `bus/__init__.py`.** It remains internal — only BusService uses it.

**Step 4: Update Router to read identity fields from sub-structs.** The Router accesses `listener.owner_id` in several places (add_route, remove_route, clear_owner, owners dict). After T01, this becomes `listener.identity.owner_id`. Update all Router methods:
- `add_route()`: `self.owners[listener.identity.owner_id].append(listener)`
- `remove_route()`: owner dict cleanup uses `listener.identity.owner_id`
- `remove_listener()`: same
- `clear_owner()`: parameter is still a string owner_id, but internal list filtering uses `listener.identity.owner_id`
- `get_listeners_by_owner()`: same

**Step 5: Write a focused unit test** at `tests/unit/bus/test_router.py`:
- Import Router directly: `from hassette.bus.router import Router`
- Test add_route + get_topic_listeners (exact match)
- Test add_route + get_topic_listeners (glob match)
- Test remove_listener_by_id
- Test clear_owner

## Focus
- Router is 173 lines, entirely self-contained. This is a mechanical extraction.
- `bus_service.py` drops from ~1066 to ~890 lines after extraction.
- The Router currently accesses `listener.owner_id` directly. After T01, Listener's `owner_id` moves to `listener.identity.owner_id`. Router tests need a Listener mock/stub that has the right sub-struct shape.
- Router uses `FairAsyncRLock` — tests must run in an async context (`pytest-asyncio`).
- The `owners` dict key is `owner_id: str` — this doesn't change. Only the access path on the Listener object changes.

## Verify
- [ ] FR#9: Router module (`src/hassette/bus/router.py`) exists and is importable
- [ ] AC#8: `router.py` has zero imports from `hassette.core` or any service-layer module (verify by reading the import block)
