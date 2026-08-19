# Tests: integration/websocket

## Available fixtures (this directory's conftest.py)

- `websocket_service` — fresh `WebsocketService(hassette, parent=hassette)` built from `hassette_with_bus`, function-scoped so each test gets its own instance

## File-local helpers

Each of these lives at module scope in its own file, not in `conftest.py` — a reader scanning
`conftest.py` alone won't find them.

- `test_reconnect.py`:
  - `FailingConnection` — callable `make_connection` stub that fails the recv task N times then
    succeeds (or fails forever, or raises a synchronous `final_error` on a specific call).
    Collapses the near-identical `fake_make_connection` closures duplicated across the early-drop
    test suite (issue #1493) into one parametrized helper.
  - `apply_early_drop_config(monkeypatch, websocket_service, **overrides)` — patches the four
    early-drop config knobs (`early_drop_max_retries`, `early_drop_stable_window_seconds`,
    `early_drop_backoff_initial_seconds`, `early_drop_backoff_max_seconds`) on
    `websocket_service.hassette.config.websocket`. Defaults match the shared constants in
    `hassette.test_utils.config`; pass an override only for the value a given test needs to
    differ (e.g. proving retry-budget exhaustion).
  - `make_failing_recv_task(error)` — builds an `asyncio.Task` that immediately raises `error`,
    simulating a failed recv loop for tests that don't need `FailingConnection`'s full
    call-counting/retry machinery.
- `test_subscribe_events_retry.py`:
  - `_make_subscribe_side_effect(ws, *, succeed_on_call=2)` — regression helper for issue #1221
    (subscribe_events double-subscribe on retry).

## Key conventions

- Split by theme, not by original file structure: `test_connection.py` (connection/auth),
  `test_dispatch.py` (`send_json`/`send_and_wait`/dispatch), `test_reconnect.py`
  (`disconnect`/`partial_cleanup`/early-drop reconnect-retry), `test_subscribe_events_retry.py`
  (`TestSubscribeEventsRetry`).
- Each file's module docstring names the sibling files it complements — check there first before
  searching for a helper or fixture that might live in a neighboring file instead.
