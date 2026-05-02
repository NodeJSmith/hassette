---
topic: "WebSocket Client Connection Management"
date: 2026-05-01
status: Draft
---

# Prior Art: WebSocket Client Connection Management

## The Problem

Long-running automation services that depend on a persistent WebSocket connection to an external system (Home Assistant, in hassette's case) face a reliability problem: the connection will drop. Networks hiccup, HA restarts, proxies time out idle connections, and VPS hosts occasionally have brief outages. What matters is not whether the connection drops, but what happens next — how fast the client detects the failure, how it backs off during reconnection, what happens to application state (subscriptions, scheduled jobs, cached state) during the outage, and how cleanly service resumes.

The problem has several interacting dimensions: **detection** (heartbeats, ping-pong, timeout tuning), **reconnection** (backoff strategy, jitter, max retries), **state management** (do subscriptions survive reconnection? do missed events get replayed?), **authentication** (token refresh before reconnect), and **observability** (connection state visible to the monitoring UI and application code). Most frameworks solve 2-3 of these well and leave the rest to the application.

## How We Do It Today

Hassette's `WebSocketService` (~580 lines) manages a persistent aiohttp WebSocket connection to HA. Reconnection uses `tenacity` with exponential backoff and jitter, with two retry tiers: early drops (rapid failures within a stability window, up to 5 retries) and connection retries (up to 180 attempts, bounded by a ~90-minute global recovery timeout). Auth failures are non-retryable. Heartbeats use aiohttp's built-in `heartbeat` parameter (auto PING/PONG). Connection state is implicit — `self.connected` checks socket status, `is_ready()`/`mark_ready()` track service readiness. Events are emitted on connect/disconnect (`WEBSOCKET_CONNECTED`, `WEBSOCKET_DISCONNECTED`) so the rest of the system can react. Subscriptions are re-established on reconnect via `_subscribe_events()` in the connection setup path. No message buffering during disconnection — pending response futures are cancelled. Graceful shutdown sends GOING_AWAY close code and cancels the recv task with a 2-second timeout.

## Patterns Found

### Pattern 1: Async Iterator Reconnection

**Used by**: Python `websockets` library (v10+)

**How it works**: `connect()` doubles as an async iterator — `async for ws in connect(uri)` yields a new connection on each failure. The iterator applies exponential backoff (3s to 60s) between attempts. `process_exception()` classifies exceptions as retryable (network errors, 5xx) or fatal (auth failures, 4xx). Application code in the loop body must re-establish subscriptions on each new connection. No built-in message buffering.

**Strengths**: Minimal API. Idiomatic Python. Backoff built in. Clean extensibility via exception classification.

**Weaknesses**: No subscription tracking or re-registration. No message buffering. Backoff parameters require subclassing to customize. No jitter by default.

**Example**: https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html

### Pattern 2: Subscription Map with Auto Re-registration

**Used by**: home-assistant-js-websocket (HA frontend), third-party HA dashboards

**How it works**: The connection maintains a `_subscriptions` map storing subscription metadata (original command + callback). On reconnect, the library iterates all entries and replays subscription commands against the new connection. Subscription state is declarative — the library knows what the app *wants* to be subscribed to, not just what it *is*. During disconnection, outgoing messages queue in `_queuedMessages`; if the first reconnect attempt fails, queued messages are rejected. A `suspendReconnectPromise` mechanism defers reconnection (e.g., waiting for token refresh or browser tab focus).

**Strengths**: Automatic subscription re-registration is the killer feature. Register once, library handles reconnection. Message queuing provides basic buffering. Suspend mechanism handles token refresh and background-tab scenarios.

**Weaknesses**: No sequence-number gap detection — events during disconnection are lost. All-or-nothing re-subscription (all restored or connection considered failed). Known issues with unhandled rejections during re-subscription phase.

**Example**: https://github.com/home-assistant/home-assistant-js-websocket/blob/master/lib/connection.ts

### Pattern 3: Explicit Connection State Machine

**Used by**: ASP.NET SignalR, Azure SignalR Service

**How it works**: Four formal states: **Connecting** → **Connected** → **Reconnecting** → Connected (or **Disconnected**). Each transition fires lifecycle events (`onreconnecting`, `onreconnected`, `onclose`). `withAutomaticReconnect()` configures retry — default [0, 2, 10, 30] second schedule, then permanent disconnection. Custom policies support infinite retry with capped backoff. "Stateful reconnect" (Azure) buffers server-side messages during brief disconnections (30s window), allowing seamless resumption.

**Strengths**: Explicit state machine makes connection status observable and testable. Applications react differently to "reconnecting" (warning banner) vs "disconnected" (error, manual reconnect). The [0, 2, 10, 30] schedule is well-tuned. Stateful reconnect eliminates message loss for short outages.

**Weaknesses**: Default four-attempt limit gives up quickly. Stateful reconnect requires Azure (not self-hosted). State machine adds complexity for simple clients.

**Example**: https://learn.microsoft.com/en-us/aspnet/signalr/overview/guide-to-the-api/handling-connection-lifetime-events

### Pattern 4: Dual-Direction Heartbeat

**Used by**: aiohttp, websockets, Socket.IO, virtually all production WebSocket deployments

**How it works**: Two independent liveness checks: the server sends periodic PINGs and expects PONGs (catches dead clients), while the client sends its own heartbeats and expects responses (catches dead servers and zombie connections). Heartbeat interval is tuned via the "75% rule" — take the shortest proxy idle timeout (typically 60s for Nginx/AWS ALB) and multiply by 0.75, yielding ~45s. PONG timeout is typically half the heartbeat interval. In aiohttp: `ws_connect(heartbeat=20)` sends PINGs every 20s, expects PONGs within 10s.

**Strengths**: Catches zombie connections (TCP open, remote unreachable — no FIN/RST). Prevents intermediary idle timeouts. Both sides clean up promptly. 75% rule provides concrete tuning heuristic.

**Weaknesses**: Heartbeat traffic adds overhead at scale. aiohttp's timer resets on any incoming data, delaying zombie detection during traffic-then-silence patterns. If the receive loop blocks, heartbeat responses are delayed, causing false positives.

**Example**: https://websocket.org/guides/heartbeat/ / https://websockets.readthedocs.io/en/stable/topics/keepalive.html

### Pattern 5: Exponential Backoff with Jitter

**Used by**: Socket.IO, SignalR, websockets library, AWS SDK

**How it works**: `delay = min(base * 2^attempt, max_delay)` with jitter via randomization factor (Socket.IO default 0.5, meaning 1x-1.5x actual delay). Prevents thundering herd when a server restarts and all N clients retry simultaneously. Critical detail: the backoff counter resets after a *stable* connection (not just a successful handshake) — a "stability window" (30-60s) should elapse before reset, preventing rapid connect-drop-retry cycles.

**Strengths**: Prevents server overload during recovery. Jitter eliminates synchronized retry storms. Simple, well-understood formula. Configurable for different failure profiles.

**Weaknesses**: During extended outages, clients spend time sleeping at cap. No circuit-breaking inherently. Choosing parameters requires deployment understanding.

**Example**: https://github.com/socketio/socket.io/discussions/4322

### Pattern 6: Cold-Start vs Reconnect Differentiation

**Used by**: AppDaemon, SignalR (onreconnecting vs initial), any system distinguishing first-connect from reconnect

**How it works**: Separate initialization paths for initial connection (cold start) and reconnections (warm restart). Cold start: connect, authenticate, fetch all state, register subscriptions, start applications. Reconnect: reconnect, re-authenticate, sync state delta, re-register subscriptions — but applications are NOT restarted. AppDaemon implements this with separate config keys: `appdaemon_startup_conditions` (cold start) vs `plugin_startup_conditions` (reconnect).

**Strengths**: Preserves application state across reconnections. Faster recovery (skip expensive init). Applications distinguish "starting fresh" from "recovering" in lifecycle hooks.

**Weaknesses**: Two initialization paths = two sets of bugs. State drift if reconnect path doesn't sync properly. Must handle server-restart-during-disconnect (reconnect becomes effectively cold start from server's perspective).

