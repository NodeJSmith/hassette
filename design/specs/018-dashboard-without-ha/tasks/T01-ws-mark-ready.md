---
task_id: "T01"
title: "Make WebsocketService unconditionally lifecycle-ready"
status: "done"
depends_on: []
implements: ["FR#4", "AC#5"]
---

## Summary

WebsocketService must call `mark_ready()` unconditionally during initialization so that wave-based startup proceeds even when HA is unreachable. Without this, the startup timeout fires and `run_forever()` records a fatal reason and tears down the process. The idempotency guard on `send_connection_lost_event()` must also change from `is_ready()` to `has_ever_connected` — otherwise the first failed connection attempt after unconditional `mark_ready()` fires a spurious disconnect event that causes StateProxy to un-ready itself.

## Target Files

- modify: `src/hassette/core/websocket_service.py`
- modify: `tests/integration/test_websocket_service.py`
- read: `design/specs/018-dashboard-without-ha/design.md`

## Prompt

Make two changes to `src/hassette/core/websocket_service.py`:

1. **Add `on_initialize()` override** that calls `mark_ready(self, reason="WebSocket service initialized")` unconditionally. This fires before `serve()` starts the connection loop. Import `mark_ready` from `hassette.resources.lifecycle` (already imported at line 35). Place the method after `__init__` and before the properties. This separates "service lifecycle ready" from "HA connected."

2. **Update `send_connection_lost_event()`** (line 727-739): Change the guard from `if not self.is_ready(): return` to `if not self.has_ever_connected: return`. The `has_ever_connected` property (line 144) is already defined and never reverts once True. This prevents spurious DISCONNECTED events before the first successful connection. The docstring should be updated to reflect the new guard.

Then update tests in `tests/integration/test_websocket_service.py`:

3. **Update `test_send_connection_lost_event_idempotent`** (line 776): This test asserts `send_connection_lost_event` is a no-op when the service is not-ready. The guard now checks `has_ever_connected` instead of `is_ready()`. Update the test to verify the behavior is a no-op when `has_ever_connected` is False (the default for a fresh service). The test name can stay the same since the behavior is still "idempotent when no connection has been established."

4. **Add a new test `test_send_connection_lost_event_skips_before_first_connection`** that explicitly verifies: when the service IS marked ready (via `mark_ready()`) but `has_ever_connected` is False, `send_connection_lost_event()` does NOT fire the DISCONNECTED event. This is the exact scenario the design doc's edge case #3 describes. Use the `EventCapture` pattern already in the file.

Follow the existing test patterns in `tests/integration/test_websocket_service.py` — use `EventCapture`, `websocket_service` fixture, `lifecycle_module.mark_ready()`.

## Focus

- `mark_ready` is imported from `hassette.resources.lifecycle` at line 35 — it's already in scope.
- `has_ever_connected` property at line 144 returns `self._ever_connected` — set to True only in `set_connection_state()` when transitioning to CONNECTED. It never reverts.
- `send_connection_lost_event()` is called from three places within websocket_service.py: `before_shutdown()` (line 221), and two error paths (lines 269, 280). All three must work correctly with the new guard.
- `test_send_connection_lost_event_self_suppressing` (line 789) manually calls `mark_ready()` to make the service ready so the event fires. With the new guard, this test also needs `_ever_connected = True` — check whether it still passes and fix if needed.
- The `before_shutdown()` call at line 221 should still fire the disconnect event when a connection was established and then the service shuts down. With `has_ever_connected`, this works: if we ever connected, the event fires; if we never connected, skipping is correct.

## Verify

- [ ] FR#4: WebsocketService has an `on_initialize()` that calls `mark_ready()` unconditionally — service reports lifecycle-ready immediately, independent of HA reachability.
- [ ] AC#5: A test verifies `send_connection_lost_event()` does not fire when `has_ever_connected` is False, even when the service is marked ready.
