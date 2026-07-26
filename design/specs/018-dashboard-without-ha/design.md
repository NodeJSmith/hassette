# Design: Dashboard Without HA

**Date:** 2026-07-26
**Status:** archived
**Scope-mode:** hold

## Problem

The hassette web dashboard is unusable when Home Assistant is offline. WebsocketService failure triggers a fatal error that tears down the entire process before the web server starts, because the dependency chain `WebsocketService → ApiResource → StateProxy → RuntimeQueryService → WebApiService` blocks wave-based startup. Additionally, WebsocketService itself is a node in the wave graph — if it doesn't call `mark_ready()` within the startup timeout, `run_forever()` records a fatal reason and shuts down before any later wave starts.

## Goals

- The web dashboard starts and serves regardless of whether Home Assistant is reachable.
- Apps start, register listeners/jobs, and appear in the dashboard even when HA is offline — they just don't receive events until HA connects.
- The existing reconnect/disconnect behavior continues to work for HA restarts and network flaps.

## Non-Goals

- Moving the app-list spine from in-memory manifests to the database — separate design for #1436.
- Persisting app manifest metadata or instance lifecycle state to the DB — follow-ups #1445, #1446.
- New UI chrome for degraded mode (banners, toasts). Existing `system_status.status` already returns "starting"/"degraded"/"ok".
- Logs from DB with WS notification channel — tracked in #1373.

## User Scenarios

### Developer/Operator: Homelab admin

- **Goal:** Check dashboard health when HA is down or unreachable
- **Context:** HA is offline (maintenance, crash, network issue), but hassette is running

#### Dashboard with HA offline

1. **Starts hassette**
   - Sees: hassette boots normally, web server starts on configured port
   - Then: WebsocketService enters retry loop in background; dashboard serves immediately

2. **Opens dashboard**
   - Sees: App grid with all configured apps showing as "running" (apps started, listeners/jobs registered). Telemetry data from DB (historical invocations, errors, durations). System status shows "starting" (WS never connected).
   - Decides: Whether to investigate further or wait for HA to come back

3. **HA comes back online**
   - Sees: System status transitions to "ok", state cache populates, listeners start receiving events
   - Then: Dashboard fully functional with live telemetry

## Functional Requirements

- **FR#1** WebApiService starts and serves HTTP responses when WebsocketService has not connected to HA.
- **FR#2** StateProxy starts with an empty state cache when HA is unreachable and populates the cache when HA becomes available via the existing `on_reconnect` handler.
- **FR#3** ApiResource starts without waiting for WebsocketService to connect. REST API calls fail naturally with connection errors when HA is down.
- **FR#4** WebsocketService reports itself as lifecycle-ready immediately, independent of whether HA is reachable. Connection state is tracked separately from service readiness.
- **FR#5** AppHandler starts and bootstraps apps without waiting for a live HA connection. Apps register listeners and jobs even when HA is offline.
- **FR#6** The system status endpoint reports connection state accurately: "starting" when WS has never connected, "degraded" when previously connected but currently disconnected, "ok" when connected.
- **FR#7** Apps that read entity state during `on_initialize()` receive `None` (not `ResourceNotReadyError`) when the state cache is empty.

## Edge Cases

- **HA never comes back**: State cache stays empty. Apps are running with registered listeners/jobs, but no HA events arrive — listeners never fire, execution counts stay at 0. Historical telemetry from the DB still renders.
- **HA comes back after extended offline**: The existing `on_reconnect` handler fires, `load_cache()` populates the state cache, `subscribe_to_events()` re-wires event subscriptions, StateProxy marks ready. Listeners start receiving events normally.
- **Spurious disconnect event before first connection**: WebsocketService's `send_connection_lost_event()` must not fire when no connection has ever been established — otherwise StateProxy's `on_disconnect()` would un-ready itself and break FR#7.
- **Apps fail during on_initialize() when HA is offline**: Some apps may call HA APIs (e.g., `call_service()`) during init. These calls fail with connection errors and the app transitions to failed status, which is correct behavior — the AppHandler records the failure and the dashboard shows the app as failed.

## Acceptance Criteria

- **AC#1** `uv run pytest tests/` passes — no regressions. (FR#1-#7)
- **AC#2** `prek -a` passes — lint and type checks clean. (all FRs)
- **AC#3** A test starts hassette with WebsocketService mocked to never connect, and verifies WebApiService is ready and serves HTTP 200 on `/api/health`. (FR#1, FR#3)
- **AC#4** A test verifies StateProxy marks ready with an empty cache when `load_cache()` fails, and `get_state()` returns `None` (not raises). (FR#2, FR#7)
- **AC#5** A test verifies `send_connection_lost_event()` does not fire when `has_ever_connected` is False. (FR#4, edge case #3)
- **AC#6** The `/api/health` response shows `status: "starting"` when WS has never connected. (FR#6)

## Key Constraints

- Do not change the existing `on_reconnect` / `on_disconnect` behavior in StateProxy — it already handles the recovery path correctly. The only change is making `on_initialize` non-fatal on cache load failure.
- Do not add a config flag or CLI parameter for "dashboard-only mode" — the decoupling makes this always-on.
- The `send_connection_lost_event()` idempotency guard must be updated to use `has_ever_connected` instead of `is_ready()` — see Architecture section.

