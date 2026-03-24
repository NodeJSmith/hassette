# Tier 1 Correctness Wave — Design Doc

## Problem

Five data-correctness bugs erode trust in the Preact SPA's accuracy:

1. **#408 — Bus endpoint returns wrong model.** `/bus/listeners` declares `response_model=list[ListenerMetricsResponse]` but returns raw `ListenerSummary` objects. FastAPI silently coerces, dropping fields that exist on `ListenerSummary` but not on `ListenerMetricsResponse`. The `pyright: ignore[reportReturnType]` suppression masks the mismatch.

2. **#407 — `ListenerMetricsResponse.once` is `bool`, should be `int`.** The database stores `once` as an integer (0 or 1+). `ListenerSummary.once: int` and `ListenerWithSummary.once: int` both use `int`, but `ListenerMetricsResponse.once: bool` silently coerces, losing the count semantics.

3. **#367 — WS log subscribe never sent.** The frontend never calls `socket.send({"type":"subscribe","data":{"logs":true}})`. The server starts with `subscribe_logs: False` per client (ws.py:91), so all log messages are silently dropped. Real-time log streaming — the primary SPA justification — does not function.

4. **#364 — REST+WS log overlap produces duplicates.** `LogTable` concatenates `[...initialEntries, ...wsEntries]` without deduplication. Once #367 is fixed, logs that arrived via WS during the REST fetch window will appear twice. No unique ID exists on `LogEntry` to enable dedup.

5. **#237 — Service log levels ignore global log level.** Setting `HASSETTE__LOG_LEVEL=DEBUG` correctly resolves `HassetteConfig.log_level` to `"DEBUG"`, and the `log_level_default_factory` correctly computes `"DEBUG"` for all 12 service-specific fields. But `model_post_init` then overwrites 9 of them with hardcoded `"INFO"` values from the bundled TOML defaults (`hassette.prod.toml` / `hassette.dev.toml`). The 3 fields that survive (`database_service_log_level`, `command_executor_log_level`, `state_proxy_log_level`) are simply not listed in the TOML files.

## Architecture

### Fix 1: Bus endpoint model alignment (#408 + #407)

**Approach:** Retire `ListenerMetricsResponse` entirely. The telemetry route already uses `ListenerWithSummary` which is a superset. The bus route should convert `ListenerSummary` → `ListenerWithSummary` via a shared helper, making the API surface consistent.

**Changes:**
- `telemetry_helpers.py`: Extract a `to_listener_with_summary(ls: ListenerSummary) -> ListenerWithSummary` function from the 30-line mapping currently inline in `routes/telemetry.py:96-126`
- `routes/telemetry.py`: Call the extracted helper instead of inline mapping
- `routes/bus.py`: Change `response_model` to `list[ListenerWithSummary]`, convert via the shared helper. Add `session_id=safe_session_id(runtime)` to `gather_all_listeners` call to match telemetry route's session scoping
- `models.py`: Delete `ListenerMetricsResponse` class
- Remove the `pyright: ignore` suppressions in bus.py
- Update any frontend types that reference the old model name
- Regenerate `frontend/openapi.json` from the FastAPI app

This also fixes #407 since `ListenerWithSummary.once` is already `int`.

### Fix 2: WS log subscribe on connect (#367)

**Approach:** Subscribe inside `useWebSocket`'s connected handler, not from `LogTable`. This fires on every connect and reconnect, guarantees socket readiness, and requires no new API surface on AppState.

**Changes:**
- `hooks/use-websocket.ts`: After receiving the `"connected"` message (line ~59), send `{type: "subscribe", data: {logs: true, min_log_level: "INFO"}}`. Subscribe at INFO (the default filter level), not DEBUG — subscribing at DEBUG would flood the per-client queue (maxsize=256) and drop non-log messages like `app_status_changed`.
- When the user changes the level filter in LogTable, send an updated subscribe message with the new `min_log_level`. This requires exposing a targeted `updateLogSubscription(level)` method (not a general-purpose `send()`).
- `state/create-app-state.ts`: Add `updateLogSubscription` callback to AppState (set by `useWebSocket`, called by `LogTable`). Narrower than a generic `send()`.

### Fix 3: Log deduplication (#364)

**Approach:** Monotonic sequence counter. Add `seq: int` to `LogCaptureHandler.emit()` — a simple `self._seq += 1` on each call. Include `seq` in both REST and WS payloads. Use `seq` as the dedup watermark instead of timestamp.

Timestamp-based watermark was considered but rejected: strict `>` on `time.time()` floats drops legitimate entries that share a timestamp with the boundary (burst logging routinely produces same-millisecond entries from different loggers).

**Changes:**
- `logging_.py`: Add `self._seq = 0` to `LogCaptureHandler.__init__`, increment in `emit()`, include in `LogEntry`
- `LogEntry` model: Add `seq: int` field
- `frontend/ws-schema.json`: Add `seq` to `LogEntryResponse`
- Frontend types: Add `seq` to `LogEntry` / `WsLogPayload`
- `components/shared/log-table.tsx`: After REST fetch, store `watermark = max(initialEntries.seq)`. Filter wsEntries to `entry.seq > watermark` before concatenation.

**Additionally:** Clear the log ring buffer on WS reconnect. The `RingBuffer` persists across reconnections (app-level state), so after reconnect the REST refetch + stale buffer produces massive duplication. The `clear()` method exists on `RingBuffer` but is never called.

**Changes:**
- `state/create-app-state.ts`: Expose `clear()` on LogStore
- `hooks/use-websocket.ts`: Call `state.logs.clear()` on reconnect (inside the connected handler, before re-subscribing)

