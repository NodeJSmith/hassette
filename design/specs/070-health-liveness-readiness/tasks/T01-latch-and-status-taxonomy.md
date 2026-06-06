---
task_id: "T01"
title: "Add ever-connected latch and fix status taxonomy"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#2"]
---

## Summary
Add a one-way "ever connected" latch to the WebSocket service and use it in `get_system_status()` so a booted instance that loses HA reports `degraded` instead of falsely reporting `starting`. This is the regression fix for the reboot loop's status taxonomy. The `proxy_ready` fallback in the status reduction is removed; the latch replaces it with a deterministic signal.

## Prompt
Implement the latch and status-taxonomy change described in `design.md` → Architecture → "Latch" and "Status taxonomy".

1. **`src/hassette/core/websocket_service.py`** — add an instance attribute `_ever_connected: bool = False` in `__init__` (alongside `_connected_at` / `_connection_state`, ~line 123). Inside `_set_connection_state()` (the single transition chokepoint, ~line 135), set `self._ever_connected = True` whenever the new state is `ConnectionState.CONNECTED`. Expose a read-only `ever_connected` property (mirror the existing `connection_state` property at ~line 130). Do not set the latch from the bus event — set it in the transition so it's true synchronously and can't be bypassed.

2. **`src/hassette/core/runtime_query_service.py`** — in `get_system_status()` (~line 269), change the status reduction so the middle tier keys off the latch read from the WebSocket service:
   ```python
   ws = self.hassette.websocket_service
   if ws.is_ready():
       status = "ok"
   elif ws.ever_connected:
       status = "degraded"
   else:
       status = "starting"
   ```
   Remove the `proxy_ready` fallback for the `degraded` branch. `proxy_ready` may still be read for other fields, but it must no longer determine `degraded` vs `starting`.

3. **`src/hassette/test_utils/web_mocks.py`** — in `create_hassette_stub` (~line 131, where `hassette._websocket_service.is_ready.return_value = is_ready` is set), expose `ever_connected` as an explicit attribute defaulting to the same value as `is_ready` (i.e. `hassette._websocket_service.ever_connected = is_ready`). This prevents health tests from relying on MagicMock's auto-truthy attribute behavior.

4. **Tests** — follow `design.md` → Test Strategy:
   - WebSocket service unit test: `ever_connected` starts `False`, flips `True` after a `_set_connection_state(ConnectionState.CONNECTED)` transition, and stays `True` across a subsequent disconnect.
   - `tests/unit/core/test_runtime_query_service.py` (`TestSystemStatus`): add cases for latched + not-ready → `degraded` (AC#1), and never-latched + not-connected → `starting` (AC#2). Update any existing `degraded` test that relied on `proxy_ready` to instead drive `websocket_service.ever_connected`.

Do not touch the health routes, response models, or the shutdown path — those are separate tasks.

## Focus
- `_set_connection_state()` is the only place all WS transitions pass through (validated table at `websocket_service.py:52`); setting the latch there covers every connect path. `_connected_at` resets to `None` on disconnect and `ConnectionState` is current-state-only, so neither already encodes "ever connected."
- `RuntimeQueryService.get_system_status()` already reads `self.hassette.websocket_service.is_ready()` — reading `ever_connected` alongside it needs no new wiring.
- `RuntimeQueryService._on_ws_connected` (`runtime_query_service.py:202`, subscribed at `:111`) exists for broadcasting connectivity to dashboard clients — do NOT set the latch there.
- Gap note: `src/hassette/web/routes/ws.py:100` also calls `get_system_status()` to broadcast status to the dashboard. The `SystemStatus` return shape is unchanged, so this consumer needs no edit — but its broadcast now correctly reports `degraded` during an outage. No action required beyond awareness.
- Reason `proxy_ready` is dropped: `StateProxy.on_disconnect()` (`state_proxy.py`) revokes proxy readiness before `get_system_status()` runs during a sustained outage, so the old `elif proxy_ready` branch fell through to `starting` — the bug.

## Verify
- [ ] FR#1: On the WebSocket service, `ever_connected` is `False` before any connection, becomes `True` after a `CONNECTED` transition, and remains `True` after a subsequent disconnect (unit test).
- [ ] FR#2: `get_system_status().status == "degraded"` when `ever_connected` is set and the WS is not ready; `== "starting"` when `ever_connected` was never set (unit test).
- [ ] FR#3: `get_system_status().status == "ok"` when `websocket_service.is_ready()` is `True` (unit test).
- [ ] AC#1: With the latch set and the WS reporting not-connected, `get_system_status().status == "degraded"` (reboot-loop regression test).
- [ ] AC#2: With the latch never set and the WS not connected, `get_system_status().status == "starting"`.
