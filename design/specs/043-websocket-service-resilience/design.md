# Design: WebSocket Service Resilience

**Date:** 2026-04-28
**Status:** approved
**Research:** /tmp/claude-mine-define-research-hFHGWz/brief.md

## Problem

When the home automation server restarts, the WebSocket connection is accepted and authenticated, but the server drops it 5-15 seconds later while it finishes initializing. The current implementation treats every post-connection drop as a fatal failure, triggering a full service restart cycle. After five restart cycles (each hitting the same early-drop pattern), the entire automation process permanently crashes and requires manual intervention.

Beyond this critical bug, the WebSocket connection code was one of the first things written and has accumulated several maintainability issues: hardcoded retry parameters that operators cannot tune, reliance on unstable internal APIs for connection state checking, and a single method that mixes five distinct responsibilities (connect, authenticate, start receiver, subscribe, mark ready).

## Goals

1. The system transparently recovers from early connection drops during server restarts without consuming any restart budget
2. After the server finishes restarting, all automations resume within seconds without manual intervention
3. Operators can tune all retry and backoff parameters through configuration
4. Connection state checking uses only stable, documented APIs
5. Token revocation mid-session is detected indirectly (via re-authentication failure after a drop), logged clearly, and triggers a graceful shutdown
6. Operators can diagnose connection issues from logs alone — every retry, backoff, and failure reason is logged at the appropriate level
7. The connection establishment code is decomposed into focused, independently testable methods

## Non-Goals

- Adding a message queue that buffers outbound commands during brief disconnects — commands that fail during a drop will raise errors as they do today
- Adding a `RECONNECTING` resource status — the existing `RUNNING` + not-ready combination is semantically correct
- Distinguishing token revocation from network drops at the protocol level — the server does not send identifiable close codes for revocation
- Changing the ServiceWatcher restart contract — `FAILED` events still trigger restarts, `CRASHED` events still trigger shutdown

## User Scenarios

### Operator: Home automation administrator

- **Goal:** Keep automations running continuously through server maintenance
- **Context:** Running the automation framework on a home server; the home automation server periodically restarts for updates or configuration changes

#### Server restart during normal operation

1. **Server begins restarting**
   - Sees: Nothing immediately — the active WebSocket connection is still open
   - Then: Server drops the connection 5-15 seconds after its restart begins

2. **Framework detects the drop**
   - Sees: Warning-level log message identifying this as an early drop with retry count
   - Decides: No decision needed — the framework handles it automatically
   - Then: Framework waits briefly, then attempts to reconnect

3. **Reconnection during server initialization**
   - Sees: Log messages showing connection retry attempts with backoff timing
   - Then: If the server is not yet ready, each attempt either fails to connect (handled by connection-level retries) or connects and drops again (handled by early-drop retries)

4. **Server finishes restarting**
   - Sees: Info-level log confirming reconnection and subscription restoration
   - Then: All automations resume processing events; no manual intervention required

#### Token revoked while connected

1. **Administrator revokes the access token used by the framework**
   - Sees: Nothing immediately — the server drops the WebSocket without a distinguishing signal
   - Then: Framework detects the drop and attempts to reconnect

2. **Reconnection fails authentication**
   - Sees: Error-level log clearly stating authentication failed on reconnect — possible token revocation
   - Then: Framework shuts down permanently (authentication failure is fatal)

#### Server permanently unreachable

1. **Server hardware failure or network partition**
   - Sees: Warning logs showing connection retry attempts exhausting
   - Then: After exhausting connection-level retries, the failure propagates to the service restart layer
   - Sees: Warning logs showing service restart attempts with increasing backoff
   - Then: After exhausting service restart budget, the framework logs the crash and shuts down

### Developer: Automation author

- **Goal:** Understand connection lifecycle behavior for debugging
- **Context:** Writing or debugging automations that depend on the WebSocket connection

#### Debugging connection issues

1. **Reviews logs after an incident**
   - Sees: Three clearly labeled retry layers in logs: connection-level (`[tenacity]`), early-drop (`[serve]`), and service-level (`[ServiceWatcher]`)
   - Decides: Which layer is relevant based on the log prefix and timing
   - Then: Adjusts configuration parameters if the defaults don't suit their environment

