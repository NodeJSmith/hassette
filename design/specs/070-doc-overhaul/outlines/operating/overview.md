# Operating Hassette — Overview

**Page type:** Operating (production reference)
**Reader's job:** Understand what Hassette does automatically at runtime and how to tune it when something goes wrong in production.
**Voice mode:** Concept/procedural hybrid — system-as-subject for behavior descriptions, "you" for tuning actions

## What was cut (and where it goes)

- **Database Degraded Mode** moved to a one-sentence mention with a link. The full details belong on the Database & Telemetry page; duplicating them here creates two places to maintain.
- The original outline's structure was already reader-oriented (runtime behaviors grouped by what the operator sees). The rewrite reorders to lead with the most common production concern (reconnection) and adds a "When to Tune" subsection to each behavior instead of a separate tuning guide.

## Outline

### H2: WebSocket Reconnection
**Content from KI-01.** The most common production event. Three-layer model, each with its own retry budget:

1. **Initial connect retries** — 5 attempts, 1s-32s exponential backoff with jitter (inside `_make_connection`)
2. **Early-drop retries** — 5 attempts when connection drops within `early_drop_stable_window_seconds` (30s default), 2s-60s backoff. Handles brief HA restarts.
3. **`ServiceWatcher` restart budget** — 5 restarts / 300s sliding window, 2s-60s backoff, then `EXHAUSTED_COOLING` (300s, configurable via `cooldown_seconds`)

What apps see during reconnection: bus, scheduler, state manager stay active. `Api` and `StateProxy` raise `ResourceNotReadyError`. Handlers resume on reconnect without re-registration.

Bus events: `hassette.event.websocket_disconnected` and `hassette.event.websocket_connected`.

Log signatures: inline code blocks showing the WARNING, ERROR, INFO, DEBUG lines the operator will see.

**When to tune:**
- Slow HA restarts (>30s): increase `early_drop_stable_window_seconds`
- Flaky networks: increase `connect_retry_max_attempts` and `connect_retry_max_wait_seconds`
- Low downtime tolerance: decrease backoff values
- `max_recovery_seconds` as total wall-clock cap for the early-drop loop

### H2: Handler Exceptions
**Content from KI-02.** What happens when a handler raises: exception caught, logged at ERROR, swallowed. Does not crash the app or affect other handlers. Telemetry records the invocation with `status='error'`. Log signature showing the ERROR line with traceback. Same behavior for scheduler callbacks.

### H2: Timeouts
Two global defaults from `LifecycleConfig`: `event_handler_timeout_seconds` (600s) and `scheduler_job_timeout_seconds` (600s from `SchedulerConfig`). Per-item overrides via `timeout=` / `timeout_disabled=` on individual registrations.

Enforcement limitations worth knowing:
- Sync handlers run in a thread executor — timeout cancels the awaitable wrapper, not the thread itself
- If a handler catches `TimeoutError` internally, the framework cannot cancel it
- `run_sync_timeout_seconds` (6s default) for sync facade calls

### H2: Database Degraded Mode
One-sentence summary: when the database is unavailable, telemetry stats show zeroed metrics but apps continue running. Link to Database & Telemetry page for full details.

## Snippet Inventory

No code snippets. Log signatures are inline code blocks. Tuning examples are TOML fragments shown inline.

## Cross-Links

- **Links to:** Log Level Tuning, Upgrading, Troubleshooting, Database & Telemetry, Configuration/Global (WebSocket settings)
- **Linked from:** Architecture, Troubleshooting