## Dependencies and Assumptions

- No new database tables or migrations required for this PR.
- No frontend changes required — the dashboard already handles the "starting" system status and apps with zero telemetry activity.
- The existing `on_reconnect` handler is the recovery path when HA becomes available. No new recovery mechanism is needed.

## Architecture

### Dependency Decoupling (FR#1-#5)

Five changes decouple the dashboard from HA availability:

1. **`WebsocketService`** (`src/hassette/core/websocket_service.py`): Add an `on_initialize()` override that calls `mark_ready()` unconditionally before `serve()` starts the connection loop. This separates "service lifecycle ready" (the service is running and will attempt connections) from "HA connected" (the WebSocket handshake succeeded). Without this, WebsocketService's wave in `run_forever()` times out when HA is unreachable, triggering `record_fatal_reason()` and tearing down the process before WebApiService's wave starts — the depends_on changes alone don't help because WS is still a node in the wave graph.

   **Idempotency guard fix**: `send_connection_lost_event()` (`websocket_service.py:735`) currently gates on `is_ready()`, which was safe when `mark_ready()` only fired post-handshake. With unconditional `mark_ready()`, the first failed connection attempt would fire a spurious "disconnected" event, causing `StateProxy.on_disconnect()` to un-ready itself and break the "returns None" contract. Fix: gate `send_connection_lost_event()` on `has_ever_connected` instead of `is_ready()` — the property already exists (line 144) and never reverts.

2. **`ApiResource`** (`src/hassette/core/api_resource.py`): Remove `WebsocketService` from `depends_on`. `on_initialize()` just creates an `aiohttp.ClientSession` — no actual HA request. REST calls fail with connection errors when HA is down; callers already handle this via tenacity retries and error responses.

3. **`StateProxy`** (`src/hassette/core/state_proxy.py`): Remove `WebsocketService` from `depends_on`. Keep `ApiResource` (StateProxy needs the HTTP session for `load_cache()`).

4. **`StateProxy.on_initialize()`**: Catch `load_cache()` failure instead of raising. Log a warning, start with empty state cache, and call `mark_ready()`. Note: `on_initialize()` already calls `subscribe_to_events()` unconditionally before `load_cache()` (line 71), so event subscriptions are wired regardless of cache success. The `on_reconnect` handler (lines 303-334) handles the recovery when HA becomes available: `load_cache()` → `subscribe_to_events()` → `mark_ready()`.

5. **`AppHandler`** (`src/hassette/core/app_handler.py`): Remove `WebsocketService` from `depends_on` (line 43). `AppHandler.on_initialize()` and `after_initialize()` don't read WS state or methods — they wire file-watcher subscriptions and bootstrap apps. With WS unconditionally ready, this edge is redundant.

The wave-based startup then proceeds: WebsocketService ready (connecting in background) → ApiResource ready (session created) → StateProxy ready (empty cache) → AppHandler ready (apps bootstrapped) → RuntimeQueryService ready → WebApiService ready → dashboard serves.

### System Status Fix (FR#6)

`RuntimeQueryService.get_system_status()` (`src/hassette/core/runtime_query_service.py:258`) currently uses `ws.is_ready()` as a proxy for "HA connected." With unconditional `mark_ready()`, this is always True. Switch to `ws.is_connected` (the existing `ConnectionState.CONNECTED` property at `websocket_service.py:213`). The existing `has_ever_connected` check (lines 282-287) continues to distinguish "starting" from "degraded."

## Implementation Preferences

No specific implementation preferences — follow codebase conventions.

## Replacement Targets

No existing code is being replaced. The `depends_on` lists are being modified, and one idempotency guard is being updated — but no methods, endpoints, or abstractions are removed.

## Convention Examples

### Wave-based startup with depends_on

**Source:** `src/hassette/core/web_api_service.py` (lines 28-33)

```python
class WebApiService(Service):
    depends_on: ClassVar[list[type[Resource]]] = [RuntimeQueryService, TelemetryQueryService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=60,
    )
```

The `depends_on` declarations are the mechanism being modified. New depends_on lists must maintain a valid DAG.

### StateProxy reconnect handler

**Source:** `src/hassette/core/state_proxy.py` (lines 303-334)

```python
async def on_reconnect(self) -> None:
    async with self._reconnect_lock:
        load_cache_succeeded = False
        try:
            await self.load_cache()
            load_cache_succeeded = True
        except Exception as exc:
            self.logger.exception("Failed to resync states after HA restart: %s", exc)
        # ... subscribe_to_events, mark_ready/mark_not_ready based on results
```

The `on_initialize()` change mirrors this pattern — catch `load_cache()` failure and mark ready with empty cache instead of raising.

### Idempotency guard pattern

**Source:** `src/hassette/core/websocket_service.py` (lines 735-739)

```python
async def send_connection_lost_event(self) -> None:
    if not self.is_ready():
        return
    # ... fire disconnected event
```

