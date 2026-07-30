---
task_id: "T01"
title: "Redefine websocket readiness and generation"
status: "done"
depends_on: []
implements: ["FR#8", "FR#9", "FR#10", "FR#11", "FR#27", "FR#28", "AC#6", "AC#7", "AC#8", "AC#19", "AC#25"]
---

## Summary
Rework `WebsocketService` so `CONNECTED` means external Home Assistant readiness, not an internal send gate. Add a private pre-readiness send capability plus generation tracking that downstream code can fence against without changing public bus payloads or app-facing listener signatures. Update the websocket-focused tests and test doubles first-hand so later StateProxy and bootstrap tasks can build on stable semantics.

## Target Files
- modify: `src/hassette/core/websocket_service.py`
- modify: `src/hassette/test_utils/ws_mocks.py`
- modify: `src/hassette/test_utils/helpers.py`
- modify: `src/hassette/test_utils/harness.py`
- modify: `src/hassette/test_utils/web_mocks.py`
- modify: `tests/unit/core/test_ws_connection_state.py`
- modify: `tests/unit/core/test_websocket_readiness_events.py`
- modify: `tests/unit/core/test_websocket_service_coverage.py`
- modify: `tests/integration/test_websocket_service.py`
- read: `src/hassette/core/state_proxy.py`
- read: `src/hassette/core/runtime_query_service.py`

## Prompt
Implement the `## Architecture -> WebSocket Capability and Generation` section from `design/specs/089-issue-1484-lifecycle/design.md`.

In `src/hassette/core/websocket_service.py`, keep `ConnectionState` and validated transitions, but change the connection sequence so external readiness is reached only after: authentication succeeds, the recv loop is running, private send capability is opened, `subscribe_events()` succeeds, and the current connection generation is recorded. `send_json()` must use private send capability so setup requests can be sent before `CONNECTED`, while public `is_connected`, `wait_connected()`, `wait_initial_connection()`, `_connected_event`, `has_ever_connected`, connected/disconnected signals, and `_connected_at` must all describe only external readiness.

Expose direct internal generation access/waits needed by StateProxy without changing public bus event payloads or existing `Bus.on_websocket_connected` / `on_websocket_disconnected` signatures. Preserve invalid-auth fatal behavior and existing service supervision responsibilities; do not add new supervision logic here.

Update websocket test utilities and tests so they model the new pre-readiness send capability and one-way connection-history latch correctly. Keep coverage on transition validation, cleanup paths, early-drop behavior, signal ordering, and readiness event emission.

## Focus
- `src/hassette/core/websocket_service.py` currently sets `CONNECTED` before `subscribe_events()` inside `start_recv_and_subscribe()`; later tasks rely on this no longer being true.
- `src/hassette/core/state_proxy.py` currently waits on `wait_initial_connection()` and subscribes to public websocket signals; preserve those call sites until the StateProxy task rewires them.
- Reverse-dependency gaps to include here: `src/hassette/test_utils/helpers.py`, `src/hassette/test_utils/harness.py`, and `src/hassette/test_utils/web_mocks.py` all hard-code websocket "ready == connected" assumptions; `tests/unit/core/test_ws_connection_state.py`, `tests/unit/core/test_websocket_readiness_events.py`, `tests/unit/core/test_websocket_service_coverage.py`, and `tests/integration/test_websocket_service.py` assert old ordering.
- `RuntimeQueryService.get_system_status()` already keys health on `is_connected` and `has_ever_connected`; this task must preserve those inputs' meanings so the runtime-query task can simply consume them.
- Preserve public listener source compatibility: no signature or topic changes in bus helper APIs, only internal readiness semantics.

## Verify
- [ ] FR#8: `WebsocketService` reaches external readiness only after auth, recv-loop start, and confirmed HA event subscription for the active connection attempt.
- [ ] FR#9: Internal setup can send and await the HA event-subscription request before `is_connected` becomes true.
- [ ] FR#10: Connected/disconnected signals, `_connected_event`, and `has_ever_connected` represent transitions into and out of external readiness only.
- [ ] FR#11: A failed pre-readiness attempt leaves `has_ever_connected` false and emits no disconnected signal.
- [ ] FR#27: Existing `on_websocket_connected` and `on_websocket_disconnected` handlers remain source-compatible.
- [ ] FR#28: Invalid authentication still terminates through existing fatal supervision instead of becoming a recoverable blocked-startup path.
- [ ] AC#6: `ConnectionState.CONNECTED`, `is_connected`, `wait_connected()`, `has_ever_connected`, health connectivity inputs, and public connected signals all align to external readiness.
- [ ] AC#7: `WebsocketService` can send and confirm `subscribe_events` before advertising external readiness.
- [ ] AC#8: Subscription failure before external readiness leaves connection history false and emits no public connected/disconnected signal pair.
- [ ] AC#19: Public websocket convenience handlers keep their current call signatures.
- [ ] AC#25: Invalid-auth behavior still requires corrected configuration plus a full process restart.
