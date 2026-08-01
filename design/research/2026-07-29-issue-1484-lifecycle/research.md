# Research Brief: Model WebSocket and State Sync Lifecycle Explicitly

**Proposal**: Issue 1484 — replace the current WebSocket/StateProxy startup and reconnect coordination with explicit, testable lifecycle phases and one serialized state-sync path.

**Date**: 2026-07-29
**Status**: Draft
**Flexibility**: Leaning
**Motivation**: Best architecture — evaluate the right lifecycle/state-machine model before designing it.
**Constraints**: Preserve degraded startup without Home Assistant, preserve app bootstrap safety after PR #1483, include WebSocket, StateProxy, AppHandler, bus events/metadata where relevant, runtime/dashboard health behavior, and system/e2e implications.
**Depth**: normal

## Context

### What prompted this

Issue 1484 is a follow-up to PR #1483 (`fce67d35 fix: wait for initial WebSocket before state sync (#1483)`). The issue body says the minimal fix prevented StateProxy from initializing apps against an empty cold cache before the first Home Assistant WebSocket/state sync opportunity, but left coordination spread across readiness flags, bus events, and a local `_initialized` guard. That is Direct evidence from `gh issue view 1484` and the commit history.

### Current state

The current model has two overlapping state systems:

- **Resource lifecycle readiness** (`mark_ready`, `mark_not_ready`, `is_ready`) reports whether a resource is lifecycle-ready. `WebsocketService.on_initialize()` marks itself ready unconditionally so startup can continue when HA is unavailable (`src/hassette/core/websocket_service.py:136-145`).
- **WebSocket connection state** is a small `ConnectionState` enum with `DISCONNECTED`, `CONNECTING`, and `CONNECTED` (`src/hassette/types/enums.py:234-244`). `WebsocketService.set_connection_state()` validates transitions and manages `_ever_connected` and `_connected_event` (`websocket_service.py:161-203`).

StateProxy currently coordinates initial and reconnect sync as separate paths:

- `StateProxy.on_initialize()` subscribes to state and WebSocket bus events, waits for `websocket_service.wait_initial_connection()`, then calls `load_cache()` and marks ready even if sync fails (`src/hassette/core/state_proxy.py:63-91`).
- `StateProxy.on_reconnect()` ignores events until `_initialized` is true, then serializes via `_reconnect_lock`, calls `load_cache()`, re-subscribes, and toggles readiness based on success (`state_proxy.py:319-354`).
- `load_cache()` itself is just the HA REST read + cache replacement (`state_proxy.py:356-367`). Polling also calls this same low-level method via `Scheduler.run_every(... mode="single")` (`state_proxy.py:115-124`).

App bootstrap is indirectly gated by `AppHandler.depends_on = [..., StateProxy, ...]` (`src/hassette/core/app_handler.py:41-47`). Since `StateProxy` only becomes ready after its initial wait/sync attempt, `AppHandler.after_initialize()` cannot bootstrap apps until that condition is met (`app_handler.py:102-111`). This is the PR #1483 safety property to preserve.

Runtime health currently reads WebSocket booleans rather than resource readiness: `ok` when connected, `degraded` when disconnected after at least one prior connection, and `starting` when never connected (`src/hassette/core/runtime_query_service.py:271-317`).

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|---|---:|---|---|
| WebSocket phase model | `src/hassette/types/enums.py`, `src/hassette/core/websocket_service.py`, tests | Medium | Current `CONNECTED` means “connected enough to send” before subscription completes (`websocket_service.py:411-417`); splitting phases changes subtle send/subscribe assumptions. |
| StateProxy sync model | `src/hassette/core/state_proxy.py`, tests | High | Startup, reconnect, polling, subscriptions, readiness, stale reads, and app bootstrap all converge here. |
| App bootstrap gating | `src/hassette/core/app_handler.py`, maybe no direct code if StateProxy readiness remains the gate | Medium | Must preserve “apps wait while first connection/sync is pending” without turning no-HA startup into fatal startup. |
| Bus event semantics | `src/hassette/types/enums.py`, `src/hassette/bus/bus.py`, `src/hassette/bus/sync.py`, event schemas/tests if metadata is added | Medium | Existing `on_websocket_connected/disconnected` APIs are simple no-payload events. Adding metadata without breaking app handlers needs care. `bus/sync.py` is generated. |
| Runtime/dashboard health | `src/hassette/core/runtime_query_service.py`, web schemas/mappers/tests | Low-Medium | Existing health semantics are clear and covered; richer phases can feed UI but should not rename existing `status` meanings casually. |
| Integration/system tests | `tests/integration/test_state_proxy.py`, `tests/integration/test_websocket_service.py`, `tests/integration/test_dashboard_without_ha.py`, `tests/system/test_startup_without_ha.py`, possible e2e tests | High | Race tests need deterministic gates, not sleeps. Core changes may require system/e2e CI confidence. |