This guard will change from `is_ready()` to `has_ever_connected` to prevent spurious events before the first successful connection.

## Alternatives Considered

**Config flag for dashboard-only mode**: Initially proposed a `require_ha_connection` flag on `LifecycleConfig` with a CLI `--dashboard-only` parameter. Rejected — always-resilient is simpler (no flag to discover, no conditional code paths) and more robust. The dependency decoupling makes the dashboard work without HA as a natural property, not an opt-in mode.

**Bundling with DB-as-spine for app list (#1436)**: Originally designed as one PR with DB tables for manifest persistence. Challenge review showed the HA-offline goal is fully satisfied by the dependency decoupling alone — `AppRegistry.get_full_snapshot()` already works with in-memory manifests once the wave startup doesn't block. The DB-spine work has its own design challenges (session-scoped queries vs. historical data, hot-reload gaps) that are better addressed in a focused follow-up.

## Test Strategy

### Existing Tests to Adapt

- `tests/integration/test_core.py` — startup tests that assert wave ordering. May need updating if dependency graph changes affect wave composition.
- `tests/integration/test_fatal_shutdown.py` — tests generic fatal-shutdown mechanics. Should still pass — they don't test WS-specific failure paths.
- `tests/integration/test_websocket_service.py` — `test_connect_ws_wraps_connection_refused` tests error wrapping. Should still pass; WS retry behavior is unchanged.
- `src/hassette/core/runtime_query_service.py` — `get_system_status()` uses `ws.is_ready()` for connection status. Must switch to `ws.is_connected`.
- `tests/unit/core/test_runtime_query_service.py` — `TestSystemStatus` tests set `is_ready.return_value` to drive system status logic. Must switch to `is_connected`.
- `tests/integration/web_api/test_endpoints.py` — health endpoint tests use `create_hassette_stub()` which sets `is_ready.return_value`. The stub (`src/hassette/test_utils/web_mocks.py`) must also set `is_connected`.
- `tests/integration/test_state_proxy.py` — `test_raises_on_api_failure_during_init` asserts `on_initialize()` raises on API failure. Must update to verify non-fatal behavior.

### New Test Coverage

- **FR#1, FR#4, FR#5**: Integration test — start hassette with WS mocked to never connect, assert WebApiService reaches ready state, apps bootstrap, and `/api/health` serves HTTP 200. (AC#3)
- **FR#2, FR#7**: Unit test — StateProxy.on_initialize() with load_cache() raising, assert it marks ready with empty cache and get_state() returns None. (AC#4)
- **FR#4**: Unit test — send_connection_lost_event() does not fire when has_ever_connected is False. (AC#5)
- **FR#6**: Integration test — /api/health returns status "starting" when WS has never connected. (AC#6)

### Tests to Remove

No tests to remove.

## Documentation Updates

- `CLAUDE.md` Architecture section — update the Resource Hierarchy description to note that StateProxy and ApiResource no longer depend on WebsocketService, and that WebsocketService marks ready unconditionally (lifecycle readiness ≠ HA connected).

## Impact

### Changed Files

<!-- Gap check 2026-07-26: 2 gaps included — test_raises_on_api_failure_during_init (tests/integration/test_state_proxy.py:98) → T02 Focus item 5, test_send_connection_lost_event_idempotent (tests/integration/test_websocket_service.py:776) → T01 Focus item 3 -->

- **modify** `src/hassette/core/websocket_service.py` — add on_initialize() that calls mark_ready() unconditionally; gate send_connection_lost_event() on has_ever_connected
- **modify** `src/hassette/core/api_resource.py` — remove WebsocketService from depends_on
- **modify** `src/hassette/core/state_proxy.py` — remove WebsocketService from depends_on, make load_cache() failure non-fatal in on_initialize()
- **modify** `src/hassette/core/app_handler.py` — remove WebsocketService from depends_on
- **modify** `src/hassette/core/runtime_query_service.py` — get_system_status() switches from ws.is_ready() to ws.is_connected

### Behavioral Invariants

- Existing startup behavior when HA IS available must not change — apps still start, listeners register, telemetry records.
- The `/api/health` endpoint contract is unchanged (status field values are the same).
- The `on_reconnect` / `on_disconnect` behavior in StateProxy is unchanged — only the idempotency guard input changes.
- CLI commands continue to work (they hit the REST API).
- WebsocketService retry/reconnection behavior is unchanged — only when `mark_ready()` fires is different.

### Blast Radius

- **StateProxy consumers**: Any code that reads `state_proxy.states` may see an empty dict during startup when HA is offline. `RuntimeQueryService.get_system_status()` already handles this. Other consumers (BusService entity state reads) use `try_state_proxy()` which returns None.
- **Wave ordering**: The dependency graph changes may alter which services land in the same wave. Tests asserting specific wave composition may need updating.
- **Apps during HA offline**: Apps start and register listeners/jobs. Apps that call HA APIs during `on_initialize()` (e.g., `call_service()`, `get_state()`) will get None/connection errors, which may cause them to transition to failed status. This is correct degraded behavior.

## Open Questions

None — all questions resolved during discovery and challenge.