**Example**: https://appdaemon.readthedocs.io/en/latest/HASS_API_REFERENCE.html

### Pattern 7: Token Refresh Gate Before Reconnection

**Used by**: home-assistant-js-websocket, RingCentral WebSocket API, Apollo GraphQL

**How it works**: Before attempting reconnection, check token validity. If expired (or expiring within a buffer window), refresh first. HA's JS library uses `suspendReconnectPromise` — the reconnection loop waits for this promise before the next attempt. This decouples auth lifecycle from transport lifecycle. HA's WS API authenticates via first-message (`{"type": "auth", "access_token": "..."}`) rather than handshake.

**Strengths**: Prevents wasted reconnection attempts with expired tokens. Decouples auth from transport. Auth system handles refresh independently.

**Weaknesses**: Adds latency (must wait for refresh). Blocked reconnection if refresh fails. Race between token check and handshake completion.

**Example**: https://github.com/home-assistant/home-assistant-js-websocket/blob/master/README.md

## Anti-Patterns

- **Relying on TCP keepalive for liveness detection**: Default `TCP_KEEPIDLE` is 7200 seconds — any proxy will kill the connection in 60-100s. TCP probes also don't detect application-level hangs (event loop blocked). WebSocket-level or application-level heartbeats are required. ([source](https://websocket.org/guides/heartbeat/))

