---
task_id: "T04"
title: "Migrate test suite mocks and assertions to sync routing contract"
status: "planned"
depends_on: ["T03"]
implements: ["AC#9"]
---

## Summary
Update all test mocks, assertions, and patterns across the test suite to match the new synchronous routing contract. This is a mechanical migration — replacing `AsyncMock` with `Mock`, removing `await` from sync calls, deleting tests for races that no longer exist, and updating spawn count/name assertions. The full test suite must pass with no regressions.

## Prompt
**Note:** Line numbers below are from the time of planning. T01–T03 may shift lines in shared files. Verify all line numbers against the actual file content before editing.

Migrate the following test files. For each, the change pattern is documented below.

**`tests/integration/test_core.py`:**
- Line 237: `remove_all_listeners` mock — change from `Mock(return_value=completed_future)` to `Mock()` (returns None).
- Line 248: Error-path test `test_before_shutdown_finalizes_even_when_listener_removal_fails` — rewrite to use `Mock(side_effect=RuntimeError("bus error"))` and `assert_called_once()` (not `AsyncMock` / `assert_awaited_once()`). The existing `try/except Exception` in `before_shutdown` handles synchronous exceptions.

**`tests/integration/test_state_proxy.py`:**
- Line 123 fixture: `remove_listeners_by_owner` mock returns `asyncio.ensure_future(asyncio.sleep(0))` — change to `Mock()` (returns None).
- Lines 90, 348, 359, 504, 510, 580: `await proxy.bus.get_listeners()` — remove `await` from all six calls.

**`tests/unit/core/test_app_lifecycle_service.py`:**
- Lines 34, 99, 203, 213, 273, 283: `AsyncMock(return_value=[])` for `get_listeners` — change to `Mock(return_value=[])`.
- Line 34: `router.get_listeners_by_owner = AsyncMock(return_value=[])` — change to `Mock(return_value=[])`.

**`tests/unit/core/test_bus_service_timeout.py`:**
- Line 93: `remove_listener` mock returns `MagicMock(return_value=MagicMock(spec=["add_done_callback"]))` — change to `MagicMock()` (returns None).

**`tests/unit/bus/conftest.py`:**
- `mock_add_listener` fixture: update `bus.bus_service.add_listener` stub to return a resolved `asyncio.Future[None]` by default (needed for `registration_task` compatibility in tests that check `isinstance(sub.registration_task, asyncio.Future)`).

**`tests/unit/bus/test_bus_public_private_split.py`:**
- `registration_task` tests: verify they work with the new Task source (from `bus_service.add_listener` return value). Tests that set `add_mock.return_value = future` explicitly should continue working.

**`tests/integration/test_bus.py`:**
- Delete `test_cancel_before_add_task_completes_does_not_orphan_listener` (lines 749-808) and `test_cancel_before_add_task_completes_app_key_path` (lines 809-842). These tests use an async gate on `router.add_route` that is incompatible with sync routing. The race they tested is eliminated by construction and covered by new AC#1 ordering test in T05.

**`tests/integration/test_dispatch_unification.py`:**
- Line 188: `await bus_service._register_then_add_route(listener)` — method is deleted. Preferred: restructure the test to call the public `bus_service.add_listener(listener)` path (sync route + spawned DB task) and await the returned task if DB verification is needed. Fallback: call `bus_service.router.add_route(listener.topic, listener)` + `await bus_service._register_in_db(listener, bus_service._build_registration(listener))` directly, but note this tests internals.

**`tests/unit/bus/test_bus_timeout_threading.py`:**
- Line 13: `add_listener` mock returns `MagicMock(spec=["add_done_callback"])` — change to return a resolved `asyncio.Future[None]` or `None`.

**`tests/integration/test_registration.py`:**
- Lines 270-274: Spawn count assertion `task_bucket.spawn.call_count == 1` and task name `"bus:add_listener"` — update: empty-app_key path spawns 0 tasks (no DB task); app_key path task name changes to `"bus:register_listener"`.

After all changes, run `timeout 300 pytest -n 2` and confirm zero failures.

## Focus
- `test_router.py` is already handled in T01 (57 await removals). This task covers everything else.
- The two deleted tests in `test_bus.py` (lines 749-842) used `async def gated_add_route` monkey-patches. With sync routing, the coroutine is created but never awaited — tests pass vacuously. Delete with rationale in commit message.
- `test_core.py` error-path test is the most subtle — `AsyncMock(side_effect=RuntimeError)` only raises on `await`, not on sync call. Must be `Mock(side_effect=RuntimeError)`.
- `test_app_lifecycle_service.py` has 6 `AsyncMock` → `Mock` changes. Using `AsyncMock` masks regressions where production code accidentally still uses `await` on the now-sync methods.

## Verify
- [ ] AC#9: `timeout 300 pytest -n 2` passes with zero failures across the full test suite
