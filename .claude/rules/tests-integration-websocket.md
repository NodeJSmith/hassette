---
paths:
  - "tests/integration/websocket/**"
---

# Tests: integration/websocket

## Available fixtures (this directory's conftest.py)

- `websocket_service` — fresh `WebsocketService(hassette, parent=hassette)` built from `hassette_with_bus`, function-scoped so each test gets its own instance

## File-local helpers

Each of these lives at module scope in its own file, not in `conftest.py` — a reader scanning
`conftest.py` alone won't find them.

- `test_reconnect_loop.py`:
  - `fast_reconnect` fixture — shrinks the reconnect pacing constants in
    `hassette.core.websocket_reconnect` (and the RUNNING-gate recheck interval in
    `websocket_service`) so loop tests run in milliseconds. `SLOW_TEST_DELAY_SECONDS` stays
    distinct from the shrunk Fast cap so a recorded plan's delay tells Slow from Fast.
  - `serving(websocket_service, fake_ha)` — async context manager that points the service at a
    `FakeHomeAssistant` (`tests/support/fake_ha_ws.py`), runs `serve()`, and tears it down.
  - `record_plans(websocket_service)` — wraps `handle_connection_failure()` to collect each
    `RetryPlan`, the observable record of how the loop classified a failure.
- `test_subscribe_events_retry.py`:
  - `_make_subscribe_side_effect(ws, *, succeed_on_call=2)` — regression helper for issue #1221
    (subscribe_events double-subscribe on retry).

## Key conventions

- Split by theme, not by original file structure: `test_connection.py` (connection/auth),
  `test_dispatch.py` (`send_json`/`send_and_wait`/dispatch), `test_reconnect.py`
  (`partial_cleanup`, the connection-lost event), `test_reconnect_loop.py` (`serve()`'s reconnect
  loop against a scripted HA server), `test_subscribe_events_retry.py` (`TestSubscribeEventsRetry`).
- Each file's module docstring names the sibling files it complements — check there first before
  searching for a helper or fixture that might live in a neighboring file instead.