### What already supports this

- There is already a validated WebSocket state transition mechanism (`WS_VALID_TRANSITIONS`, `set_connection_state`) in `websocket_service.py:48-58` and `161-203`. That makes a richer enum feasible without inventing the pattern from scratch.
- The project already separates lifecycle readiness from connection health. `WebsocketService.on_initialize()` marks ready regardless of HA reachability, and health uses `is_connected`/`has_ever_connected` rather than `is_ready()`.
- StateProxy already has serialization primitives: `FairAsyncRLock` for cache writes, `_reconnect_lock` for reconnects, and scheduler `mode="single"` for poll non-overlap.
- Tests already encode the important invariants: no-HA startup (`tests/integration/test_dashboard_without_ha.py`, `tests/system/test_startup_without_ha.py`), initial app gating (`test_dashboard_without_ha.py:148-238`), reconnect serialization (`test_state_proxy.py:664-713`), stale reads while disconnected (`test_state_proxy.py:254-267`), and event idempotency (`test_websocket_service.py:780-835`).

### What works against this

- `ConnectionState.CONNECTED` currently covers multiple moments: authenticated, allowed to send, connection-established event emitted, HA event subscription done, `_connected_event` set, readiness event emitted (`websocket_service.py:400-423`). Issue 1484 wants those distinctions explicit.
- StateProxy has phase information encoded indirectly: resource readiness, `_initialized`, `state_change_sub is None`, cache emptiness, and readiness reason strings. These are hard to test as a coherent state machine.
- The bus connection events are currently binary and payloadless (`send_connection_established_event()` / `send_connection_lost_event()` send `HassetteSimpleEvent` only). Consumers cannot distinguish initial connect from reconnect except by local flags.
- `bus/sync.py` is generated, so any public bus API change likely requires changing the generator or regenerating the facade, not hand-editing only the generated file.

## Options Evaluated

### Option A: Explicit phase enums + a StateProxy sync coordinator (preferred)

**How it works**

Introduce two explicit lifecycle concepts:

- `WebSocketPhase` or expanded `ConnectionState`, with phases such as `DISCONNECTED_NEVER_CONNECTED` or `DISCONNECTED`, `CONNECTING`, `AUTHENTICATED`, `SUBSCRIBING`, `CONNECTED_SUBSCRIBED`, `RECONNECTING`, `SHUTTING_DOWN`. A lighter version can keep `ConnectionState` for compatibility and add computed properties/metadata: `is_connected`, `is_subscribed`, `connection_generation`, `initial_attempt_complete`, `has_ever_connected`.
- `StateSyncPhase`, e.g. `NOT_STARTED`, `WAITING_FOR_INITIAL_CONNECTION`, `SYNCING_INITIAL`, `DEGRADED_EMPTY`, `FRESH`, `STALE_DISCONNECTED`, `RESYNCING`, `FAILED_RESYNC`, `SHUTTING_DOWN`.

StateProxy would own a single serialized method, for example `sync(reason: SyncReason, connection_generation: int | None = None)`, used by startup, reconnect, and polling. That method would dedupe or serialize overlapping requests, set `sync_phase`, call `load_cache()` internally, manage state-change subscriptions, and then mark resource readiness consistently. `on_initialize()` becomes “subscribe to lifecycle signals, wait for initial connection attempt result, call `sync(INITIAL)`”; `on_reconnect()` becomes “enqueue `sync(RECONNECT, generation=...)`”. Polling becomes either `sync(POLL)` or a very thin low-level cache refresh that uses the same lock/dedupe policy.

Bus events should either carry metadata or be replaced/augmented with a richer internal event. Minimum useful metadata: `generation`, `phase`, `initial: bool`, `previously_connected: bool`, and maybe `subscribed: bool`. Existing `on_websocket_connected` can remain compatible by still firing when the connection is usable/subscribed; framework listeners can inspect payload only if they opt in.

**Pros**

- Directly addresses the acceptance criterion that `_initialized` disappears: startup-vs-reconnect becomes a `SyncReason`/phase decision instead of a boolean guard.
- Preserves the current resource model: `AppHandler` can still depend on StateProxy readiness, while StateProxy readiness becomes backed by explicit sync phases.
- Gives RuntimeQueryService a cleaner data source for health and future dashboard copy without changing today’s `starting/degraded/ok` contract.
- Fits existing code conventions: enums in `types/enums.py`, transition validation in the service, deterministic async locks, and readiness events.

**Cons**

