# Design: App Bootstrap and Home Assistant State Lifecycle

**Date:** 2026-07-29
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-07-29-issue-1484-lifecycle/research.md; design/research/2026-07-29-issue-1484-lifecycle/prior-art.md

## Problem

Hassette has no single authoritative answer to "may apps start?" App bootstrap currently depends on `AppHandler`'s resource dependency list, `StateProxy` resource readiness, WebSocket readiness flags, an `_initialized` startup guard, a reconnect-only lock, and incidental bus-event timing. That makes startup and reconnect behavior difficult to reason about and has produced races around cold state reads, duplicate synchronization, and subscription churn.

The current workaround also assigns the wrong meaning to `StateProxy` readiness. It becomes ready after a failed initial state load so all apps can start with an empty cache, even though `self.states` cannot yet provide the state capability apps expect. Conversely, StateProxy becomes not-ready after disconnect while populated stale data remains readable. Resource readiness is therefore being used as app-bootstrap policy rather than as a coherent statement about the cache.

Hassette needs one narrow coordinator that owns the complete one-time app-bootstrap decision. The WebSocket service should report connection capability, StateProxy should report state-cache capability, and the coordinator should compose those capabilities with the other app-facing resources. Until per-app capability declarations exist, all apps must wait for the full capability set, including Home Assistant connectivity and a successfully loaded, actively maintained state cache. The dashboard and other independent framework services must remain available while apps wait.

## Goals

- Provide one authoritative framework component that answers whether apps may bootstrap.
- Start apps only after every app-facing framework capability is initialized and usable.
- Keep the web dashboard available while Home Assistant is unavailable and apps remain blocked.
- Give WebSocket external readiness one meaning: authenticated, receiving replies/events, and subscribed to Home Assistant events.
- Give StateProxy explicit, testable synchronization and freshness semantics without embedding app-bootstrap policy in it.
- Make initial synchronization, reconnect synchronization, polling overlap, event ordering, and obsolete connection work deterministic.
- Preserve stale state reads and existing reconnect recovery for apps that have already started.
- Preserve public app-author APIs and existing runtime health status meanings.

## Non-Goals

