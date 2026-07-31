---
topic: "Explicit WebSocket lifecycle and state sync readiness"
date: 2026-07-29
status: Draft
---

# Prior Art: Explicit WebSocket Lifecycle and State Sync Readiness

## The Problem

Realtime clients need more than a raw WebSocket `open`/`closed` flag. A socket can be open before authentication, subscription setup, initial cache loading, or reconnect resynchronization has completed. Consumers need to know which capability is ready: transport, protocol/session, subscriptions, fresh cache, stale cache, writes, or degraded reads.

This matters for Hassette because startup intentionally continues when Home Assistant is unreachable, while apps must not initialize against an empty cold cache before the first connection/state-sync opportunity has completed. Reconnects also need to preserve stale reads without silently treating a re-opened socket as proof that state is synchronized.

## How We Do It Today

Hassette separates resource lifecycle readiness from Home Assistant connection health: `WebsocketService` marks itself lifecycle-ready while connection attempts continue, and runtime health uses `is_connected` plus `has_ever_connected` to report `starting`, `degraded`, or `ok`. `StateProxy` waits for the first WebSocket success or failed attempt, then loads cache or marks itself ready with degraded-empty state; reconnect resync, polling, and initial load all call the same low-level `load_cache()` but are coordinated by separate paths and guards.

## Patterns Found

### Pattern 1: Layered Lifecycle State Machine

**Used by**: Ably, SignalR, Socket.IO, Phoenix Channels, GraphQL-over-WebSocket clients

**How it works**: Mature realtime clients add application-level states above the native WebSocket states. Ably distinguishes `initialized`, `connecting`, `connected`, `disconnected`, `suspended`, `closing`, `closed`, and `failed`. SignalR distinguishes automatic reconnect after an established connection from initial startup failure. Phoenix separates socket lifecycle from per-channel join/rejoin lifecycle.

For Hassette, this argues for modeling at least transport connection, authenticated/subscribed protocol readiness, and state-cache freshness separately. `socket open` should not imply `StateProxy ready`; the app bootstrap gate should release only after the initial sync barrier has completed or intentionally degraded.

**Strengths**: Makes degraded startup and reconnect behavior testable; avoids unsafe consumers using raw socket state as readiness; gives UI/status reporting precise language.

**Weaknesses**: Too many states can obscure invariants unless transition boundaries are documented. One giant enum can become another overloaded catch-all.

**Example**: https://ably.com/docs/connect/states

### Pattern 2: Initial Snapshot Plus Incremental Stream

**Used by**: Kubernetes watches, Phoenix Presence, Apollo subscription guidance, TanStack Query-style server state

**How it works**: Clients establish a baseline snapshot, then apply streamed changes. Kubernetes clients list resources, record `resourceVersion`, then watch changes after that version; if the watch cannot resume, clients list again. Phoenix Presence sends full `presence_state`, then `presence_diff` updates.

This gives a clear readiness barrier: a cache is synchronized only after the baseline snapshot has been applied. Stream events maintain freshness after that. Reconnect can try to resume from a known offset/version, but if continuity is not guaranteed, the safe fallback is full resync.

**Strengths**: Simple correctness model; easy to test; directly maps to initial load, reconnect resync, and stale-cache transitions.

**Weaknesses**: Full snapshots can be expensive; deltas need ordering/idempotency; streams that arrive before the baseline require buffering or a protocol guarantee.

**Example**: https://kubernetes.io/docs/reference/using-api/api-concepts/#efficient-detection-of-changes

### Pattern 3: Bounded Resume With Explicit Full-Resync Fallback

**Used by**: Socket.IO, Ably, Kubernetes

**How it works**: Reconnect continuity is treated as a bounded optimization, not a guarantee. Socket.IO exposes whether recovery succeeded via `socket.recovered`; Ably distinguishes recoverable `disconnected` from longer `suspended`; Kubernetes returns `410 Gone` when a watch version is too old and requires a fresh list.