- This is a real refactor, not a naming patch. The hardest part is defining exact phase boundaries around WebSocket auth/subscription and StateProxy subscription/cache freshness.
- Metadata-rich bus events may ripple into public API/docs/tests if exposed to app authors.
- There is a risk of overfitting to current bugs if the state model is too granular.

**Effort estimate**: Large. The direct code footprint is moderate, but the race tests and semantic audit are substantial.

**Dependencies**: No new runtime dependency appears necessary. Existing `asyncio`, `fair-async-rlock`, and `tenacity` cover the needed primitives (`pyproject.toml:36-66`).

### Option B: Minimal explicit StateProxy state machine, keep WebSocket API mostly as-is

**How it works**

Keep the current `ConnectionState` enum, `_connected_event`, `_first_connection_attempt_done_event`, and bus topics. Add only `StateSyncPhase` and a single StateProxy sync coordinator. Replace `_initialized` with `sync_phase` checks and maybe a `startup_sync_done` event. WebSocket gets only small computed properties like `initial_connection_attempt_done` and perhaps `connection_generation`.

**Pros**

- Smaller blast radius. Most risk is in `state_proxy.py`, where the architectural smell is most visible.
- Likely enough to remove the `_initialized` guard and dedupe startup/reconnect/poll sync paths.
- Avoids public bus API churn unless metadata proves necessary.

**Cons**

- Leaves `ConnectionState.CONNECTED` overloaded and may not satisfy “first-connect, subscribed, disconnected, reconnect phases represented explicitly” unless tests define those with side booleans.
- Future consumers may still infer WebSocket semantics from event timing.
- Runtime/dashboard health remains split between booleans rather than a coherent connection phase.

**Effort estimate**: Medium-Large.

**Dependencies**: None.

## Concerns

### Technical risks

- **WebSocket `CONNECTED` send gate**: `start_recv_and_subscribe()` sets `CONNECTED` before subscribing because `send_json()` gates on `is_connected` (`websocket_service.py:411-415`, `675-683`). If phases are split, `send_json()` may need to allow `AUTHENTICATED`/`SUBSCRIBING` for internal subscription sends while app/API sends require `CONNECTED_SUBSCRIBED`.
- **Initial no-HA behavior**: StateProxy must still mark ready with an empty cache after the first connection opportunity fails or times out, so WebApiService and apps can start (`state_proxy.py:79-90`, tests in `test_dashboard_without_ha.py` and `test_startup_without_ha.py`).
- **Stale reads**: When disconnected with a populated cache, `get_state`/domain reads intentionally return stale data while `is_ready()` is false (`state_proxy.py:174-182`, tests `test_state_proxy.py:254-291`). A new phase model must not turn all not-fresh reads into errors.
- **Polling overlap**: Poll jobs currently rely on scheduler `mode="single"` to prevent concurrent `load_cache()` (`state_proxy.py:115-124`, `test_state_proxy.py:1028-1128`). If polling moves through a central sync coordinator, preserve or replace that non-overlap guarantee.

### Complexity risks

- Too many phases could obscure rather than clarify. The phases should map to externally meaningful behavior: can send? subscribed to HA events? initial attempt done? cache empty/stale/fresh? apps allowed to bootstrap?
- Adding metadata to public bus events makes simple app handlers harder to document unless compatibility is preserved.

### Maintenance risks

- Every future WebSocket or StateProxy change will need state-transition tests. This is good, but it raises the maintenance bar.
- Generated sync facade drift is easy to miss if bus convenience APIs change; update generator/regeneration workflow rather than hand-editing `src/hassette/bus/sync.py` alone.

## Test Strategy

Recommended coverage should be layered:

1. **Unit/integration phase transition tests**
   - Valid/invalid WebSocket phase transitions, strict lifecycle behavior, and phase-derived booleans.
   - Initial connection success path: auth → subscribe → connected/subscribed event → generation increments.
   - First connection failure: initial attempt complete, never-connected health remains `starting`, no disconnected event emitted.
   - Reconnect after prior success: disconnected event emitted once, stale cache retained, reconnect sync requested once.

