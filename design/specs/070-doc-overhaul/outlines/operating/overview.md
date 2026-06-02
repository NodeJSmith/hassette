# Operating Hassette — Overview

**Status:** Stub (3 lines), new page
**Voice mode:** Concept/procedural hybrid — system-as-subject for behavior descriptions, "you" for actions

## Outline

### H2: (Opening)
What this section covers: how Hassette behaves at runtime and how to operate it in production.

### H2: Runtime Behavior

#### H3: WebSocket Reconnection
**Content from KI-01.** Three-layer reconnection model:
1. **Initial connect retries** (inside `_make_connection`): 5 attempts, 1s→32s exponential backoff with jitter
2. **Early-drop retries** (inside `serve()`): 5 attempts when connection drops within `early_drop_stable_window_seconds` (30s default), 2s→60s backoff. This layer handles brief HA restarts.
3. **ServiceWatcher restart budget**: 5 restarts / 300s sliding window, 2s→60s backoff → `EXHAUSTED_COOLING` (300s, configurable via `cooldown_seconds`)

Bus events use full topic strings: `hassette.event.websocket_disconnected`, `hassette.event.websocket_connected`. App behavior during reconnection: `Api` and `StateProxy` raise `ResourceNotReadyError`, handlers resume automatically on reconnect. Include log signatures.

**When to tune** (absorbed from configuration tuning guide):
- Slow HA restarts (>30s): increase `early_drop_stable_window_seconds`
- Flaky networks: increase `connect_retry_max_attempts` and `connect_retry_max_wait_seconds`
- Low tolerance for downtime: decrease backoff values
- `max_recovery_seconds` as the total wall-clock cap for the early-drop retry loop

#### H3: Handler Exception Behavior
**Content from KI-02.** Exceptions caught and swallowed, logged at ERROR, recorded in telemetry with `status='error'`. Include log signature. Matches scheduler behavior.

#### H3: Timeout Behavior
**Absorbed from configuration tuning guide.** Two global defaults: `scheduler_job_timeout_seconds` (600s) and `event_handler_timeout_seconds` (600s). Per-item overrides via `timeout=` / `timeout_disabled=`.

Enforcement limitations: sync handlers run in a thread executor — the timeout cancels the awaitable wrapper, not the thread. `TimeoutError` swallowing: if a handler catches `TimeoutError` internally, the framework cannot cancel it. `run_sync_timeout_seconds` default (6s).

#### H3: Database Degraded Mode
Brief: what happens when the DB is unavailable. Links to Database & Telemetry page for full details.

### H2: See Also
→ Log Level Tuning, → Upgrading, → Troubleshooting

## Snippet Inventory

No code snippets — log signatures are inline code blocks.

## Cross-Links

- **Links to:** Log Level Tuning, Upgrading, Troubleshooting, Database & Telemetry, Configuration/Global (WebSocket resilience settings)
- **Linked from:** Architecture, Troubleshooting (cross-reference)
