# Context: Dashboard Without HA

## Problem & Motivation

The hassette web dashboard is unusable when Home Assistant is offline. WebsocketService failure triggers a fatal error that tears down the entire process before the web server starts. The dependency chain `WebsocketService → ApiResource → StateProxy → RuntimeQueryService → WebApiService` blocks wave-based startup — and WebsocketService itself is a node in the wave graph, so if it doesn't call `mark_ready()` within the 30s startup timeout, `run_forever()` records a fatal reason and shuts down. The fix decouples service lifecycle readiness from HA connection status so the dashboard serves regardless of HA availability.

## Visual Artifacts

None.

## Key Decisions

1. **Always-resilient, no config flag** — the dependency decoupling makes the dashboard work without HA as a natural property, not an opt-in mode. No `require_ha_connection` flag or CLI `--dashboard-only` parameter.
2. **Lifecycle readiness ≠ HA connected** — WebsocketService calls `mark_ready()` unconditionally in `on_initialize()`, separating "service is running and will attempt connections" from "HA WebSocket handshake succeeded." Connection state is tracked via `is_connected` and `has_ever_connected`.
3. **Idempotency guard uses `has_ever_connected`** — `send_connection_lost_event()` gates on `has_ever_connected` instead of `is_ready()` to prevent spurious disconnect events before the first successful connection.
4. **StateProxy starts with empty cache** — `load_cache()` failure in `on_initialize()` is caught and logged as a warning. StateProxy marks ready with an empty dict. `get_state()` returns None (not raises) because `_check_ready()` passes when `is_ready()` is True.
5. **Existing reconnect/disconnect paths unchanged** — `on_reconnect` and `on_disconnect` in StateProxy are not modified. Only `on_initialize` changes to make the initial cache load non-fatal.

## Constraints & Anti-Patterns

- Do NOT add new database tables or migrations.
- Do NOT modify frontend code — the dashboard already handles the "starting" system status and apps with zero telemetry.
- Do NOT change the `on_reconnect` / `on_disconnect` behavior in StateProxy.
- Do NOT add a config flag or CLI parameter for "dashboard-only mode."
- The `has_ever_connected` property at `websocket_service.py:144` never reverts once True — do not introduce any path that resets it.
- Do NOT modify the `_check_ready()` logic in StateProxy — it already returns None when `is_ready()` is True and cache is empty.

## Design Doc References

- `## Architecture → Dependency Decoupling` — the five file changes and their rationale
- `## Architecture → System Status Fix` — RQS `is_ready()` → `is_connected` switch
- `## Edge Cases` — HA never comes back, reconnect after extended offline, spurious disconnect, app init failures
- `## Convention Examples` — depends_on pattern, StateProxy reconnect handler, idempotency guard pattern
- `## Test Strategy` — existing tests to adapt and new coverage needed

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

### Idempotency guard pattern

**Source:** `src/hassette/core/websocket_service.py` (lines 735-739)

```python
async def send_connection_lost_event(self) -> None:
    if not self.is_ready():
        return
    # ... fire disconnected event
```
