---
task_id: "T02"
title: "Remove WebsocketService from depends_on chains"
status: "done"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "FR#5", "FR#7", "AC#4"]
---

## Summary

Three services — ApiResource, StateProxy, and AppHandler — declare `WebsocketService` in their `depends_on`, which blocks their startup wave until WS is ready. With T01 making WS unconditionally ready, these edges are redundant but still create unnecessary coupling. Remove them. Additionally, StateProxy's `on_initialize()` must catch `load_cache()` failure instead of raising, so it can mark ready with an empty cache when HA is unreachable.

## Target Files

- modify: `src/hassette/core/api_resource.py`
- modify: `src/hassette/core/state_proxy.py`
- modify: `src/hassette/core/app_handler.py`
- modify: `tests/integration/test_state_proxy.py`
- read: `design/specs/018-dashboard-without-ha/design.md`

## Prompt

Make four changes:

1. **`src/hassette/core/api_resource.py`** (line 55): Change `depends_on` from `[WebsocketService]` to `[]` (empty list). Remove the `WebsocketService` import (line 21). Update the `on_initialize()` docstring (line 80) which says "WebsocketService is guaranteed ready by depends_on auto-wait" — remove that statement since it's no longer true.

2. **`src/hassette/core/state_proxy.py`** (line 38): Remove `WebsocketService` from `depends_on`. Keep `ApiResource`, `BusService`, and `SchedulerService`. The new list is `[ApiResource, BusService, SchedulerService]`. Remove the `WebsocketService` import (line 12). Update the `on_initialize()` docstring (line 63-68) which says "WebsocketService, ApiResource, BusService, and SchedulerService are guaranteed ready by depends_on auto-wait" — remove the WebsocketService mention.

3. **`src/hassette/core/state_proxy.py` `on_initialize()`** (lines 77-84): Make `load_cache()` failure non-fatal. Instead of letting the exception propagate (which currently kills startup), catch it, log a warning, and call `mark_ready()` with an empty cache. The pattern mirrors `on_reconnect()` (lines 303-334) which already catches `load_cache()` failure gracefully. After the change, `on_initialize()` should look like:
   - Call `subscribe_to_events()` (already at line 71 — unchanged)
   - Wire bus handlers for reconnect/disconnect (already at lines 73-74 — unchanged)
   - Try `load_cache()` → on success, `mark_ready(self, reason="Initial state sync complete")`
   - On exception: log warning with `self.logger.warning(...)` (not `.exception()` — the full traceback is noise during normal HA-offline startup), then `mark_ready(self, reason="Started with empty state cache")`

4. **`src/hassette/core/app_handler.py`** (line 42-49): Remove `WebsocketService` from `depends_on`. Keep `ApiResource`, `BusService`, `SchedulerService`, `StateProxy`, `SyncExecutorService`. Remove the `WebsocketService` import (line 19).

5. **`tests/integration/test_state_proxy.py`**: Update `test_raises_on_api_failure_during_init` (line 98). This test currently asserts that `on_initialize()` raises when `load_cache()` fails. With the change, `on_initialize()` no longer raises — it catches the error and marks ready with an empty cache. Rewrite the test to verify the new behavior: mock `get_states_raw` to raise, call `on_initialize()`, assert it does NOT raise, assert `proxy.is_ready()` is True, and assert `proxy.states` is empty (`{}`). Rename to `test_marks_ready_with_empty_cache_on_api_failure_during_init`. Remove the second `on_initialize()` call at line 112 (no longer needed since the first call now succeeds).

6. **Add a new test** in the same test class: `test_get_state_returns_none_when_cache_empty_after_init_failure`. Mock `get_states_raw` to raise, call `on_initialize()`, then call `proxy.get_state("light.nonexistent")` and assert it returns None (not raises `ResourceNotReadyError`). This validates FR#7 end-to-end.

## Focus

- `ApiResource.on_initialize()` (line 78) creates an `aiohttp.ClientSession` — no actual HA request. Safe to start without WS.
- `StateProxy.on_initialize()` calls `subscribe_to_events()` BEFORE `load_cache()` (line 71). Event subscriptions are wired regardless of cache success. Do not reorder these calls.
- `StateProxy._check_ready()` (line 158-160): raises `ResourceNotReadyError` only when `not is_ready() AND not self.states`. Once marked ready (even with empty cache), `is_ready()` returns True, so `_check_ready()` passes and `get_state()` returns None. No change to `_check_ready()` is needed.
- `AppHandler.on_initialize()` and `after_initialize()` don't read WS state or call WS methods — they wire file-watcher subscriptions and bootstrap apps.
- The `state_proxy` fixture at `tests/integration/test_state_proxy.py:116` creates a mock-backed StateProxy. Check whether it needs adjustment for the changed `on_initialize()` behavior.
- The test at line 112 (`await proxy.on_initialize()`) was a cleanup call to ensure the proxy could be used in later tests. With non-fatal `on_initialize()`, this cleanup is unnecessary since the first call succeeds.

## Verify

- [ ] FR#2: StateProxy starts with an empty state cache when HA is unreachable and does not raise during `on_initialize()`.
- [ ] FR#3: ApiResource starts without waiting for WebsocketService — `depends_on` is empty.
- [ ] FR#5: AppHandler starts and bootstraps apps without waiting for a live HA connection — WebsocketService removed from `depends_on`.
- [ ] FR#7: `get_state()` returns None (not `ResourceNotReadyError`) when the state cache is empty after a failed initial sync.
- [ ] AC#4: A test verifies StateProxy marks ready with an empty cache when `load_cache()` fails, and `get_state()` returns None.