## Functional Requirements

### Early-drop detection and retry

1. When a post-connection drop occurs within a configurable time window after the connection was marked ready, the system must classify it as an early drop and retry without emitting a failure event
2. Each early-drop retry must clean up the previous connection's state (cancel receiver, close socket, clear pending responses) while preserving the underlying session for reuse
3. The early-drop retry loop must have a configurable maximum attempt count; after exhausting retries, the failure must propagate normally to the service restart layer
4. Early-drop retries must use configurable exponential backoff with jitter to avoid thundering-herd reconnection patterns
5. When an early-drop retry succeeds, the service restart budget must remain unchanged (no failure event was emitted)
6. When the connection is in the early-drop retry loop, the service must be marked not-ready but must not change its resource status from RUNNING

### Token revocation detection

7. When a reconnection attempt (whether from early-drop retry or service restart) fails authentication, the system must log a clear message indicating possible token revocation
8. Authentication failures must remain fatal and non-retryable — the system must shut down immediately rather than cycling through retry budgets

### Connection state

9. Connection state checking must use only documented, stable public APIs — no access to library-internal attributes
10. The `connected` property must accurately reflect whether the connection is usable for sending messages
24. When the receive loop encounters an error frame (transport or protocol error reported by the library), it must raise a retryable connection error to trigger the early-drop or disconnect handling — not silently continue looping

### Configuration

11. All retry parameters currently hardcoded in the connection logic must be exposed as configuration fields with sensible defaults matching current behavior
12. The early-drop stable window, retry count, and backoff parameters must each be independently configurable
13. Default values must produce behavior identical to the current implementation for connection-level retries, with the addition of early-drop retry as a new capability

### Logging

14. Every retry attempt must be logged with the retry layer name, attempt number, maximum attempts, and reason for the retry
15. Early-drop detection must log the elapsed time since the connection was marked ready and the configured stable window threshold
16. Successful reconnection after early-drop retries must log at INFO level confirming restoration
17. Close codes from the server must be included in disconnect log messages when available

### Connection lifecycle events

18. When an early drop is detected, a connection-lost event must be emitted to notify downstream consumers
19. When an early-drop retry succeeds, a connection-established event must be emitted so downstream consumers can refresh their state
20. Connection events during the early-drop retry loop must use the same event types as the existing connect/disconnect events — no new event types
23. Framework-internal event subscribers that perform expensive operations on disconnect (such as clearing caches or bulk-fetching state) must be idempotent for rapid disconnect/reconnect cycles — the first disconnect triggers the operation, subsequent disconnects within the early-drop window are no-ops when the subscriber is already in a not-ready state

### Method decomposition

21. The connection establishment logic must be separated into distinct operations: socket connection with authentication, receiver startup with event subscription, and partial cleanup for retry scenarios
22. Each extracted method must be independently unit-testable with mock dependencies

## Edge Cases

1. **Immediate drop**: The server drops the connection within milliseconds of authentication — the recv task may fail before `serve()` starts awaiting it. The stable-window check must work even when the failure is synchronous with connection establishment.

2. **Drop at stable-window boundary**: The connection drops at exactly the stable-window threshold. The boundary condition must be defined clearly (strictly less than threshold = early drop).

3. **Cascading early drops**: Multiple consecutive early drops within the same `serve()` invocation. Each must decrement the retry budget and apply increasing backoff.

4. **Early drop followed by connection refusal**: The first drop is an early drop, but on retry the server is fully down (connection refused). The connection-level retries (tenacity) must handle the refusal; if tenacity exhausts, the error propagates through the early-drop loop to ServiceWatcher.

5. **Non-retryable error during early-drop window**: A `RuntimeError` or other non-retryable exception occurs within the stable window. The early-drop retry must only apply to connection-related exceptions (`RetryableConnectionClosedError`, `ServerDisconnectedError`), not all exceptions.

6. **Partial cleanup failure**: If cancelling the old recv task or closing the old WebSocket fails during early-drop cleanup, the retry must still proceed (suppressing cleanup errors) rather than propagating the cleanup failure.

