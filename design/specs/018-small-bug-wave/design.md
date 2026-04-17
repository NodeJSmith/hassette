# Design: Small Bug Wave (March 2026)

**Status:** Draft (Rev 4 — post-challenge R3)
**Issues:** #380, #349, #348, #340

## Problem

Four independent small bugs that degrade post-Preact-migration stability:

1. **#380 — Stale listeners and jobs in telemetry DB.** Listeners and scheduled jobs are INSERT-or-UPDATE'd on registration but never deleted. When an app removes a handler or job, the telemetry page still shows the stale row.

2. **#349 — Connection bar flashes "Disconnected" on refresh.** `connection` signal initializes as `"disconnected"` (create-app-state.ts:46). The StatusBar renders synchronously before the WebSocket `onopen` fires, producing a visible flash.

3. **#348 — Stop/start/reload gated behind dev_mode.** `_check_reload_allowed()` in apps.py:38-40 blocks all three endpoints unless `dev_mode` or `allow_reload_in_prod` is set. The file watcher (correctly gated in app_handler.py:75-81) is the only thing that should require dev_mode — manual user actions should always work.

4. **#340 — Flaky throttle test + test isolation.** `test_throttle_tracks_time_correctly` uses real `asyncio.sleep` with sub-100ms margins. Under CI load, the event loop scheduler timing is unreliable — the test was testing asyncio scheduling, not throttle logic.

**Note:** #338 (missing instance_index filter) is already fixed in the codebase — dropped from this batch.

## Architecture

### WP01: Stale registration cleanup at startup (#380)

**Approach:** Delete-before-insert at `start_app()` time. Before any listener or job registration tasks are spawned for an app, delete all existing rows for that `app_key` from both `listeners` and `scheduled_jobs`. The subsequent upsert registrations then re-insert everything fresh. The DELETE scopes to `app_key` only (not per-instance), matching `start_app()`'s granularity.

**Why startup-time, not teardown-time:**
Rev 2 proposed teardown-time deletion in `stop_app()`. Challenge R2 identified two problems:
1. `shutdown_all()` bypasses `stop_app()` — goes directly to `shutdown_instances()` (`app_lifecycle_service.py:217-224`). Crash/kill also never calls `stop_app()`. Stale rows from prior sessions would persist.
2. Startup-time deletion has no race condition because it executes before any registration tasks are spawned. The DELETE runs synchronously in the lifecycle, then `on_initialize()` spawns registration tasks that re-insert.

**FK constraint handling:** `handler_invocations.listener_id` (`001_initial_schema.py:76`) and `job_executions.job_id` (line 91) are `NOT NULL REFERENCES` with no `ON DELETE` clause, and `PRAGMA foreign_keys = ON` (`database_service.py:220`). A bare DELETE on the parent tables will fail for any row with invocation/execution history.

**Solution:** Add migration 003 that:
1. Makes `handler_invocations.listener_id` and `job_executions.job_id` nullable
2. Adds `ON DELETE SET NULL` to both FK constraints

Must use `batch_alter_table` (table rebuild) — SQLite cannot ALTER column constraints in-place. The project already uses this pattern in migration 002.

This allows stale parent rows to be deleted while preserving history. Orphaned history rows (with `listener_id = NULL` or `job_id = NULL`) remain queryable by `session_id` and retain all timing/error data.

**Telemetry query impact:** The summary queries use LEFT JOIN (`telemetry_query_service.py:99,148`) and handle NULLs correctly. However, `get_recent_errors` (`:397,414`) and `get_slow_handlers` (`:480`) use INNER JOIN — orphaned rows would vanish from these feeds. These JOINs must be changed to LEFT JOIN as part of this WP to preserve error/slow-handler visibility after cleanup.

**Scope includes scheduled_jobs:** The `scheduled_jobs` table (`command_executor.py:371-414`) uses the identical INSERT ON CONFLICT UPDATE pattern with no DELETE path — same bug, same fix.

**Changes:**

| File | Change |
|------|--------|
| `migrations/versions/003_nullable_fk_for_cleanup.py` | New migration using `batch_alter_table`: make `listener_id` and `job_id` nullable with `ON DELETE SET NULL` |
| `command_executor.py` | Add `clear_registrations(app_key)` method that DELETEs from both `listeners` and `scheduled_jobs` WHERE `app_key = ?` |
| `app_lifecycle_service.py` | Call `clear_registrations()` in `start_app()` before `initialize_instances()` |
| `telemetry_query_service.py` | Change INNER JOINs to LEFT JOIN in `get_recent_errors` (`:397,414`) and `get_slow_handlers` (`:480`) so orphaned history rows remain visible |

### WP02: Connection bar initial state (#349)

**Approach:** Add a `"connecting"` state to `ConnectionStatus` and initialize with it. The StatusBar shows a subtle neutral indicator — grey dot with "Connecting..." text.

**Why show "Connecting..." instead of hiding:**
Challenge R1 identified that hiding the indicator entirely means server-down-on-first-load is invisible. The WebSocket lifecycle goes `connecting → onclose → reconnecting → backoff → reconnecting...` and never reaches `"disconnected"` unless unmount. A subtle "Connecting..." provides feedback without the red "Disconnected" flash.