2. **StateProxy sync coordinator tests**
   - Initial sync waits while WebSocket initial attempt is pending and app bootstrap remains blocked.
   - Initial connect event during startup does not cause a duplicate sync, without `_initialized`.
   - Concurrent reconnect events dedupe or serialize through one path.
   - Poll sync cannot overlap with reconnect sync in a way that corrupts freshness/readiness.
   - Failed reconnect cache load still keeps/re-establishes state event subscription if that is still intended (#992 behavior).

3. **End-to-end startup tests**
   - Keep `tests/integration/test_dashboard_without_ha.py` and `tests/system/test_startup_without_ha.py` semantics: web serves, apps bootstrap, health says `starting`, `websocket_connected` is false, `has_ever_connected` false.
   - Keep the app-state reader regression: app cannot initialize against an empty cold cache while first WebSocket connection/state sync is still pending.

4. **Runtime/dashboard tests**
   - `RuntimeQueryService.get_system_status()` still maps phases to `starting`, `degraded`, and `ok` exactly as today unless intentionally redesigned.
   - If richer phase fields are exposed, add schema/mapper tests without breaking existing API fields.

Use deterministic `asyncio.Event` gates like the existing tests do; avoid sleep-based race assertions.

## Existing Semantics to Preserve

- WebsocketService lifecycle readiness does **not** mean HA is connected; it means the service is running and attempting connection.
- No DISCONNECTED bus event before the first successful connection (`send_connection_lost_event()` is gated on `has_ever_connected`).
- Health status mapping: `starting` before first connection, `degraded` after a lost prior connection, `ok` when connected.
- AppHandler should bootstrap only after StateProxy has finished the initial sync opportunity: either fresh cache from HA or degraded-empty after the first connection attempt fails/times out.
- StateProxy retains cache on disconnect and allows stale reads when cache is populated.
- Reconnect resync is serialized; rapid reconnect events must not leak duplicate subscriptions.
- State events are still processed after failed reconnect cache loads if event subscription succeeds.
- Polling remains optional via `disable_state_proxy_polling` and must not run overlapping cache loads.

## Open Questions

- Should WebSocket “connected” mean authenticated socket, HA event subscription confirmed, or app/API-safe connection? Current code uses `CONNECTED` as an internal send gate before subscription and as external health after subscription.
- Should `on_websocket_connected` remain a simple public app-author event, with richer metadata only on an internal topic, or should its payload become richer while preserving handler compatibility?
- Should StateProxy polling be allowed while disconnected, as today’s comment suggests (“self-heal between disconnect and next reconnect”), or should it be explicitly a `POLL_WHILE_STALE` sync phase with separate readiness semantics?
- If initial HA connection succeeds but initial `load_cache()` fails, should apps bootstrap against degraded-empty immediately (current behavior) or should there be a retry window now that HA is known reachable?
- Should RuntimeQueryService expose detailed phases to the UI, or only keep using them internally to compute the existing health summary?

## Recommendation

Proceed with Option A, but keep the public surface conservative. The evidence points strongly to an explicit StateProxy sync coordinator as the central architectural improvement: the current race-prone behavior is concentrated in the split between `on_initialize()`, `on_reconnect()`, `load_cache()`, `_initialized`, and polling. WebSocket phases should also be made more explicit, but avoid turning every internal socket step into public API.

Suggested shape:

1. Add `WebSocketPhase`/expanded `ConnectionState` plus `connection_generation` and computed booleans. Preserve `is_connected` as “HA event subscription is established and the connection is externally usable.” Add a private/internal predicate for “can send subscription/control messages” if needed.
2. Add `StateSyncPhase` and `SyncReason` enums. Replace `_initialized` and `_reconnect_lock` with one `sync(reason, generation=None)` coordinator using a lock plus dedupe policy.
3. Keep `AppHandler` dependency on `StateProxy`; make StateProxy readiness mean “app bootstrap may proceed,” not necessarily “fresh HA state exists.” Use `sync_phase` to explain whether that readiness is fresh or degraded.
4. Keep existing bus topics compatible. If metadata is needed, add a typed payload that existing no-argument handlers can ignore, or add internal-only topics for framework consumers.
5. Preserve current health response fields and meanings first; expose richer phase details only after the core lifecycle is stable.

### Suggested next steps

1. Write a design doc that defines exact phase names, transition tables, and invariants before implementation.
2. Add failing tests around `_initialized` replacement and duplicate startup/reconnect sync before changing code.
3. Implement StateProxy sync coordinator first, then refine WebSocket phases; this lowers risk by addressing the worst race while keeping health behavior stable.
4. Run affected integration tests locally; rely on CI for heavy system/e2e unless actively debugging core startup behavior.

## Sources

- GitHub issue 1484 via `gh issue view 1484 --json title,body,comments,labels,assignees,milestone`.
- Commit history via `git log --all --oneline --decorate -30 --grep='1483\|state sync\|websocket\|StateProxy\|without HA'`.
- Code references listed inline from `src/hassette/core/websocket_service.py`, `src/hassette/core/state_proxy.py`, `src/hassette/core/app_handler.py`, `src/hassette/core/runtime_query_service.py`, `src/hassette/types/enums.py`, `src/hassette/bus/bus.py`, and related tests.