7. **Concurrent send during early-drop retry**: Application code calls `send_json` while the early-drop retry is in progress. The `connected` property must return `False`, and `send_json` must raise `ConnectionClosedError` as it does today.

8. **Authentication failure on reconnect**: The reconnection after an early drop fails authentication (possible token revocation). This must be logged distinctively and must propagate as a fatal error immediately, not consume more early-drop retry budget.

## Acceptance Criteria

1. A server restart that causes 1-3 early connection drops results in transparent recovery with zero service restart counter increments
2. After exhausting the early-drop retry budget, the failure propagates to the service restart layer and behaves identically to current behavior
3. All eight new configuration fields have sensible defaults and are documented
4. The `connected` property works correctly without accessing any library-internal attributes
5. Connection establishment logic is split into at least three independently testable methods
6. Log output during an early-drop recovery cycle clearly shows the retry layer, attempt count, timing, and outcome
7. Token revocation (simulated as authentication failure on reconnect) produces a distinctive log message and immediate shutdown
8. The system test hold-probe workaround is no longer required for test reliability (may be retained as defense-in-depth)
9. All existing integration tests continue to pass after the refactoring
10. New integration tests cover: early-drop retry success, early-drop retry exhaustion, stable-connection failure propagation, non-retryable exception within stable window, authentication failure on reconnect
11. During an early-drop retry cycle, the service resource status remains RUNNING while `is_ready` is False
12. When the server sends a close frame with a close code, the `RetryableConnectionClosedError` carries the close code and the connection-lost event includes it in its data
13. Connection-lost and connection-established events emitted during early-drop retry use the same event types as normal connect/disconnect events

## Dependencies and Assumptions

