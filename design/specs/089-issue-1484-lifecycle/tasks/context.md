# Context: App Bootstrap and Home Assistant State Lifecycle

## Problem & Motivation
Hassette currently spreads the answer to "may apps start?" across AppHandler dependencies, StateProxy readiness, WebSocket flags, startup guards, reconnect locks, and event timing. That ambiguity caused cold-read races, duplicate synchronization, and startup behavior that is hard to reason about or test. This design narrows ownership: WebsocketService reports transport capability, StateProxy reports state capability, and a new AppBootstrapCoordinator owns the one-time app-bootstrap release decision. The web dashboard and other lifecycle-independent framework services must stay available while Home Assistant is unavailable and apps remain blocked.

## Visual Artifacts
None.

## Key Decisions
1. Add a concrete `AppBootstrapCoordinator` resource that becomes lifecycle-ready once wired, but exposes a separate process-latched `wait_released()` capability that alone means apps may initialize.
2. Treat WebSocket `CONNECTED` as external readiness only: auth succeeded, recv loop is running, and the Home Assistant event subscription is confirmed.
3. Replace StateProxy's `_initialized`, `_reconnect_lock`, and listener churn with one synchronization coordinator, one resource-lifetime state-change listener, generation fencing, and a journaled snapshot commit barrier.
4. Keep StateProxy lifecycle readiness non-blocking so later framework services can start without Home Assistant; initial state capability becomes a separate wait.
5. Move all app-creation enforcement to the shared `AppLifecycleService.start_app()` boundary with explicit admission modes so bootstrap, manual start/reload, and file/config reconciliation all obey one guard.
6. Remove `RuntimeQueryService`'s lifecycle dependency on `AppHandler` so the dashboard can query registry metadata before apps bootstrap, while remaining tolerant of concurrent AppHandler shutdown.
7. Preserve stale reads after post-bootstrap disconnect, existing public WebSocket listener APIs, current health meanings (`starting` / `degraded` / `ok`), and existing fatal invalid-auth supervision behavior.

## Constraints & Anti-Patterns
- Do not use `StateProxy.is_ready()` as the global app-bootstrap decision.
- Do not allow degraded app bootstrap before a successful initial state capability.
- Do not make dashboard startup depend on Home Assistant connectivity or app-bootstrap release.
- Do not introduce a generic gate registry, per-app capability model, or broader lifecycle taxonomy in this change.
- Do not use bus signals as the correctness boundary between WebsocketService, StateProxy, and bootstrap coordination.
- Do not treat auth-only or send-only socket state as external WebSocket readiness.
- Do not rely on sleeps in race tests; use deterministic `asyncio.Event`/gates.
- Do not change public `on_websocket_connected` / `on_websocket_disconnected` handler signatures.
- Non-goals remain out of scope: per-app capability declarations, continuous runtime suspension on capability loss, dashboard phase chrome, event-loop isolation, and generic orchestration infrastructure.

## Design Doc References
- `## Problem` — why startup policy and state readiness are currently ambiguous.
- `## Goals` — the lifecycle, readiness, and dashboard outcomes this implementation must preserve.
- `## Non-Goals` — explicit exclusions that tasks must not implement.
- `## Functional Requirements` — the FR#1–FR#34 traceability source.
- `## Acceptance Criteria` — the AC#1–AC#26 verification source.
- `## Key Constraints` — hard design boundaries and testing constraints.
- `## Architecture -> AppBootstrapCoordinator Resource` — coordinator ownership, release latch semantics, and app admission policy.
- `## Architecture -> WebSocket Capability and Generation` — external readiness ordering, private send capability, and generation fencing.
- `## Architecture -> State Capability Model` — separation of synchronization status, freshness, cache presence, and maintained generation.
- `## Architecture -> State Synchronization Coordinator` — coalescing/skip policy for initial, reconnect, and poll requests.
- `## Architecture -> Snapshot and Event Ordering` — synchronization-local journal, tombstones, and fenced commit behavior.
- `## Architecture -> Failure Semantics` — blocked bootstrap, stale cache behavior, and bounded retry requirements.
- `## Architecture -> Health Semantics` — required `starting` / `degraded` / `ok` mapping.
- `## Replacement Targets` — implementation details that must be removed in the same wave.
- `## Test Strategy` — exact tests to adapt, new coverage to add, and assertions to remove.
- `## Documentation Updates` — required `CLAUDE.md` updates and no-docs-site stance.
- `## Impact` — changed files, invariants, and blast radius.

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