- **Fixed-interval reconnection without backoff or jitter**: When a server restarts, all N clients reconnect at identical intervals, creating a thundering herd. AppDaemon uses fixed 5s and gets away with it for single-client scenarios, but it doesn't scale. ([source](https://dev.to/hexshift/robust-websocket-reconnection-strategies-in-javascript-with-exponential-backoff-40n1))

- **Resetting backoff on handshake success instead of stable connection**: If the server accepts the connection but drops it within seconds (load shedding, misconfiguration), the client retries without backoff, creating a rapid connect-drop-retry cycle. Reset only after a stability window (30-60s). ([source](https://dev.to/hexshift/robust-websocket-reconnection-strategies-in-javascript-with-exponential-backoff-40n1))

- **Blocking the receive loop with long-running handlers**: aiohttp's heartbeat depends on the receive loop consuming messages promptly. Long-running handlers block PONG responses, triggering false disconnection detection. ([source](https://github.com/aio-libs/aiohttp/issues/7508))

## Emerging Trends

**Stateful reconnect / session resumption**: Azure SignalR's pattern of allowing clients to resume with the same connection ID within a 30s window, receiving all missed messages. Shifts reliability from application to infrastructure. Currently Azure-specific but the pattern is being adopted by other managed WS services. ([source](https://learn.microsoft.com/en-us/azure/azure-signalr/signalr-concept-client-disconnections))

**Suspend/resume-aware reconnection**: HA's `suspendReconnectPromise` represents a trend toward context-aware reconnection — deferring attempts until conditions are favorable (network available, token valid, tab visible). Reduces wasted attempts and battery drain on mobile. ([source](https://github.com/home-assistant/home-assistant-js-websocket/blob/master/README.md))

## Relevance to Us

Hassette's WebSocket service is **well-designed for its domain** — the dual-tier retry strategy, tenacity-based backoff with jitter, non-retryable auth failures, and event-bus notification of connection state changes are all sound choices.

**What we're doing well:**

- **Exponential backoff with jitter** (Pattern 5) via tenacity — matches the industry standard. The dual-tier approach (early drops vs connection retries) is a refinement that most libraries don't offer.
- **Non-retryable auth failures** — correctly avoids hammering HA with bad credentials, matching the fatal-exception classification in Pattern 1.
- **Subscription re-registration** on reconnect via `_subscribe_events()` — correctly handles the application-state problem, matching Pattern 2's approach (though imperatively rather than declaratively).
- **Heartbeat via aiohttp** (Pattern 4) — delegates liveness detection to the transport layer.
- **Event-bus notification** of connect/disconnect — the rest of the system can react to connection state changes.
- **Receive loop doesn't block** — events are dispatched asynchronously to the bus, avoiding the "blocking receive loop" anti-pattern.

**Gaps worth examining:**

1. **No formal state machine** (Pattern 3): Connection state is implicit (socket-null-check, ready flag). SignalR's explicit state machine with lifecycle events makes connection status observable and testable. A lightweight enum-based state machine (DISCONNECTED → CONNECTING → CONNECTED → RECONNECTING → DISCONNECTED) with transition events would improve debuggability and make it easier to show connection state in the monitoring UI. The infrastructure for this is partially there (WEBSOCKET_CONNECTED/DISCONNECTED events), but the states aren't formalized.

2. **No stability window for backoff reset**: The anti-pattern research highlights that resetting backoff on handshake success (instead of after a stability period) causes rapid connect-drop-retry cycles. Worth verifying whether hassette's dual-tier approach (early drops counted within a stability window) already addresses this — the `_connected_at` timestamp suggests it does, but the interaction with tenacity's retry state may need auditing.

3. **Subscription re-registration is imperative, not declarative** (Pattern 2): Hassette calls `_subscribe_events()` on reconnect, which works. But the HA JS library's pattern of maintaining a subscription map and replaying commands is more robust — if subscription types change (e.g., adding a new event type to subscribe to), the map approach handles it automatically. Currently hassette subscribes to a fixed set of events, so this is a theoretical gap unless dynamic subscriptions are needed.

4. **No message buffering during disconnection**: Pending response futures are cancelled immediately. For hassette's use case this is likely correct — HA events during disconnection are stale by the time connection resumes. But if hassette ever needs to send commands to HA during a brief outage (e.g., a queued service call), a message buffer with timeout would be needed.

## Recommendation

Hassette's WebSocket service is production-quality for its use case. The dual-tier retry strategy is a genuine improvement over what most libraries offer, and the non-blocking receive loop avoids the most common production pitfall.

The most impactful improvement would be **formalizing the connection state machine** — even a simple four-state enum (DISCONNECTED/CONNECTING/CONNECTED/RECONNECTING) with transition logging would make WebSocket issues much easier to debug and would enable the monitoring UI to show real-time connection status. This is additive — it doesn't require changing the reconnection logic, just wrapping it in explicit state tracking.

The subscription-map pattern (Pattern 2) is worth keeping in mind if hassette ever supports dynamic event subscriptions (beyond the current fixed set), but isn't needed today.

## Sources

### Reference implementations
- https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html — websockets async iterator reconnection
- https://github.com/home-assistant/home-assistant-js-websocket/blob/master/lib/connection.ts — HA JS WebSocket client
- https://github.com/marcelveldt/python-hass-client — Python HA client library
- https://docs.aiohttp.org/en/stable/client_reference.html — aiohttp WebSocket client

### Blog posts & writeups
- https://dev.to/hexshift/robust-websocket-reconnection-strategies-in-javascript-with-exponential-backoff-40n1 — Backoff with jitter walkthrough
- https://github.com/socketio/socket.io/discussions/4322 — Socket.IO reconnection strategies
- https://github.com/aaugustin/websockets/issues/414 — websockets reconnection design rationale
- https://github.com/aaugustin/websockets/issues/362 — Graceful close for long-lived clients
- https://github.com/aio-libs/aiohttp/issues/7508 — aiohttp heartbeat + long-running tasks

### Documentation & standards
- https://learn.microsoft.com/en-us/aspnet/signalr/overview/guide-to-the-api/handling-connection-lifetime-events — SignalR connection lifecycle
- https://learn.microsoft.com/en-us/azure/azure-signalr/signalr-concept-client-disconnections — Azure stateful reconnect
- https://websocket.org/guides/heartbeat/ — Heartbeat best practices
- https://websocket.org/guides/reconnection/ — Reconnection state sync guide
- https://websocket.org/guides/best-practices/ — Production WebSocket best practices
- https://websockets.readthedocs.io/en/stable/topics/keepalive.html — websockets keepalive guide
- https://appdaemon.readthedocs.io/en/latest/HASS_API_REFERENCE.html — AppDaemon HA connection
- https://developers.ringcentral.com/guide/notifications/websockets/session-recovery — RingCentral session recovery