- **aiohttp**: The `closed` and `close_code` properties on `ClientWebSocketResponse` are documented public API and stable across versions. Verified in aiohttp source.
- **tenacity**: The `@retry` decorator applied inside a method body captures config values at call time (verified: `AsyncRetrying.wraps()` creates a copy per invocation). Config externalization is safe.
- **Home Assistant WebSocket protocol**: HA does not send identifiable close codes for different disconnect scenarios (restart vs. token revocation vs. overload). Token revocation produces a TCP drop, not a clean close frame (HA PR #57091).
- **Monotonic clock**: `time.monotonic()` is used for the stable-window timestamp, consistent with other service-layer code in this project (`database_service`, `command_executor`, `rate_limiter`).

## Architecture

### Three-layer retry model

The existing two-layer retry (tenacity for connection phase, ServiceWatcher for service restarts) has a gap: post-connection failures go straight to ServiceWatcher. This design fills the gap with an early-drop retry loop inside `serve()`:

| Layer | Scope | Handles | Config prefix | Default |
|-------|-------|---------|---------------|---------|
| **Connection retry** (tenacity in `_make_connection`) | TCP connect + auth + subscribe | Connection refused, DNS failure, auth timeout | `websocket_connect_retry_*` | 5 attempts, 1s→32s exponential+jitter |
| **Early-drop retry** (loop in `serve`) | Post-ready drops within stable window | HA dropping connection during its restart | `websocket_early_drop_*` | 5 attempts, 30s window, 2s→60s exponential+jitter, 300s total cap |
| **Service restart** (ServiceWatcher) | Full service lifecycle | Persistent failures after inner retries exhaust | `service_restart_*` | 5 attempts, 2s→60s exponential |

Each layer is independently configurable. They do not interact: the inner layer must fully exhaust before the next layer sees a failure.

The primary trade-off is conceptual complexity: three retry layers with independent configuration mean operators must understand which layer handles which failure class. This complexity is justified because each layer has a fundamentally different blast radius (lightweight reconnect vs. full service rebuild vs. process shutdown), and collapsing them would force a single budget to serve incompatible failure modes.

### New config fields

Added to `HassetteConfig` alongside the existing `websocket_*` block:

```python
# Connection-level retry (externalized from hardcoded tenacity params)
websocket_connect_retry_max_attempts: int = Field(default=5)
websocket_connect_retry_initial_wait_seconds: float = Field(default=1.0)
websocket_connect_retry_max_wait_seconds: float = Field(default=32.0)

# Early-drop retry (new capability)
websocket_early_drop_stable_window_seconds: float = Field(default=30.0)
websocket_early_drop_max_retries: int = Field(default=5)
websocket_early_drop_backoff_initial_seconds: float = Field(default=2.0)
websocket_early_drop_backoff_max_seconds: float = Field(default=60.0)
websocket_max_recovery_seconds: float = Field(default=300.0)
```

Defaults for the `connect_retry_*` fields match current hardcoded behavior exactly. The `early_drop_*` fields are new with conservative defaults: 30s window (covers the 5-15s HA restart drop with margin), 5 retries with 2s→60s backoff. `websocket_max_recovery_seconds` (default: 300s / 5 minutes) caps the total wall-clock time spent in the early-drop retry loop — when exceeded, the current failure propagates to ServiceWatcher regardless of remaining per-retry budget. This prevents the multiplicative worst-case (21+ minutes) from the three independent retry layers.

At startup, WebsocketService logs the effective resilience budget at INFO level: `"WebSocket resilience budget: max ~N minutes to permanent shutdown (early-drop: X retries capped at Ys, connection: Z retries, service: W restarts)"`, computed from the config values.

### Method decomposition of `_make_connection`

Currently `_make_connection` contains a single inner function `_inner_connect` that mixes five concerns. After decomposition:

- **`_connect_ws(session)`** — Opens the WebSocket connection and authenticates. Sets `self._ws`. Converts `ClientConnectorError` with `ConnectionRefusedError` cause to `CouldNotFindHomeAssistantError`.
- **`_start_recv_and_subscribe()`** — Spawns the recv loop task, sends the connection-established event, subscribes to HA events, and calls `mark_ready()`. Records `_connected_at` timestamp. Returns the recv task. Note: `_connected_at: float | None` is initialized to `None` in `__init__` and reset to `None` at the start of each `_make_connection` call.
- **`_partial_cleanup()`** — Cancels the recv task, closes the WebSocket, clears pending futures and subscription IDs. Does NOT close the `ClientSession` (that's owned by `serve()`'s `async with` block). Suppresses all cleanup errors to ensure retry can proceed.

The tenacity `@retry` decorator remains on `_inner_connect` inside `_make_connection`, but `_inner_connect` now delegates to `_connect_ws` and `_start_recv_and_subscribe`. The retry config values are read from `self.hassette.config` instead of hardcoded literals.

### Early-drop retry loop in `serve()`

The core change: `serve()` wraps the recv-task await in a loop that distinguishes early drops from stable-connection failures:

```python
async def serve(self) -> None:
    async with self._connect_lock:
        timeout = ClientTimeout(...)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            early_drop_attempts = 0
            max_early_drops = self.hassette.config.websocket_early_drop_max_retries
            stable_window = self.hassette.config.websocket_early_drop_stable_window_seconds
            max_recovery = self.hassette.config.websocket_max_recovery_seconds
            recovery_started_at: float | None = None

            while True:
                try:
                    self._recv_task = await self._make_connection(session)
                    await self._recv_task
                    return  # clean exit (shutdown)
                except InvalidAuthError:
                    if early_drop_attempts > 0:
                        self.logger.error(
                            "Authentication failed on reconnect — possible token revocation"
                        )
                    raise
                except Exception as exc:
                    elapsed = (time.monotonic() - self._connected_at) if self._connected_at is not None else float('inf')
                    recovery_elapsed = (time.monotonic() - recovery_started_at) if recovery_started_at is not None else 0.0
                    is_early = (
                        elapsed < stable_window
                        and isinstance(exc, EARLY_DROP_RETRYABLE)
                        and early_drop_attempts < max_early_drops
                        and recovery_elapsed < max_recovery
                    )
                    if is_early:
                        if recovery_started_at is None:
                            recovery_started_at = time.monotonic()
                        early_drop_attempts += 1
                        # log with timing, attempt count, and close code
                        await self._send_connection_lost_event()
                        self.mark_not_ready(reason="Early drop detected")
                        await self._partial_cleanup()
                        await self._early_drop_backoff(early_drop_attempts)
                        continue
                    # Genuine failure — propagate to _serve_wrapper
                    await self._send_connection_lost_event()
                    self.mark_not_ready(reason="WebSocket recv loop failed")
                    raise
```

`EARLY_DROP_RETRYABLE` is a tuple of exception types that qualify for early-drop retry: `(RetryableConnectionClosedError, ServerDisconnectedError)`. This is a subset of the connection-level `RETRYABLE` tuple — it excludes `ClientConnectorError` and `CouldNotFindHomeAssistantError` because those indicate the server is unreachable, not that it dropped a post-auth connection.

### Token revocation detection

Token revocation is handled indirectly. When HA revokes a token on an active connection, it cancels the WebSocket handler, producing a TCP drop indistinguishable from a network failure. The early-drop retry loop reconnects and calls `_make_connection`, which calls `authenticate()`. If authentication fails with `InvalidAuthError`:

1. `InvalidAuthError` is in `NON_RETRYABLE`, so tenacity does not retry
2. `InvalidAuthError` is a `FatalError`, so `_serve_wrapper` calls `handle_crash()`
3. ServiceWatcher sees `CRASHED` and calls `hassette.shutdown()`

The logging improvement: when `_make_connection` raises `InvalidAuthError` during a reconnection (i.e., after at least one early-drop retry), the early-drop loop catches it and logs a distinctive message before re-raising: "Authentication failed on reconnect — possible token revocation."

### `connected` property replacement

Replace private API access:

```python
# Current (fragile)
@property
def connected(self) -> bool:
    if self._ws is None:
        return False
    if self._ws._conn is None:
        return False
    return not self._ws._conn.closed

# Proposed (public API)
@property
def connected(self) -> bool:
    return self._ws is not None and not self._ws.closed
```

`aiohttp.ClientWebSocketResponse.closed` is a documented public property. The theoretical timing gap (transport dead but `closed` not yet flipped) is bounded by the continuous recv loop and the heartbeat mechanism.

### StateProxy disconnect idempotency

`StateProxy.on_disconnect()` currently clears the entity state cache and cancels subscriptions on every DISCONNECTED event. During an early-drop retry cycle (5 retries), this would produce 5 full cache-clear/reload cycles — a 5x load spike against HA's REST API. The fix: `on_disconnect()` must be idempotent — if StateProxy is already not-ready (cache already cleared), subsequent disconnect events are no-ops. The first disconnect clears the cache; the reconnect event triggers a single reload.

### Idempotent, self-suppressing connection-lost event

`_send_connection_lost_event()` must be both idempotent and self-suppressing:

1. **Idempotent**: If the service is already not-ready (`not self.is_ready()`), skip the event. This prevents duplicate DISCONNECTED events when `before_shutdown()` fires during an active early-drop cycle.
2. **Self-suppressing**: The method wraps its own bus dispatch in `suppress(Exception)` internally, so callers never need to add suppress at the call site. This prevents the class of bugs where a bus error replaces the original network exception.

### Close-code logging

Enhance `RetryableConnectionClosedError` to optionally carry the close code from `self._ws.close_code`. This is used for logging only — no behavioral decisions are based on close codes (HA doesn't send distinguishing codes). The close code is logged at WARNING level in the early-drop and disconnect log messages.

## Alternatives Considered

### Single retry layer with higher budget

Instead of three layers, collapse everything into ServiceWatcher with a higher restart budget (e.g., 15 attempts). This would handle early drops by brute force.

Rejected: Each ServiceWatcher restart tears down and rebuilds the entire service (all resources, connections, subscriptions). This is expensive and slow compared to a lightweight reconnect within `serve()`. It also consumes restart budget that should be reserved for genuine failures, and produces noisy logs that obscure the actual issue.

### Connection health probe before marking ready

After authentication and subscription, hold the connection open for N seconds (like the system test's `_ws_probe`) before calling `mark_ready()`.

Rejected: This delays every connection by N seconds, including healthy ones. The early-drop retry approach has zero overhead on healthy connections and only adds latency when the problem actually occurs. The probe approach was already implemented in the system tests as a workaround, not a solution.

### Reconnecting status in ResourceStatus

Add a `RECONNECTING` enum value to `ResourceStatus` to distinguish "reconnecting after early drop" from "running but not ready."

Rejected: The existing `RUNNING` + `mark_not_ready()` combination is semantically correct and already understood by all consumers (ServiceWatcher, readiness checks, status display). A new status would require changes to the state machine, ServiceWatcher, and UI — significant complexity for marginal diagnostic value. The log messages provide sufficient context.

## Test Strategy

### Unit tests (per decomposed method)

- `_connect_ws`: WebSocket opened and authenticated; `ClientConnectorError` with `ConnectionRefusedError` wrapped; `InvalidAuthError` propagated
- `_start_recv_and_subscribe`: recv task spawned, event sent, subscription recorded, `mark_ready()` called, `_connected_at` set
- `_partial_cleanup`: recv task cancelled, WebSocket closed, futures cleared, subscriptions cleared, session preserved; cleanup errors suppressed

### Integration tests (early-drop retry)

- **Early-drop retries and succeeds**: Simulate 2 fast disconnects followed by a stable connection. Verify: `handle_failed` never called, ServiceWatcher restart counter unchanged, 2 connection-lost + 2 connection-established events emitted.
- **Early-drop exhausts budget**: Simulate `max_retries + 1` fast disconnects. Verify: exception propagates out of `serve()`, `mark_not_ready` called on final failure.
- **Stable-connection failure propagates**: Set `_connected_at` to 60 seconds ago (outside stable window). Verify: recv loop failure propagates immediately, no retry.
- **Non-retryable exception in stable window**: `RuntimeError` within the stable window. Verify: propagates immediately, not treated as early drop.
- **Auth failure on reconnect**: First drop is an early drop; reconnection attempt raises `InvalidAuthError`. Verify: distinctive log message, `InvalidAuthError` propagated (fatal).

### Existing test updates

- `test_connected_reflects_websocket_state`: Remove `_conn` mock, test against `_ws.closed` only
- `_build_fake_ws()` helper: Remove `_conn` attribute

### System test impact

The `wait_for_ha_ready()` hold-probe should become unnecessary for test reliability. It may be retained as defense-in-depth but should no longer be the primary mechanism ensuring stable connections during system tests.

## Documentation Updates

- **Config reference** (`docs/`): Add the 8 new configuration fields with types, defaults, and descriptions. Add a subsection explaining the three-layer retry model and when to tune each layer.
- **Docstrings**: `serve()`, `_connect_ws()`, `_start_recv_and_subscribe()`, `_partial_cleanup()` — describe the method's responsibility and where it sits in the connection lifecycle.
- **Architecture page** (if one covers the WebSocket service): Update to reflect the three-layer retry model.

## Impact

### Files modified

| File | Change |
|------|--------|
| `src/hassette/core/websocket_service.py` | Early-drop retry loop, method decomposition, `connected` property, close-code logging |
| `src/hassette/config/config.py` | 8 new config fields |
| `src/hassette/exceptions.py` | Optional `close_code` on `RetryableConnectionClosedError` |
| `tests/integration/test_websocket_service.py` | Update `_build_fake_ws`, remove `_conn` tests, add early-drop tests |
| `src/hassette/core/state_proxy.py` | Idempotent `on_disconnect()` — skip cache-clear when already not-ready |
| `src/hassette/core/runtime_query_service.py` | Fix `get_system_status()` to use `websocket_service.is_ready()` instead of `.status == RUNNING` for `ws_connected` |
| `tests/system/conftest.py` | Evaluate whether `_ws_probe` can be simplified or removed |

### Blast radius

Changes are contained within the WebSocket service and its tests. No other services, resources, or the ServiceWatcher contract are modified. The config additions are purely additive — all defaults match current behavior. The method decomposition changes internal structure but preserves external behavior.

## Open Questions

None — all open questions from the research phase have been resolved:

- **Events during early-drop retry**: Emit connection-lost on drop, connection-established on reconnect (apps need accurate connection state)
- **Stable window basis**: Wall-clock time (simpler, more predictable than message count)
- **send_json during retry**: Fail immediately via `connected` check (no message queuing)
- **System test hold-probe**: Retain as defense-in-depth, evaluate removal separately