### Fix 4: Service log level defaults (#237)

**Root cause:** `model_post_init` (`config.py:425-435`) loads defaults from bundled TOML files (`hassette.prod.toml` / `hassette.dev.toml`) and overwrites any field not in `model_fields_set`. Fields populated by `default_factory` are NOT in `model_fields_set`, so they get overwritten. The TOML files hardcode `log_level = "INFO"` for 9 service-specific fields, clobbering the factory's correctly-computed value.

**Approach:** Remove all values from the TOML defaults that are identical between prod and dev. These are redundant with the `Field(default=...)` declarations and only serve to interfere with the factory resolution. Keep only the 18 values that actually differ between environments (timeouts, delays, `dev_mode`, `allow_startup_if_app_precheck_fails`).

**Changes:**
- `hassette.prod.toml`: Strip to 19 fields that differ from dev
- `hassette.dev.toml`: Strip to 19 fields that differ from prod
- No changes to `model_post_init`, `log_level_default_factory`, or `config.py`

**Fields to keep (all that differ between prod/dev):**

| Field | Prod | Dev |
|-------|------|-----|
| `dev_mode` | `false` | `true` |
| `allow_startup_if_app_precheck_fails` | `false` | `true` |
| `startup_timeout_seconds` | 10 | 20 |
| `app_startup_timeout_seconds` | 20 | 40 |
| `app_shutdown_timeout_seconds` | 10 | 20 |
| `resource_shutdown_timeout_seconds` | 10 | 20 |
| `task_cancellation_timeout_seconds` | 5 | 10 |
| `run_sync_timeout_seconds` | 6 | 12 |
| `websocket_authentication_timeout_seconds` | 10 | 20 |
| `websocket_response_timeout_seconds` | 5 | 10 |
| `websocket_connection_timeout_seconds` | 5 | 10 |
| `websocket_total_timeout_seconds` | 30 | 60 |
| `websocket_heartbeat_interval_seconds` | 30 | 60 |
| `scheduler_min_delay_seconds` | 1 | 2 |
| `scheduler_max_delay_seconds` | 30 | 60 |
| `scheduler_default_delay_seconds` | 15 | 30 |
| `file_watcher_debounce_milliseconds` | 3000 | 6000 |
| `file_watcher_step_milliseconds` | 500 | 1000 |
| `state_proxy_poll_interval_seconds` | 30 | 15 |

**AppConfig note:** `AppConfig` (`app_config.py:25`) uses the same `log_level_default_factory`. It is not affected by this bug (no bundled TOML defaults overwrite its fields). After this fix, `AppConfig.log_level` will correctly inherit from the global `log_level` via the factory's `data.get("log_level")` — which is the intended behavior.

## Alternatives Considered

1. **#408: Keep ListenerMetricsResponse, add conversion** — More code to maintain two nearly-identical models. Rejected: simpler to converge on `ListenerWithSummary`.

2. **#364: Timestamp watermark** — Strict `>` on `time.time()` floats drops legitimate entries that share a timestamp with the boundary. Burst logging routinely produces same-millisecond entries. Rejected: a monotonic seq counter is ~10 lines and eliminates the ambiguity.

3. **#364: Accept duplicates, do nothing** — Zero risk of data loss, zero work. Viable but the seq counter is cheap enough to be worth it.

4. **#367: Subscribe from LogTable on mount** — Creates a race (socket may not be ready), breaks on reconnect (LogTable doesn't remount but server resets `ws_state`), and threading `send()` through AppState creates an unbounded coupling surface. Rejected: subscribing in the hook's connected handler is simpler and handles all lifecycle states.

5. **#237: Add `get_log_level()` fallback in the factory** — The original design proposed this, but investigation revealed the factory already works correctly. The real culprit is `model_post_init` overwriting factory results with redundant TOML defaults. Adding `get_log_level()` would create a parallel env-var resolution path that bypasses Pydantic's settings chain. Rejected.

6. **#237: Fix only websocket_service** — The root cause affects all services with redundant TOML entries. Fixing only one is a partial fix.

## Risks

- **#408 schema change** is a breaking API change if any external consumer depends on `ListenerMetricsResponse`. Mitigated: this is an internal API, and `ListenerWithSummary` is a superset (all existing fields preserved, new ones added).
- **#364 seq counter** adds a field to LogEntry. Mitigated: additive, non-breaking. Old clients that don't know about `seq` ignore it.
- **#237 TOML cleanup** changes the defaults for fields that were previously overwritten by TOML. Mitigated: removing redundant values means Pydantic's own `Field(default=...)` takes effect, which was always the intended default. The `model_post_init` mechanism still works for the 18 fields that actually differ.

## Test Strategy

- **#408/#407:** Integration test via `create_hassette_stub()` — hit `/bus/listeners`, assert response matches `ListenerWithSummary` schema, assert `once` is `int`. Verify both routes return the same schema.
- **#367:** E2E test — connect WS, verify log messages arrive after connect without explicit subscribe from component. Verify logs resume after reconnect.
- **#364:** Unit test — verify `seq` increments monotonically. Frontend test — create LogTable with overlapping REST+WS entries, assert dedup by seq. Test that ring buffer clear on reconnect prevents stale duplicates.
- **#237:** Unit test — create `HassetteConfig` with `HASSETTE__LOG_LEVEL=DEBUG` env var and no service-specific overrides, assert ALL 12 service log level fields resolve to `"DEBUG"`. Verify `AppConfig.log_level` also inherits correctly.
