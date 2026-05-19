---
task_id: "T05"
title: "Add ordering guarantee tests, contract tests, and documentation"
status: "planned"
depends_on: ["T03"]
implements: ["AC#1", "AC#2", "AC#3", "AC#4", "AC#5", "AC#6"]
---

## Summary
Write new tests that prove the ordering guarantees and routing/DB independence contract introduced by this change. These tests would fail under the old async-task-based design. Also update the docs site with the routing vs registration independence contract (#781).

## Prompt
**1. New ordering guarantee tests** — add to a new file `tests/unit/bus/test_bus_ordering.py` or equivalent:

- **Cancel-then-add ordering (AC#1):** Register a handler via `bus.on(...)`, cancel it via `sub.cancel()`, immediately register a replacement on the same topic. Query `bus.get_listeners()` and assert exactly one handler is routed. Under the old design, the remove task could race with the add task — this test would have been flaky.

- **Bulk remove then query (AC#4):** Register multiple handlers, call `bus.remove_all_listeners()`, immediately call `bus.get_listeners()` and assert empty list. Under the old design, `get_listeners` returned a Task that could resolve before remove completed.

- **Query after registration (AC#3):** Register a handler, immediately call `bus.get_listeners()` and assert the handler is present. This verifies synchronous visibility — no task interleaving between registration and query.

**2. New contract tests** — add to `tests/unit/bus/test_bus_contract.py` or similar:

- **DB failure doesn't affect routing (AC#2):** Mock `_executor.register_listener` to raise an exception. Register a handler. Dispatch an event on the handler's topic. Assert the handler was invoked despite the DB failure. Assert `listener.db_id is None`.

- **Registration task resolves on DB failure (AC#6 — verified here as a behavioral test):** Mock `_executor.register_listener` to raise. Register a handler. `await sub.registration_task`. Assert it resolved with `None` (no exception propagated). Assert `listener.db_id is None`.

**3. Router structural tests (AC#5)** — add to `tests/unit/bus/test_bus_contract.py` or the ordering test file:

- **Router methods are synchronous:** Use `inspect.iscoroutinefunction()` to assert that all 7 Router methods (`add_route`, `remove_route`, `remove_listener`, `remove_listener_by_id`, `clear_owner`, `get_topic_listeners`, `get_listeners_by_owner`) are plain `def`, not `async def`. This prevents silent regression if someone re-adds async.

- **No async lock in Router:** Assert `FairAsyncRLock` does not appear in `router.py`'s module attributes or imports. A simple `assert not hasattr(Router, 'lock')` or `assert 'FairAsyncRLock' not in inspect.getsource(Router)` suffices.

**4. Update docs site** — modify `docs/pages/core-concepts/bus/handlers.md`:

Add a new "Registration vs Routing" section after the existing "Awaiting persistence confirmation" block. Cover:
- Routing is synchronous — the handler is immediately routable when registration returns
- DB registration is asynchronous and may fail independently
- A failed registration does not remove the handler from the routing table
- `registration_task` resolves when the persistence attempt completes, regardless of outcome
- Check `listener.db_id is not None` to confirm persistence succeeded
- Link to existing `registration_task` code example

Reference: design doc `## Architecture > ### Contract documentation (#781)`, `## Test Strategy` (including Router-specific tests), `## Documentation Updates`.

## Focus
- Use `HassetteHarness` for integration-style ordering tests — it wires real Bus, Router, and BusService.
- For the DB failure contract test, mock at the `_executor.register_listener` boundary — this is the system boundary where mocking is appropriate.
- The ordering tests are the most valuable part of this task — they prove the design's core thesis. Write them to be robust: no `asyncio.sleep`, no timing-dependent assertions. The synchronous guarantees should hold deterministically.
- `docs/pages/core-concepts/bus/handlers.md` already has a "Awaiting persistence confirmation" section with a `registration_task` example. The new section builds on it, not replaces it.

## Verify
- [ ] AC#1: A test cancels a handler and immediately registers a replacement — exactly one handler is routed, no duplication
- [ ] AC#2: A test mocks DB failure, dispatches an event, and verifies the handler was invoked with `db_id is None`
- [ ] AC#3: A test registers a handler and immediately queries — the handler is present in the result (no stale snapshot)
- [ ] AC#4: A test calls `remove_all_listeners()` then `get_listeners()` — the list is empty (synchronous completion)
- [ ] AC#5: A test verifies all 7 Router methods are plain `def` (not coroutine functions) and no `FairAsyncRLock` exists in the Router
- [ ] AC#6: A test mocks DB failure, awaits `sub.registration_task`, and confirms it resolves with no exception and `db_id is None`