**First-connection failure handling:** If `onclose` fires and `hasConnectedRef.current` is false (the server's `"connected"` message was never received — `use-websocket.ts:43-48`), transition to `"disconnected"` instead of `"reconnecting"`. Note: `hasConnectedRef` is set on the application-level `"connected"` WS message (inside `onmessage`), not on the transport-level `onopen`. The distinction matters: `onopen` fires on TCP connect, but the server may not send the `"connected"` message if initialization fails. Still call `scheduleReconnect()` — "disconnected" means "failed to connect, will retry" not "gave up".

**Changes:**

| File | Change |
|------|--------|
| `create-app-state.ts` | Add `"connecting"` to `ConnectionStatus` union, change initial value to `"connecting"` |
| `status-bar.tsx` | Early return for `"connecting"`: grey dot (`--ht-text-dim`) + "Connecting..." text. Refactor binary ternary into a proper state map for all 4 states |
| `use-websocket.ts` | (1) Move `state.connection.value = "connected"` from `onopen` (line 27) to the `case "connected"` branch in `onmessage` — the connection is only truly ready when the server sends the application-level `"connected"` message, not on TCP connect. (2) In `onclose`: if `!hasConnectedRef.current`, set `"disconnected"` (+ scheduleReconnect). Otherwise set `"reconnecting"` (existing behavior) |

**Design tokens:** Grey dot uses `--ht-text-dim` (`#9898a0` light / `#555560` dark) from direction.md.

### WP03: Decouple app actions from dev_mode (#348)

**Approach:** Remove `_check_reload_allowed()` and its three call sites.

**Risk acknowledgment:** `reload_app` does a non-atomic `stop_app()` then `start_app()` (`app_lifecycle_service.py:327-339`). If start fails after stop, the app stays down with no automatic rollback. This is an accepted risk — the operator explicitly triggered the action and can restart Hassette if needed. A blue/green reload mechanism is out of scope for this bug fix.

**No auth change:** The `_check_reload_allowed` guard was a config-flag gate, not authentication. There is no authentication on any Hassette API endpoint today. Removing this guard doesn't change the auth posture — it was never auth to begin with. API authentication is a separate concern tracked under the HA Addon milestone.

**Config semantics:** After this change, `allow_reload_in_prod` only controls the file watcher. The name becomes slightly misleading but renaming it is a breaking config change — out of scope for a bug fix. A comment will be added to the config field clarifying its narrowed scope.

**Changes:**

| File | Change |
|------|--------|
| `web/routes/apps.py` | Delete `_check_reload_allowed()` and remove 3 call sites |
| `tests/integration/test_web_api.py` | Rename `test_app_management_forbidden_in_prod` to `test_app_management_works_without_dev_mode`, assert 202 |
| `config/config.py` | Update `allow_reload_in_prod` docstring to clarify it only controls the file watcher |

### WP04: Fix flaky throttle test (#340)

**Approach:** Mock `time.monotonic` at the module level to control time deterministically. Remove real `asyncio.sleep` calls — they tested asyncio scheduler timing, not throttle logic.

**Mock target:** `hassette.bus.rate_limiter.time.monotonic` (module-scoped, not global). Global patching would affect asyncio internals and other coroutines sharing the event loop.

**Test pattern:** Advance time via `mock_time.return_value = X` between calls. No `asyncio.sleep`. The throttle decision is purely based on `time.monotonic()` comparison at `rate_limiter.py:100-101`, so controlling that value is sufficient.

**Changes:**

| File | Change |
|------|--------|
| `tests/integration/test_listeners.py` | Rewrite `test_throttle_tracks_time_correctly`: use `@patch("hassette.bus.rate_limiter.time.monotonic")` with discrete time steps. Remove `asyncio.sleep` calls, replace with `mock_time.return_value` assignments |

**Web UI watcher test isolation:** Verified — each test gets a fresh `watcher` fixture with a fresh `mock_hassette`. No changes needed.

## Alternatives Considered

**#380 — Registration-time reconciliation (Rev 1):** Fatal race condition due to fire-and-forget async task spawning with no synchronization barrier.

**#380 — Teardown-time deletion in stop_app (Rev 2):** `shutdown_all()` and crash bypass `stop_app()`, leaving stale rows from prior sessions.

**#380 — Soft delete with `is_active` column:** More complex (migration, query changes, bookkeeping) for the same outcome. Startup-time DELETE + nullable FK is simpler.

**#349 — Hide indicator entirely for "connecting":** Server-down-on-first-load becomes invisible.

**#349 — Session storage for last-known state:** Over-engineered for a <200ms problem.

**#348 — Keep the guard but default `allow_reload_in_prod` to True:** Adds a config knob nobody asked for.

**#340 — Global `time.monotonic` patch:** Would affect asyncio internals.

## Execution Order

WP03 → WP02 → WP04 → WP01

Rationale: WP03 is the simplest (pure deletion). WP02 is frontend-only. WP04 is test-only. WP01 is the most involved (migration + backend + test) and benefits from WP03 being done first.