- Per-app capability declarations or allowing apps that do not use Home Assistant to start earlier.
- Continuous enforcement that stops or suspends running apps when a capability is later lost.
- Separating internal lifecycle signals from the Home Assistant event stream (#685).
- Defining a broader lifecycle signal taxonomy (#686).
- Exposing richer lifecycle or state-sync phases in the dashboard.
- Isolating framework and app event loops (#1038).
- Building a generic gate-registration or framework-wide orchestration platform.

## User Scenarios

### Framework Runtime: App Bootstrap
- **Goal:** Start apps only when their framework APIs are genuinely usable.
- **Context:** Hassette is starting and Home Assistant may be available immediately, connect late, or remain unavailable.

#### Home Assistant Is Available

1. **Starts independent framework services**
   - Sees: The web API and monitoring surface can initialize independently of Home Assistant connectivity.
   - Decides: App bootstrap must continue waiting for all app-facing capabilities.
   - Then: The bootstrap decision remains closed while connection and state initialization proceed.

2. **Establishes Home Assistant capability**
   - Sees: The WebSocket is authenticated, its receive loop is running, and the Home Assistant event subscription is confirmed.
   - Decides: State synchronization may establish the initial cache capability.
   - Then: StateProxy loads a complete snapshot and installs its state-change listener.

3. **Releases app bootstrap**
   - Sees: API, bus, scheduler, sync execution, and fresh maintained state capabilities are all ready.
   - Decides: Apps may safely initialize.
   - Then: AppHandler bootstraps apps exactly once.

#### Home Assistant Is Unavailable at Startup

1. **Starts the framework without Home Assistant**
   - Sees: WebSocket connection attempts fail or retry while lifecycle-independent services continue.
   - Decides: The dashboard may serve, but app prerequisites are not satisfied.
   - Then: Apps remain unbootstrapped without a fatal framework shutdown.

2. **Connects later**
   - Sees: Home Assistant eventually becomes externally ready and initial state synchronization succeeds.
   - Decides: The complete app-facing capability set is now available.
   - Then: The coordinator releases AppHandler and apps bootstrap without restarting Hassette.

### State Runtime: Reconnect Recovery
- **Goal:** Keep already-running apps' state semantics correct across connection loss and recovery.
- **Context:** Apps have bootstrapped after a successful initial state sync and Home Assistant later disconnects.

#### Recover After Disconnect

1. **Loses the active connection**
   - Sees: The cache is no longer guaranteed current.
   - Decides: Existing state remains readable as stale data, but StateProxy is not fresh.
   - Then: The old state-change listener is canceled and running apps continue.

2. **Establishes a new connection generation**
   - Sees: A new externally ready WebSocket connection is available.
   - Decides: A full snapshot is required because missed events cannot be resumed reliably.
   - Then: StateProxy performs one generation-aware reconnect synchronization.

3. **Restores fresh maintained state**
   - Sees: The snapshot and listener belong to the current connection generation.
   - Decides: The cache may be marked fresh.
   - Then: State reads use the refreshed cache and subsequent events maintain it.

## Functional Requirements

- **FR#1** The framework must expose one authoritative, process-latched release decision for initial app bootstrap.
- **FR#2** The app-bootstrap decision must remain closed until API, bus, scheduler, synchronous execution, and state capabilities are ready.
- **FR#3** App bootstrap must remain blocked while Home Assistant has not reached external WebSocket readiness.
- **FR#4** App bootstrap must remain blocked until an initial state snapshot loads successfully.
- **FR#5** App bootstrap must remain blocked until the initial snapshot and all state changes observed during that snapshot are committed in order.
- **FR#6** The web API must remain available while apps wait indefinitely for Home Assistant prerequisites.
- **FR#7** Apps must bootstrap when delayed Home Assistant connectivity and state capability eventually become available.
- **FR#8** WebSocket external readiness must require successful authentication, a running receive loop, and confirmed Home Assistant event subscription.
- **FR#9** Internal WebSocket setup must be able to send the event-subscription request without claiming external readiness.
- **FR#10** Connected and disconnected public signals must describe transitions into and out of external WebSocket readiness.
- **FR#11** A failed pre-readiness connection attempt must not count as a prior successful connection or emit a disconnected signal.
- **FR#12** StateProxy must distinguish synchronization activity from cache freshness and cache presence.
- **FR#13** A successfully loaded empty Home Assistant snapshot must count as fresh state capability.
- **FR#14** A failed or never-completed initial snapshot must not count as fresh state capability.
- **FR#15** Initial state synchronization must never be skipped or duplicated by concurrent connection signals.
- **FR#16** Concurrent reconnect requests must coalesce into one reconnect synchronization for the current connection generation.
- **FR#17** A polling refresh must not overlap another state synchronization.
- **FR#18** A polling request arriving during active synchronization must be skipped.
- **FR#19** A reconnect arriving during a polling refresh must cause one reconnect synchronization after the poll finishes.
- **FR#20** State synchronization from an obsolete connection generation must not mark the cache fresh.
- **FR#21** State changes received during snapshot synchronization must not be overwritten by an older snapshot value.
- **FR#22** Disconnect after successful app bootstrap must preserve populated cached states for stale reads.
- **FR#23** Cold-cache reads before state capability exists must raise `ResourceNotReadyError`.
- **FR#24** State-change capture must remain installed across reconnect snapshot failures.
- **FR#25** Failed reconnect recovery must not stop or suspend apps that already bootstrapped.
- **FR#26** Runtime health must retain the existing `starting` and `degraded` meanings; `ok` additionally requires that app bootstrap has released, so a permanently-connected WebSocket with permanently-failing state synchronization is not reported as healthy.
- **FR#27** Existing public app-author WebSocket listener APIs must remain source-compatible.
- **FR#28** Invalid authentication must preserve the existing fatal service-failure behavior and require corrected configuration plus process restart.
- **FR#29** Framework shutdown must cancel app-bootstrap capability waits without waiting for Home Assistant recovery.
- **FR#30** No app instance may be created before the authoritative bootstrap release decision opens.
- **FR#31** An entity removed by a state-change event during snapshot synchronization must not be restored from that in-flight snapshot.
- **FR#32** Interactive start and reload requests before bootstrap release must fail immediately with an explicit retryable response.
- **FR#33** Config-change and file-watcher requests before bootstrap release must coalesce into latest desired state without accumulating waiters.
- **FR#34** Every recoverable synchronization failure must have a bounded future retry trigger while its connection generation remains current.

## Edge Cases

- Home Assistant is unavailable for the entire process lifetime; the dashboard serves and apps wait indefinitely.
- Home Assistant connects after multiple failed attempts; apps bootstrap only after the first successful maintained snapshot.
- Authentication succeeds but the Home Assistant event subscription fails.
- WebSocket external readiness succeeds but the initial REST state snapshot fails.
- The initial snapshot succeeds with zero entities.
- The lifetime StateProxy state-change listener fails during Resource initialization.
- A connected signal arrives while initial synchronization is already running.
- Multiple connected signals for the same generation arrive during reconnect synchronization.
- A newer connection replaces the generation whose snapshot is currently loading.
- A disconnect occurs after snapshot loading but before state-change maintenance is confirmed.
- A state-change event arrives while a snapshot request is in flight and contains a newer `last_updated` value than the snapshot.
- Polling fires during initial synchronization or reconnect synchronization.
- Reconnect occurs while a poll is replacing the cache.
- Reconnect snapshot loading fails while the lifetime state-change listener remains active.
- Snapshot loading succeeds but journal commit is abandoned because the connection generation changes.
- Disconnect occurs with a populated cache versus an empty cache.
- Invalid authentication terminates the process through existing supervision; correcting the token requires an external process restart.
- Shutdown begins while the bootstrap coordinator is waiting indefinitely.

## Acceptance Criteria

- **AC#1** `AppHandler` has one bootstrap prerequisite representing the complete app-bootstrap decision rather than directly composing app-facing resources itself. Covers FR#1, FR#2.
- **AC#2** With Home Assistant unavailable, the web API becomes usable while no app instance is bootstrapped. Covers FR#3, FR#6.
- **AC#3** When Home Assistant becomes available later, apps bootstrap without a Hassette restart after the initial snapshot and synchronization-local event journal commit successfully. Covers FR#4, FR#5, FR#7.
- **AC#4** A recoverable initial connection, snapshot, or journal-commit failure leaves apps blocked and allows normal service recovery to continue. Invalid authentication follows AC#25 instead. Covers FR#3, FR#4, FR#5.
- **AC#5** An empty but successfully loaded snapshot with active state-change maintenance releases app bootstrap. Covers FR#13.
- **AC#6** `ConnectionState.CONNECTED`, `is_connected`, `wait_connected()`, `has_ever_connected`, health connectivity, and public connected signals all represent authenticated, receiving, HA-event-subscribed external readiness. Covers FR#8, FR#10.
- **AC#7** WebSocket setup can send and await the HA event-subscription request before advertising external readiness, and advertises readiness only after confirmation. Covers FR#9.
- **AC#8** Subscription failure before external readiness leaves `has_ever_connected` false and emits no connected or disconnected public signal. Covers FR#10, FR#11.
- **AC#9** StateProxy exposes independently testable synchronization status, freshness, and cache-presence semantics. Covers FR#12, FR#13, FR#14.
- **AC#10** Duplicate initial/connected signals do not produce a second initial snapshot or duplicate listener. Covers FR#15.
- **AC#11** Concurrent reconnect requests for one generation perform one reconnect snapshot through the existing lifetime state-change listener. Covers FR#16.
- **AC#12** Poll requests skip while synchronization is active, while reconnect during a poll causes exactly one reconnect synchronization afterward. Covers FR#17, FR#18, FR#19.
- **AC#13** Completion of work for an obsolete connection generation cannot mark StateProxy fresh or release app bootstrap. Covers FR#20.
- **AC#14** A newer state-change event observed during synchronization wins over an older value returned in the snapshot. Covers FR#21.
- **AC#15** Disconnect with populated cache permits stale reads, while not-ready empty-cache reads raise `ResourceNotReadyError`. Covers FR#22, FR#23.
- **AC#16** The lifetime state-change listener remains installed through reconnect snapshot failure without marking the failed snapshot fresh. Covers FR#24.
- **AC#17** A runtime disconnect marks state stale but does not stop or suspend already-running apps. Covers FR#25.
- **AC#18** Runtime health remains `starting` before first external connection, `degraded` after losing a prior external connection or while externally connected without bootstrap release, and `ok` only while externally connected with bootstrap released. Covers FR#26.
- **AC#19** Existing `on_websocket_connected` and `on_websocket_disconnected` handlers work without signature changes. Covers FR#27.
- **AC#20** Shutdown cancels an indefinitely waiting bootstrap coordinator without delaying framework shutdown. Covers FR#29.
- **AC#21** The shared app-creation boundary prevents every caller from creating an app before release; after release, runtime disconnects do not re-block creation. Covers FR#25, FR#30.
- **AC#22** An entity deleted by an event while a snapshot is in flight remains absent even when the returned snapshot contains its older state. Covers FR#21, FR#31.
- **AC#23** Manual HTTP start/reload requests before release return an explicit retryable conflict/unavailable response without retaining a waiting task. Covers FR#32.
- **AC#24** Repeated config and file-watcher changes before release retain only the latest desired reconciliation state and run one reconciliation after release. Covers FR#33.
- **AC#25** Invalid authentication terminates Hassette through existing fatal supervision and requires corrected configuration plus process restart. Covers FR#28.
- **AC#26** A recoverable synchronization failure retries on the next poll, or through one coalesced generation-scoped timer when polling is unavailable, and obsolete retries are canceled. Covers FR#34.

## Key Constraints

- Do not use `StateProxy.is_ready()` as a proxy for the global app-bootstrap decision.
- Do not permit degraded app bootstrap with an unavailable or never-successfully-loaded state capability in this change.
- Do not make dashboard startup depend on Home Assistant connectivity or app-bootstrap readiness.
- Do not introduce a generic condition registry, dynamic gate registration, or per-app capability model.
- Do not use public bus signal delivery as the correctness boundary between WebsocketService, StateProxy, and app-bootstrap coordination.
- Do not treat socket liveness, authentication alone, or private send capability as external WebSocket readiness.
- Do not rely only on locking to reject work from obsolete WebSocket connection generations.
- Do not rely on sleeps in race tests; use deterministic synchronization primitives.
- Do not change existing public WebSocket listener handler signatures.

## Dependencies and Assumptions

- Home Assistant remains the authoritative state source.
- Home Assistant does not provide a reliable missed-state-event resume token, so reconnect requires a complete snapshot.
- All apps currently receive the same bootstrap policy because app manifests do not declare capability requirements.
- `ApiResource`, `BusService`, `SchedulerService`, `SyncExecutorService`, and StateProxy state capability comprise today's complete app-facing prerequisite set.
- Existing resource dependency waves and service supervision remain authoritative for transient connection failures, retries, restart budgets, invalid-auth fatal exit, and shutdown cancellation.
- RuntimeQueryService remains authoritative for dashboard/API health summaries.
- No persistent data format or database schema changes are required.

## Architecture

### Ownership Boundaries

The lifecycle is divided into four explicit owners:

| Component | Responsibility |
|---|---|
| `WebsocketService` | Transport/protocol capability, external connection readiness, connection generation, and first-success history |
| `StateProxy` | Cache contents, snapshot synchronization, cache freshness, state-change maintenance, polling, and reconnect recovery |
| `AppBootstrapCoordinator` | One-time policy decision that the complete app-facing capability set is available |
| `AppHandler` | Loading, initializing, supervising, reloading, and stopping apps |

Correctness-critical coordination uses direct internal capability methods and resource dependencies. Public bus signals remain observational and source-compatible; they do not release app bootstrap or certify cache freshness.

### AppBootstrapCoordinator Resource

Add `AppBootstrapCoordinator` as a narrow `Resource` in `src/hassette/core/app_bootstrap_coordinator.py`. It is not a `Service`: it has no independent background serve loop, restart policy, or continuous runtime enforcement.

Its declared dependencies are the complete ordinary app-facing resource set:

- `ApiResource`
- `BusService`
- `SchedulerService`
- `StateProxy`
- `SyncExecutorService`

The ordinary resource lifecycle automatically waits for these resources to initialize. StateProxy lifecycle readiness remains non-blocking so its startup wave cannot prevent WebApiService and other later framework resources from starting while Home Assistant is unavailable. Lifecycle readiness only means the StateProxy resource is running and able to pursue synchronization.

After dependency auto-wait completes, AppBootstrapCoordinator marks itself lifecycle-ready so the finite root startup wave can finish. It then waits for StateProxy's separate initial-capability API in coordinator-owned background work. That capability completes only after the current externally ready WebSocket generation has a successful snapshot, the Resource-lifetime listener has captured concurrent events in a synchronization-local journal, and one generation-fenced commit has applied the snapshot and journal. StateProxy's capability therefore subsumes the WebSocket prerequisite; AppBootstrapCoordinator does not separately depend on or interpret WebsocketService.

The coordinator publishes a separate process-latched release capability such as `wait_released()`. This latch, not Resource readiness, has the meaning **apps may initialize code**. It opens once, never closes after runtime disconnect, and is canceled by coordinator shutdown so no waiter can delay teardown. The coordinator's ordinary Resource readiness means only that its prerequisites and background wait are wired.

`AppHandler.depends_on` is reduced to `[AppBootstrapCoordinator]`, which guarantees the coordinator itself is wired but does not release app creation. AppHandler does not duplicate the coordinator's prerequisite list or inspect WebSocket/StateProxy phases. All app-creation paths explicitly consult the coordinator's release capability, making it the single place to answer and evolve the global bootstrap policy.

Enforcement lives at the lowest shared mutation boundary: `AppLifecycleService.start_app()` accepts an internal admission mode and checks the coordinator release immediately before app instance creation. No facade, HTTP route, file-watcher path, reset helper, or internal reconciliation can bypass this guard.

Admission behavior is caller-specific and bounded:

- Initial bulk bootstrap calls the shared boundary with `WAIT_FOR_RELEASE`; it is the one AppLifecycleService task allowed to await the coordinator latch.
- Manual HTTP start/reload calls use `REJECT_IF_UNRELEASED`; the boundary raises a typed internal not-released error that web routes map to `409 Conflict` or `503 Service Unavailable`. They do not retain tasks.
- Config-change and file-watcher handlers do not call `start_app()` while unreleased. AppLifecycleService owns one latest desired-state/reconciliation record. Repeated changes overwrite/coalesce that record rather than queuing callbacks. A single AppLifecycleService task awaits release and then reconciles through the shared creation boundary using the latest manifests and changed paths.
- Test/reset helpers must select an admission mode explicitly; there is no unchecked creation entrypoint.
- Once released, the process latch remains open: later disconnects do not re-block starts/reloads and do not stop running apps.

`RuntimeQueryService.depends_on` removes `AppHandler`. AppHandler and its `AppRegistry` are constructed before lifecycle startup, so RuntimeQueryService can safely query them while AppHandler is still waiting to bootstrap. Before bootstrap, `overlay_manifest_rows()` and `get_registry_only_apps()` may read configured registry metadata; `get_app_status_snapshot()` may return an empty live-instance snapshot; `get_system_status()` reports `app_count=0`; and `collect_boot_issues()` reports only issues already represented in the registry. These paths update through their existing mechanisms after apps start. RuntimeQueryService continues to depend on the services required to install its subscriptions and log broadcasting, but it must not transitively gate WebApiService on app bootstrap. This preserves dashboard availability without inventing a new pending-app status in this issue.

Removing the dependency also removes reverse shutdown ordering. RuntimeQueryService therefore becomes explicitly tolerant of concurrent AppHandler teardown: registry reads retain their existing guarded empty-result behavior, app-state handlers are idempotent when registry entries disappear, and shutdown cancels subscriptions without requiring a final app-stopped broadcast. Missing final UI-only events during process teardown is acceptable because the web transport is shutting down and no durable state depends on those broadcasts; this issue does not add a second teardown-edge model to the Resource graph.

This coordinator is intentionally concrete. It does not accept dynamically registered conditions, expose a generic gate API, or evaluate per-app manifests. If per-app capability declarations are introduced later, this component is the natural migration point for evaluating an app-specific policy.

### WebSocket Capability and Generation

Keep `ConnectionState` and the validated `WS_VALID_TRANSITIONS`/`set_connection_state()` pattern in `src/hassette/core/websocket_service.py`. `ConnectionState.CONNECTED` becomes exclusively the external state: authentication succeeded, the receive loop is running, and Home Assistant confirmed the HA event subscription.

Add a private send-capability event or equivalent predicate:

1. Authentication completes.
2. The receive loop starts so request futures can receive replies.
3. Private send capability opens.
4. WebsocketService sends and confirms the HA event subscription.
5. The connection generation increments.
6. `ConnectionState.CONNECTED`, `_connected_event`, `_ever_connected`, and `_connected_at` update.
7. The public connected signal emits.

`send_json()` uses private send capability rather than `is_connected`, allowing setup requests without exposing premature external readiness. Cleanup clears private send capability before closing the socket and resolving pending requests.

Each successful transition into external readiness receives a monotonically increasing integer generation. Direct internal consumers can obtain the current generation and wait for a connected generation without changing public bus event payloads. Disconnect invalidates that generation as active but does not decrement or reuse it. StateProxy compares the generation before committing freshness so old work cannot certify a replaced connection.

WebsocketService lifecycle readiness remains independent from connection readiness: `on_initialize()` still marks the service lifecycle-ready so lifecycle-independent services can start while Home Assistant is unreachable or transiently failing. Invalid authentication is explicitly outside the recoverable blocked-startup guarantee: existing supervision terminates the process, and recovery requires corrected configuration plus external restart. Other connection failures, retries, and restart exhaustion remain under existing supervision.

### State Capability Model

StateProxy tracks separate facts rather than one enum that combines operation, freshness, lifecycle, and failure cause:

- **Synchronization status:** idle, synchronizing initial state, synchronizing reconnect state, or refreshing by poll.
- **Cache freshness:** unavailable, fresh, or stale.
- **Cache presence:** derived from whether the cache contains entities; this remains independent from freshness because a successful fresh snapshot may be empty.
- **Maintained generation:** the active WebSocket generation whose snapshot and journal passed the freshness barrier.

Published cache data, freshness, and source generation remain separate internal fields, but synchronization may update them only through one lock-protected fenced commit. Existing lock-free state readers remain unchanged because whole state dictionaries and entity objects are replaced rather than mutated.

These values remain internal framework state rather than new app-author APIs. StateProxy resource readiness means **the StateProxy lifecycle is running**, not that initial state capability exists. A separate direct capability wait means **initial state capability exists**: a snapshot loaded successfully, its associated state-change listener is active, and both belong to the current connected generation. This wait never completes merely because an initial attempt ended in failure.

On disconnect after successful initialization, StateProxy marks its cache stale while retaining lifecycle readiness and cached data. This does not revoke `AppBootstrapCoordinator` readiness or stop apps: the coordinator makes a one-time bootstrap decision rather than continuously enforcing capabilities. Existing stale-read behavior remains based on cache presence and freshness, not Resource readiness alone.

### State Synchronization Coordinator

Replace StateProxy's split `on_initialize()`, `on_reconnect()`, polling, `_initialized`, and `_reconnect_lock` decisions with one internal synchronization coordinator. StateProxy installs one stable internal state-change listener for its Resource lifetime rather than canceling and recreating it on disconnect/reconnect. The coordinator handles snapshot replacement, generation fencing, and journal barriers while retaining `FairAsyncRLock` as the cache-write lock.

The request policy is explicit:

- Initial synchronization cannot be skipped and runs once for the first externally ready generation that can establish state capability.
- Additional connected signals while initial synchronization is active coalesce with that work.
- Reconnect requests for the same active generation coalesce.
- Poll requests skip while any synchronization is active.
- A reconnect request arriving during a poll records one pending reconnect; it runs after the poll finishes.
- A pending reconnect is superseded by a newer generation before execution.
- No work may mark the cache fresh unless its generation is still active when snapshot merge and event-journal commit finish.

Polling refreshes only the snapshot for the currently maintained generation. Polling does not alter listener ownership or independently turn stale/disconnected state fresh. Reconnect synchronization establishes a new generation's snapshot/journal barrier through the existing lifetime listener.

### Snapshot and Event Ordering

StateProxy must prevent events received during a full snapshot request from being lost or overwritten. The lifetime listener accepts only events associated with the active WebSocket generation. At each synchronization start, StateProxy opens one synchronization-local operation journal before issuing the snapshot request. Event handlers update the live cache under the existing lock and append ordered upsert/removal operations while that synchronization is active. After the response arrives, the coordinator builds a candidate state dictionary off-lock. Timestamps may help reconcile untouched pre-sync cache values, but journaled operations always win regardless of equal, absent, or malformed `last_updated` values:

- Snapshot entities reconcile untouched pre-sync values using existing freshness semantics.
- Journaled state-change upserts overwrite snapshot values in observed order.
- Journaled removals act as tombstones and remove entities even when the snapshot contains older values.
- Entities absent from the full snapshot are removed unless the journal added or updated them.

Under the cache lock, one fenced commit revalidates synchronization request identity and active generation, incorporates every journal operation appended before lock acquisition, replaces `states`, updates freshness/source generation, and opens initial capability when applicable. Because event handlers use the same lock, an event is either included in that journal/commit or runs afterward against the committed cache; no BusService-wide barrier API is required. No obsolete request may mutate cache contents, freshness, source generation, or release capability. Synchronization-local records are cleared only by request-ID-conditional cleanup after successful commit or abandonment.

### Failure Semantics

Initial capability requires a successful snapshot plus lifetime-listener journal and fenced commit for the active generation. Any failure leaves the initial-capability wait unresolved and apps blocked indefinitely while StateProxy remains lifecycle-ready and normal WebSocket/reconnect recovery continues. A fresh empty snapshot is success; a failed empty snapshot is not.

The lifetime listener remains installed even if snapshot loading fails. Partial outcomes are represented by separate freshness and maintained-generation facts:

- Snapshot, journal, and fenced commit succeed for the active generation: cache fresh.
- Snapshot fails: cache remains stale; the listener remains installed so subsequent events can improve individual entities.
- Journal/commit fails or the generation changes: cache remains stale and the candidate is abandoned without publishing capability.

Every recoverable synchronization failure has a bounded future trigger without introducing a second retry subsystem:

- When polling is enabled, the next scheduled poll is the normal convergence path for snapshot or commit failure on a still-healthy generation.
- Before the poll job exists, or when polling is disabled, the coordinator maintains at most one coalesced generation-scoped retry timer using existing backoff conventions.
- A newer generation replaces pending retry intent; disconnect and shutdown cancel it.
- Programming errors surface through normal logging/error handling rather than retrying indefinitely.

These runtime failures do not stop already-running apps. Existing service supervision handles fatal/non-retryable failures; AppBootstrapCoordinator does not duplicate that logic.

### Health Semantics

`RuntimeQueryService.get_system_status()` derives external health from WebsocketService and `AppBootstrapCoordinator.is_released()`:

- `starting`: no connection generation has ever reached external readiness.
- `degraded`: external readiness was reached previously but is not current, or WebsocketService is externally ready while app bootstrap has not yet released.
- `ok`: WebsocketService is externally ready and app bootstrap has released.

This is a deliberate amendment to the original plan: deriving health from WebsocketService alone leaves one uncovered failure mode — WebsocketService can stay externally ready indefinitely while the initial state snapshot keeps failing (malformed response, HA-side bug), so `is_released()` never fires. Without folding release into `status`, that combination reports `ok` forever while every app stays permanently unbootstrapped, which is a materially misleading health signal, not a cosmetic gap. Because `is_released()` is a one-time latch, this does not reintroduce continuous bootstrap enforcement or a later runtime disconnect re-blocking `ok`: once released, only WebsocketService's current external readiness continues to gate `ok`/`degraded`.

While HA is unavailable at cold startup, health remains `starting`, the web API serves, and apps remain unbootstrapped. Richer explanation of app-bootstrap or state-sync phases beyond this `status` value (e.g., a dedicated dashboard indicator distinguishing "waiting on HA" from "waiting on snapshot success") remains deferred.

## Implementation Preferences

No specific implementation preferences beyond the decisions above; follow codebase conventions and use existing async primitives and lifecycle helpers. Do not add runtime dependencies.

## Replacement Targets

- Replace `StateProxy._initialized` in `src/hassette/core/state_proxy.py` with explicit initial synchronization state and generation-aware work classification; remove the boolean outright.
- Replace `StateProxy._reconnect_lock` and scheduler-only overlap assumptions with the synchronization coordinator and explicit request policy; retain the separate cache-write lock.
- Replace initial failure behavior that treats an empty/failed cache as initial state capability; StateProxy remains lifecycle-ready, but its separate initial-capability wait stays unresolved until capability succeeds.
- Replace direct app-facing dependencies in `AppHandler.depends_on` with `AppBootstrapCoordinator` as the sole bootstrap policy dependency.
- Replace `ConnectionState.CONNECTED` as a temporary internal send gate with private send capability; retain `CONNECTED` only for external readiness.
- Replace listener cancellation/recreation with one Resource-lifetime listener and generation-fenced operation journals.
- Replace blind full-dictionary snapshot assignment with a generation-fenced, event-preserving snapshot transaction under the existing cache lock.

## Convention Examples

### Validated Lifecycle Transitions

**Source:** `src/hassette/core/websocket_service.py`

```python
WS_VALID_TRANSITIONS: dict[ConnectionState, frozenset[ConnectionState]] = {
    ConnectionState.DISCONNECTED: frozenset({ConnectionState.CONNECTING}),
    ConnectionState.CONNECTING: frozenset({ConnectionState.CONNECTED, ConnectionState.DISCONNECTED}),
    ConnectionState.CONNECTED: frozenset({ConnectionState.CONNECTING, ConnectionState.DISCONNECTED}),
}

def set_connection_state(self, new: ConnectionState) -> None:
    old = self._connection_state
    if old == new:
        return
    allowed = WS_VALID_TRANSITIONS.get(old, frozenset())
    if new not in allowed:
        ...
    self._connection_state = new
```

### Module-Level Readiness Helpers

**Source:** `src/hassette/core/app_handler.py`

```python
async def after_initialize(self) -> None:
    self.logger.debug("Bootstrapping apps")
    await self.lifecycle.bootstrap_apps()
    mark_ready(self, reason="apps-bootstrapped")

async def on_shutdown(self) -> None:
    mark_not_ready(self, reason="shutting-down")
    await self.lifecycle.shutdown_all()
```

### Stale Reads Only With Cache

**Source:** `src/hassette/core/state_proxy.py`

```python
def _check_ready(self) -> None:
    if not self.is_ready() and not self.states:
        raise ResourceNotReadyError(f"StateProxy is not ready (reason: {self._ready_reason}).")

def get_state_once(self, entity_id: str) -> "HassStateDict | None":
    self._check_ready()
    return self.states.get(entity_id)
```

### Event Freshness Guard

**Source:** `src/hassette/core/state_proxy.py`

```python
if (
    entity_id in self.states
    and (curr_last_updated := self.states[entity_id].get("last_updated")) is not None
    and (new_last_updated := new_state_dict.get("last_updated")) is not None
):
    if new_last_updated <= curr_last_updated:
        return
```

### Deterministic Async Race Gate

**Source:** `tests/integration/test_state_proxy.py`

```python
gate = asyncio.Event()
first_call_entered = asyncio.Event()

async def gated_get_states_raw():
    first_call_entered.set()
    await gate.wait()
    return [make_light_state_dict("light.kitchen", "on")]

task1 = asyncio.create_task(state_proxy.on_reconnect())
task2 = asyncio.create_task(state_proxy.on_reconnect())
await asyncio.wait_for(first_call_entered.wait(), timeout=1.0)
assert not task1.done()
assert not task2.done()
```

## Alternatives Considered

### Keep Bootstrap Policy in StateProxy

Rejected because state-cache capability and global app-bootstrap policy are separate concerns. It would preserve the confusing meaning where StateProxy readiness can mean either fresh cache, stale cache, or intentional empty degradation depending on the caller.

### Put Bootstrap Policy in AppHandler

Rejected because AppHandler would need to understand the readiness semantics of every app-facing service and would accumulate future bootstrap policy alongside app loading and supervision. A dedicated Resource keeps AppHandler focused and provides one authoritative decision point.

### General-Purpose Startup Coordination Platform

Rejected as premature. The current requirement is a concrete global app-bootstrap policy. Dynamic gate registration, arbitrary condition composition, and per-app policies add complexity without a second demonstrated use case.

### Preserve Degraded App Startup Without Home Assistant

Rejected because every app currently receives `self.states`, and the framework cannot know which apps safely tolerate an unavailable initial state capability. Until per-app capability declarations exist, starting all apps degraded can expose preventable startup exceptions and empty-state behavior.

### Use Public Bus Signals for Correctness Coordination

Rejected because delivery timing, shared event-stream backpressure, and payloadless connected events are unsuitable as the sole correctness boundary. Public signals remain useful observations, while direct capabilities establish lifecycle invariants.

### Serialize Every Sync Request

Rejected because duplicate reconnect and poll requests would perform redundant full snapshots and listener churn. Explicit coalescing/skipping preserves required work while making races deterministic.

## Test Strategy

### Existing Tests to Adapt

- `tests/integration/test_dashboard_without_ha.py`: change the expected no-HA behavior from degraded app bootstrap to dashboard-ready/apps-blocked, then verify delayed HA releases bootstrap.
- `tests/e2e/test_dashboard_without_ha.py`: update app-status expectations while preserving web availability and health output.
- `tests/system/test_startup_without_ha.py`: preserve non-fatal dashboard startup but assert apps remain pending without HA.
- `tests/integration/test_state_proxy.py`: replace `_initialized` and `_reconnect_lock` assertions with synchronization status, freshness, generation, coalescing, polling, and merge-order assertions.
- `tests/integration/test_websocket_service.py`: separate private send capability from external readiness and update connected-event ordering tests.
- `tests/unit/core/test_ws_connection_state.py`: cover any transition or generation changes while preserving strict transition validation.
- `tests/unit/core/test_websocket_readiness_events.py`: assert public signals and `has_ever_connected` change only at external readiness.
- `tests/unit/core/test_state_proxy_yield_retry.py`: preserve cold-cache retry and stale-cache read semantics under the new readiness contract.
- RuntimeQueryService/web API tests: verify `overlay_manifest_rows()` and `get_registry_only_apps()` can read pre-bootstrap metadata, `get_app_status_snapshot()` may be empty, `get_system_status()` reports zero live apps, and all relevant views update when delayed bootstrap completes.
- RuntimeQueryService shutdown tests: registry clearing and app-state events concurrent with observer shutdown are tolerated without exceptions or delayed teardown.
- Test fixtures under `src/hassette/test_utils/` that force StateProxy ready or mock `wait_initial_connection()`: update them to model state capability and the bootstrap coordinator explicitly.

### New Test Coverage

- Unit: AppBootstrapCoordinator declares and composes the complete prerequisite set, becomes lifecycle-ready without HA, keeps its release latch closed, and AppHandler depends on it alone. Covers FR#1, FR#2, FR#6.
- Integration: web API serves while HA is unavailable and apps remain absent indefinitely. Covers FR#3, FR#6.
- Integration: the explicitly supported pre-bootstrap RuntimeQueryService paths return the behavior defined in Architecture and reflect apps after delayed bootstrap. Covers FR#6, FR#7.
- Integration: delayed HA connection plus successful snapshot/listener releases app bootstrap exactly once. Covers FR#4, FR#5, FR#7.
- Integration: failed initial snapshot or listener leaves apps blocked until a later successful generation. Covers FR#4, FR#5, FR#14.
- Integration: a successful zero-entity snapshot releases bootstrap. Covers FR#13.
- Integration: HA event subscription is possible through private send capability before external readiness. Covers FR#8, FR#9.
- Unit/integration: pre-readiness subscription failure does not set connection history or emit connected/disconnected signals. Covers FR#10, FR#11.
- Unit: synchronization status, freshness, cache presence, and maintained generation represent independent combinations. Covers FR#12.
- Integration: duplicate startup and reconnect signals coalesce according to the request policy. Covers FR#15, FR#16.
- Integration: polls skip during sync and reconnect during poll runs once afterward. Covers FR#17, FR#18, FR#19.
- Integration: obsolete generation work cannot mark fresh or release bootstrap. Covers FR#20.
- Unit/integration: obsolete or canceled work cannot mutate cache contents, freshness, source generation, or release capability. Covers FR#12, FR#20.
- Integration: newer state events received during snapshot loading survive snapshot merge, including concurrent additions and removals. Covers FR#21.
- Integration: disconnect retains populated stale cache while empty cold cache raises. Covers FR#22, FR#23.
- Integration: the lifetime listener remains installed after snapshot failure without marking stale cache fresh. Covers FR#24.
- Integration: events accepted during snapshot loading are journaled and committed before initial capability or freshness publishes. Covers FR#5, FR#21.
- Integration: failed synchronization converges through the next poll, or through one coalesced retry timer when polling is unavailable; retries cancel on supersession/shutdown. Covers FR#14, FR#20, FR#34.
- Integration: disconnect after bootstrap leaves apps running. Covers FR#25.
- Unit/integration: health retains starting/degraded/ok mapping. Covers FR#26.
- Unit: public WebSocket convenience handlers remain source-compatible. Covers FR#27.
- Integration/system: invalid auth preserves fatal process termination rather than recoverable dashboard-only startup. Covers FR#28.
- Integration: shutdown cancels an unresolved initial-capability wait without waiting for HA recovery. Covers FR#29.
- Integration: every path converging on `AppLifecycleService.start_app()` is unable to create an instance before release, while creation after release remains allowed across disconnects. Covers FR#25, FR#30.
- Web route: manual start/reload before release returns the selected typed retryable status and retains no waiting task. Covers FR#32.
- Integration: repeated config/file changes before release retain one latest desired reconciliation and execute it once after release. Covers FR#33.
- Integration: delete events received during snapshot loading create tombstones and are not resurrected by the returned snapshot. Covers FR#21, FR#31.

### Tests to Remove

- Remove or rewrite tests that assert `ConnectionState.CONNECTED` is a pre-subscription internal send gate.
- Remove or rewrite tests that assert `StateProxy._initialized` or `_reconnect_lock` implementation details.
- Remove expectations that a failed first Home Assistant opportunity makes StateProxy ready or permits app bootstrap with an empty cache.

## Documentation Updates

- `CLAUDE.md`: document AppBootstrapCoordinator ownership, strict initial app prerequisites, StateProxy capability semantics, WebSocket external readiness, and changed no-HA app behavior.
- User-facing docs: no docs-site update is required because no app-author API changes; startup behavior should be included in release notes through the conventional commit generated changelog.
- Follow-up issue documentation: update or create the per-app capability declaration issue to reference AppBootstrapCoordinator as the intended migration point.

## Impact

### Changed Files

- Create `src/hassette/core/app_bootstrap_coordinator.py`: own the one-time complete app-bootstrap readiness policy.
- Modify `src/hassette/core/core.py`: construct and expose the bootstrap coordinator in the resource graph.
- Modify `src/hassette/core/app_handler.py`: depend only on AppBootstrapCoordinator for bootstrap readiness.
- Modify `src/hassette/core/app_lifecycle_service.py`: enforce release admission at the shared app-creation boundary and coalesce pre-release desired-state reconciliation.
- Modify `src/hassette/web/routes/apps.py`: map the typed unreleased error for manual start/reload to an explicit retryable HTTP response.
- Modify file/config change handling in `src/hassette/core/app_lifecycle_service.py` and `src/hassette/core/app_handler.py`: retain one latest desired reconciliation until release.
- Modify `src/hassette/core/websocket_service.py`: add private send capability, external-readiness ordering, direct generation capability, and cleanup behavior.
- Modify `src/hassette/core/state_proxy.py`: add explicit capability facts, generation-aware sync coordination, snapshot/event merge ordering, and strict initial readiness.
- Modify `src/hassette/types/enums.py`: add only synchronization/freshness enums that are useful outside one local implementation; keep local-only enums local.
- Modify `src/hassette/core/runtime_query_service.py`: remove AppHandler as a lifecycle dependency while continuing to query its already-constructed registry; preserve response schemas and health mapping.
- Modify affected test and test-utility files listed in Test Strategy.
- Modify `CLAUDE.md`: record final lifecycle architecture and behavior.

### Behavioral Invariants

- WebsocketService resource readiness means its lifecycle is running, not that Home Assistant is connected.
- The dashboard and web API can initialize without Home Assistant.
- No disconnected public signal fires before the first externally ready connection.
- Health is `starting` before first external readiness, `degraded` after losing prior external readiness, and `ok` while externally ready.
- A fresh Home Assistant snapshot may legitimately contain zero entities.
- Populated cached state remains readable as stale data after disconnect.
- Empty cold-cache reads before capability exists raise `ResourceNotReadyError`.
- Reconnect performs a full snapshot because missed events cannot be resumed reliably.
- The lifetime state-change listener remains installed when reconnect snapshot loading fails.
- Polling remains optional through `disable_state_proxy_polling`.
- Existing public WebSocket bus listener APIs remain source-compatible.
- Existing resource/service supervision remains responsible for retries, non-retryable failures, restart budgets, and shutdown.

### Blast Radius

This changes core startup semantics and intentionally changes no-HA behavior for apps: they no longer bootstrap degraded with an unavailable initial state capability. It affects the resource graph, app startup timing, WebSocket event ordering, StateProxy synchronization and reads, runtime health inputs, framework test harnesses, and startup/system tests. The web API remains independently available. Unit and integration tests provide the development gate; system and e2e CI remain the safety net for real lifecycle ordering.

## Open Questions

None.