Home Assistant state sync should take the conservative version of this pattern unless HA provides reliable offsets: every reconnect should mark cache stale/resyncing and perform a full cache reload before claiming freshness.

**Strengths**: Prevents silent divergence after dropped messages, server restarts, long outages, or browser sleep.

**Weaknesses**: Full resync can be costly and can temporarily keep consumers in stale/degraded mode.

**Example**: https://socket.io/docs/v4/connection-state-recovery

### Pattern 4: Cache Freshness Is Separate From Connection Status

**Used by**: TanStack Query, React Query community, Ably, Apollo Client

**How it works**: Cached data has freshness semantics independent of network state. TanStack Query treats cached data as stale by default and refetches on strategic signals such as reconnect. TkDodo frames React Query as async state synchronization: stale data is often better than no data, but it must be labeled as stale and revalidated.

For Hassette, `connected` should not mean `cache_fresh`, and `disconnected` should not mean `cache_unusable`. A populated cache can remain readable while stale; a cold cache may be degraded-empty; a reconnect should transition through resyncing before fresh.

**Strengths**: Preserves Hassette's degraded startup and stale reads without lying about accuracy.

**Weaknesses**: Consumers need standard policies so every app does not invent its own stale/fresh handling.

**Example**: https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults

### Pattern 5: Readiness Gates Per Capability

**Used by**: Phoenix Channels, SignalR UI examples, Kubernetes list/watch clients, Ably channel attach/resume semantics

**How it works**: A single readiness boolean is too coarse. Consumers wait on the gate they need: transport connected, protocol authenticated, channel/subscription joined, cache synchronized, writes allowed, or stale reads allowed. Gates are released by explicit phase transitions and reset when reconnect invalidates the invariant.

In Hassette, `Resource.is_ready()` can remain the coarse lifecycle/app-bootstrap gate, but the implementation should derive it from explicit `StateSyncPhase` values. Internal code can use narrower capability predicates such as `can_send_control_messages`, `is_subscribed`, `cache_has_data`, and `cache_is_fresh`.

**Strengths**: Prevents startup races and makes degraded mode useful instead of all-or-nothing.

**Weaknesses**: Too many public gates confuse users; keep most gates internal unless app authors need them.

**Example**: [no source found]

### Pattern 6: Configurable Backoff With Jitter and Terminal States

**Used by**: Socket.IO, SignalR, Phoenix Channels, Ably

**How it works**: Reconnect behavior is policy-driven. Socket.IO exposes attempts, delay, maximum delay, timeout, and randomization factor. SignalR lets retry policy stop retrying. Ably moves between retry cadences depending on state and enters `failed` for unrecoverable cases.

Hassette already has retry/backoff configuration, so the prior art does not suggest a new dependency. It does suggest preserving the distinction between transient disconnected, suspended/degraded, and fatal/non-retryable errors if phases are expanded.

**Strengths**: Avoids tight retry loops and thundering herds; makes tests tunable.

**Weaknesses**: Retry policy does not solve cache correctness; reconnect must still trigger sync/freshness decisions.

**Example**: https://socket.io/docs/v4/client-options/

### Pattern 7: Liveness Is Not Application Readiness

**Used by**: MDN WebSocket API, GraphQL-over-WebSocket, Ably, SignalR, TanStack Query

**How it works**: Transport liveness and browser/network status are inputs, not readiness. MDN exposes only `CONNECTING`, `OPEN`, `CLOSING`, and `CLOSED`. GraphQL-over-WebSocket exposes protocol events such as connecting, opened, connected, closed, ping, and pong. TanStack Query warns against treating browser online/offline status as authoritative.

For Hassette, pings and socket openness should keep transport state healthy, but should not release state-dependent app initialization unless the StateProxy sync gate has completed.

**Strengths**: Prevents false readiness and improves diagnostics.

**Weaknesses**: Requires better telemetry because users need to understand why a socket is open while state is still resyncing or degraded.

**Example**: https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/readyState

## Anti-Patterns

- Treating successful reconnect as proof that local state is synchronized. Socket.IO explicitly exposes recovery success because recovery can fail: https://socket.io/docs/v4/connection-state-recovery
- Relying on native WebSocket `readyState` as application readiness. Native states do not cover authentication, subscriptions, cache loading, or degraded mode: https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/readyState
- Assuming platform network status is authoritative. TanStack Query documents false negatives from `navigator.onLine`: https://tanstack.com/query/latest/docs/reference/onlineManager
- Using subscriptions as a universal freshness mechanism. Apollo recommends subscriptions only for incremental real-time updates, with queries/refetch/polling for current state: https://www.apollographql.com/docs/react/data/subscriptions
- Keeping stale incremental offsets forever. Kubernetes requires full relist when historical watch versions are unavailable: https://kubernetes.io/docs/reference/using-api/api-concepts/#efficient-detection-of-changes

## Emerging Trends

- Realtime systems increasingly document recovery as bounded and observable rather than implicit reconnect magic. Socket.IO exposes connection-state recovery, and Ably documents resume/recover limits.
- Watch-style APIs are reducing bootstrap races by combining initial state and stream establishment. Kubernetes documents `sendInitialEvents=true` plus bookmarks for synced resource versions.
- Subscription transports are diversifying, reinforcing that transport choice should be separate from cache synchronization semantics.

## Relevance to Us

The strongest match for Hassette is a layered model: keep `WebsocketService` lifecycle readiness separate from connection health, add explicit WebSocket/protocol phases where they affect behavior, and make `StateProxy` own cache freshness through a single sync coordinator. This fits the existing architecture because Hassette already separates resource readiness from health, already permits degraded startup, and already has a full snapshot path via `api.get_states_raw()` plus incremental HA state events.

The main gap is that Hassette currently encodes important phase distinctions indirectly: `_initialized`, resource readiness, connection booleans, subscription presence, and cache emptiness. Prior art says those should be explicit enough to test, but not necessarily all public. Public app-author bus APIs should stay conservative; richer phase events can be internal or additive metadata.

## Recommendation

Use prior art to refine the original research recommendation, not replace it. Build a two-layer model: WebSocket/protocol phase for transport/auth/subscription semantics, and StateProxy sync phase for cache freshness/app-bootstrap semantics. Treat cache freshness as separate from connection status, and make reconnect perform a conservative full resync unless HA provides a reliable resume token.

Avoid a single mega-enum or public explosion of readiness states. Preserve `RuntimeQueryService`'s existing `starting`/`degraded`/`ok` contract and derive it from richer internals only after the lifecycle is stable.

## Sources

### Reference implementations

- https://socket.io/docs/v4/connection-state-recovery — bounded recovery and explicit recovery success flag.
- https://socket.io/docs/v4/client-options/ — reconnect policy configuration and jitter.
- https://hexdocs.pm/phoenix/js/ — separate socket and channel lifecycle/rejoin behavior.
- https://hexdocs.pm/phoenix/Phoenix.Presence.html — full state plus diff synchronization.
- https://kubernetes.io/docs/reference/using-api/api-concepts/#efficient-detection-of-changes — list/watch, resource versions, resume, and full relist fallback.

### Blog posts & writeups

- https://tkdodo.eu/blog/react-query-as-a-state-manager — stale-while-revalidate framing for server-state caches.

### Documentation & standards

- https://learn.microsoft.com/en-us/aspnet/core/signalr/javascript-client?view=aspnetcore-10.0 — SignalR reconnect states and initial-start retry distinction.
- https://ably.com/docs/connect/states — rich connection state machine with recoverable and terminal phases.
- https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults — stale data, refetch, and cache retention defaults.
- https://tanstack.com/query/latest/docs/reference/onlineManager — online manager caveats and custom online detectors.
- https://www.apollographql.com/docs/react/data/subscriptions — subscriptions as incremental updates, not universal cache freshness.
- https://the-guild.dev/graphql/ws/docs/client/functions/createClient — protocol-level lifecycle event surface.
- https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/readyState — native WebSocket transport states.
