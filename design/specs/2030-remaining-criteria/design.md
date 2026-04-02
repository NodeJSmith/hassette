# Design: Issue #268 Remaining Criteria

**Date:** 2026-03-31
**Status:** archived
**Research:** design/research/2026-02-16-sqlite-command-pattern/prereq-04-frontend-query-requirements.md

## Problem

Issue #268 tracks follow-up features for the SQLite telemetry backend. Of 8 original acceptance criteria, 3 are done (invocation drill-down, retention cleanup, heartbeat) and error hooks were split to #213. Four remain:

1. **Session list UI** — `get_session_list()` query exists and is tested, but there's no HTTP endpoint, no frontend page, and no sidebar link.
2. **Current session vs all-time toggle** — every backend query accepts `session_id: int | None`, but the server hardcodes `safe_session_id(runtime)` in all route handlers. The client has no way to request all-time data.
3. **Size failsafe** — `db_max_size_mb` config doesn't exist. No size checking, no oldest-record deletion logic.
4. **Source code display** — `registration_source` and `source_location` flow end-to-end from DB through API to generated frontend types, but neither `handler-row.tsx` nor `job-row.tsx` renders them.

## Non-Goals

- Error hooks (tracked in #213)
- New query patterns beyond what prereq-04 specifies
- Session picker dropdown (selecting a specific historical session) — the toggle is binary: current session or all-time

## Architecture

### AC 1: Session List UI

**Backend**: Add a `SessionListEntry` Pydantic model to `src/hassette/web/models.py` with fields matching the existing `get_session_list()` return shape: `id`, `started_at`, `stopped_at`, `status`, `error_type`, `error_message`, `duration_seconds`. Add `GET /telemetry/sessions` to `src/hassette/web/routes/telemetry.py` that calls `telemetry.get_session_list()`. The endpoint accepts `limit: int = Query(default=50, ge=1, le=200)` and passes it through to the query service (matching the pattern used by `/handler/{id}/invocations` and `/job/{id}/executions`). Wrap the call in `try/except DB_ERRORS` with `_reraise_if_not_connection_closed()`, returning an empty list on DB failure (consistent with `dashboard_errors`).

**Frontend**:
- `frontend/src/api/endpoints.ts` — add `getSessionList()` fetcher
- `frontend/src/pages/sessions.tsx` — new page component: a table of sessions with status badges (reuse existing `ht-status-badge` pattern), formatted timestamps, duration, and error info. Ordered by most recent first.
- `frontend/src/app.tsx` — add `/sessions` route
- `frontend/src/components/layout/sidebar.tsx` — add "Sessions" nav item with a clock/history icon (add `IconHistory` to `shared/icons.tsx`)

Additionally, fix `get_session_list()` in `telemetry_query_service.py` to return typed Pydantic models (e.g., `SessionRecord`) instead of `list[dict]`, matching every other query method. This is the last `list[dict]` straggler in the query service — the route handler can then pass typed objects directly to the `SessionListEntry` response model.

The session list is a read-only table page. No expandable rows, no drill-down — just a flat list showing session lifecycle data.

### AC 2: Current Session vs All-Time Toggle

**Decision: Client owns scope.** The server becomes stateless about session scoping. The frontend passes `session_id=<N>` on telemetry requests for current-session mode, or omits it for all-time.

**Backend changes** (`src/hassette/web/routes/telemetry.py`):
- Add optional `session_id: int | None = Query(default=None)` to all 8 telemetry endpoints that currently call `safe_session_id()`.
- Remove the `safe_session_id(runtime)` calls — the client provides session_id explicitly, or omits it for all-time.
- Remove `runtime: RuntimeDep` from the 6 endpoints that no longer use it after removing `safe_session_id()` (`app_health`, `app_listeners`, `app_jobs`, `handler_invocations`, `job_executions`, `dashboard_errors`). Keep `RuntimeDep` on `dashboard_kpis` (for `uptime_seconds`) and `dashboard_app_grid` (for manifests). Update corresponding integration tests.
- Update the module docstring (currently says "the SPA never needs to know or pass a session ID").
- `safe_session_id()` in `telemetry_helpers.py` remains for the WebSocket `connected` payload in `ws.py:95` — add a comment in `telemetry_helpers.py` noting `ws.py` as the remaining consumer.

**Frontend state** (`frontend/src/state/create-app-state.ts`):
- Add `sessionScope: signal<"current" | "all">("current")` initialized from `localStorage` (key: `"sessionScope"`). Persists across page reloads, matching the theme toggle pattern.

**Frontend endpoints** (`frontend/src/api/endpoints.ts`):
- All telemetry fetcher functions gain an optional `sessionId?: number | null` parameter. When provided, append `?session_id=<N>` to the URL. When `null`/omitted, no param (all-time).

**Toggle component** (`frontend/src/components/layout/session-scope-toggle.tsx`):
- Two-button segmented control: "This Session" / "All Time"
- Reads/writes `state.sessionScope` signal
- Writes to `localStorage` on change
- Lives in the status bar (`frontend/src/components/layout/status-bar.tsx`), visible on all pages

**`useScopedApi` wrapper hook** (`frontend/src/hooks/use-scoped-api.ts`):
- New hook that wraps `useApi` and handles scope resolution internally. Reads `state.sessionScope` and `state.sessionId` from app state, computes the effective `sessionId` (current scope + non-null sessionId → pass sessionId; all scope → pass null), and passes it to the fetcher. All telemetry consumers use `useScopedApi` instead of `useApi` directly — this makes it impossible to forget the scope wiring.
- Example: `useScopedApi((sid) => getDashboardKpis(sid), [])` — the hook resolves `sid` from state and includes it in the dependency tracking automatically.
- When `sessionId` is null and scope is `"current"`, the hook returns a loading state and **does not fire the fetch**. This prevents the initial page load from silently returning all-time data before the WebSocket delivers the session ID. The loading state is brief (WebSocket connects within seconds).

**Refetch behavior**: When `sessionScope` or `sessionId` changes, `useScopedApi` automatically refetches. This is handled inside the hook — individual consumers do not need to include scope signals in their deps arrays.

### AC 3: Size Failsafe

**Config** (`src/hassette/config/config.py`):
- Add `db_max_size_mb: int = Field(default=500, ge=0)` after `db_retention_days`. `0` disables the failsafe.
- Docstring: "Maximum database file size in MB. When exceeded, oldest execution records are deleted. 0 disables the size failsafe."

**auto_vacuum setup**: SQLite only reclaims disk space after DELETEs if `auto_vacuum` is enabled. This PRAGMA must be set before the first table is created, so existing databases need a one-time conversion.

- Add Alembic migration that:
  1. Checks current `auto_vacuum` mode via `PRAGMA auto_vacuum`
  2. If not `INCREMENTAL` (value 2), sets `PRAGMA auto_vacuum = INCREMENTAL` and runs `VACUUM`
  3. Logs a warning that this is a one-time operation that may take a few seconds for large databases
- Add `PRAGMA auto_vacuum = INCREMENTAL` to `_set_pragmas()` as documentation of intent only — this is a no-op on all databases because migrations always run first and create tables before `_set_pragmas()` is called. Add an inline comment: "Intentionally a no-op — auto_vacuum is set via the Alembic migration before table creation. This line documents intent only."

**Size check logic** (`src/hassette/core/database_service.py`):
- New method `_check_size_failsafe()`:
  1. If `db_max_size_mb == 0`, return (disabled)
  2. Check total disk footprint: sum `self._db_path.stat().st_size` + WAL file (`-wal`) + SHM file (`-shm`), using `path.stat().st_size if path.exists() else 0` for auxiliary files. Convert bytes → MB.
  3. If under limit, return
  4. Delete oldest 1000 records from `handler_invocations` and `job_executions` (by `execution_start_ts ASC LIMIT 1000`)
  5. Run `PRAGMA incremental_vacuum(100)` to reclaim freed pages in small chunks (shorter exclusive lock windows keep dashboard reads responsive)
  6. Run `PRAGMA wal_checkpoint(TRUNCATE)` to force WAL merge so `st_size` reflects the actual file size
  7. Re-check size; repeat steps 4-6 for up to **10 iterations** per invocation. If still over limit after 10 batches, log a WARNING and stop — the next hourly run will continue cleanup
  8. Log the total records deleted, iterations used, elapsed time, and final file size. If the failsafe has triggered N consecutive hourly runs, log at WARNING: "Size failsafe has triggered N consecutive times — consider increasing db_max_size_mb or db_retention_days."
- Sessions table is exempt from size-based deletion
- New method `_run_size_failsafe()` wraps `_check_size_failsafe()` with the enqueue pattern (matching `_run_retention_cleanup`)

**Integration points**:
- Call `_check_size_failsafe()` directly in `on_initialize()`, **before** the write queue is created (between `_set_pragmas()` and `self._db_write_queue = asyncio.Queue()`). At this point, no other writer exists, so the single-writer invariant is preserved without needing the queue.
- Call `_run_size_failsafe()` in `serve()` loop alongside retention cleanup (same hourly interval, runs after retention)

**Migration timeout**: Wrap the `asyncio.to_thread(self._run_migrations)` call in `asyncio.wait_for()` with a generous timeout (default 120s, configurable via `db_migration_timeout_seconds`). The one-time VACUUM for auto_vacuum conversion can take tens of seconds on slow HA hardware (SD cards, NFS). The migration is idempotent on retry — if it times out, the next startup will complete the conversion.

### AC 4: Source Code Display

Both `handler-row.tsx` and `job-row.tsx` have an expanded detail panel (`.ht-item-detail`). Add registration source display inside this panel, above the invocations/executions table.

**Handler row** (`frontend/src/components/app-detail/handler-row.tsx`):
- In the `ht-item-detail` div, before `<HandlerInvocations>`, render:
  - `source_location` as a muted label (e.g., `my_app.py:42`) using `ht-text-muted ht-text-xs`
  - `registration_source` in an inline `<code>` block using `ht-text-mono ht-text-xs`
- Only render when `source_location` is non-empty OR `registration_source` is non-null (note: `source_location` is `NOT NULL` in the schema with a default of `""`, so a null check is insufficient — use `{(listener.source_location || listener.registration_source) && ...}`)
- No syntax highlighting — plain monospace text

**Job row** (`frontend/src/components/app-detail/job-row.tsx`):
- Same pattern in the `ht-item-detail` div, before `<JobExecutions>`

**Display format**:
```
my_app.py:42
self.bus.on_state_change("light.kitchen", handler=self.on_light_change)
```

The `source_location` line acts as a file reference; the `registration_source` line shows the actual registration call. Both use existing CSS utility classes — no new styles needed.

## Alternatives Considered

**Session toggle: server-provides, client-overrides** — Add `?scope=all` param while keeping server-side session injection as the default. Rejected in favor of client-owns-scope because: (a) it's the industry standard pattern (Grafana, Datadog, Sentry), (b) the server stays stateless and predictable, (c) caching is simpler when same params = same result.

**Size failsafe: skip auto_vacuum, full VACUUM after cleanup** — Simpler setup (no migration) but VACUUM rewrites the entire file and blocks all reads/writes. `auto_vacuum = INCREMENTAL` + `incremental_vacuum` is cheaper per-run at the cost of a one-time migration.

**Size failsafe: no disk reclamation** — Just delete rows and let SQLite reuse freed pages naturally. Rejected because the whole point of a size failsafe is to keep the file from growing unboundedly, and SQLite never shrinks its file without explicit vacuum operations.

## Test Strategy

**AC 1 (Session list UI)**:
- Integration test: `GET /telemetry/sessions` returns session list matching query service output
- E2E test: sessions page renders, sidebar link navigates to it, table shows session data

**AC 2 (Session toggle)**:
- Integration tests: each telemetry endpoint returns all-time data when `session_id` is omitted, session-scoped data when provided
- E2E test: toggle switches between "This Session" and "All Time", KPI numbers change accordingly, preference persists across reload

**AC 3 (Size failsafe)**:
- Unit test: `db_max_size_mb = 0` disables the failsafe
- Integration test: insert enough records to exceed a low `db_max_size_mb` threshold (e.g., 1 MB), verify oldest records are deleted and file size decreases after `incremental_vacuum`
- Integration test: startup size check runs and cleans up oversized DB
- Migration test: verify `auto_vacuum` is set to `INCREMENTAL` after migration on a pre-existing database

**AC 4 (Source display)**:
- E2E test: expand a handler row, verify `source_location` and `registration_source` text appears in the detail panel
- E2E test: same for job row
- E2E test: when both fields are null, no source section renders

## Open Questions

None — all architectural decisions resolved. Challenge findings from 2026-03-31 addressed in revision (14 findings, all resolved).

## Impact

**Backend files modified**:
- `src/hassette/config/config.py` — add `db_max_size_mb` field
- `src/hassette/core/database_service.py` — add size failsafe methods, call from `on_initialize()` (before queue creation) and `serve()`; `_set_pragmas()` add `auto_vacuum` comment; wrap `_run_migrations()` in `asyncio.wait_for()`
- `src/hassette/core/telemetry_query_service.py` — fix `get_session_list()` to return typed models instead of `list[dict]`
- `src/hassette/web/routes/telemetry.py` — add session list endpoint, change all 8 telemetry endpoints to accept `session_id` query param
- `src/hassette/web/routes/bus.py` — also calls `safe_session_id()`, needs same `session_id` query param change for scoping consistency
- `src/hassette/web/models.py` — add `SessionListEntry` model
- `src/hassette/migrations/versions/` — new migration for `auto_vacuum = INCREMENTAL`

**Frontend files modified**:
- `frontend/src/api/endpoints.ts` — add `getSessionList()`, add `sessionId` param to all telemetry fetchers
- `frontend/src/state/create-app-state.ts` — add `sessionScope` signal
- `frontend/src/components/layout/sidebar.tsx` — add Sessions nav item
- `frontend/src/components/layout/status-bar.tsx` — embed session scope toggle
- `frontend/src/components/app-detail/handler-row.tsx` — add source display in detail panel
- `frontend/src/components/app-detail/job-row.tsx` — add source display in detail panel
- `frontend/src/app.tsx` — add `/sessions` route

**Frontend files created**:
- `frontend/src/pages/sessions.tsx` — session list page
- `frontend/src/components/layout/session-scope-toggle.tsx` — toggle component
- `frontend/src/hooks/use-scoped-api.ts` — scope-aware wrapper around `useApi`

**Generated files** (regenerated):
- `frontend/src/api/generated-types.ts` — new `SessionListEntry` type

**Blast radius**: Medium. The session toggle touches every telemetry endpoint and every frontend consumer, but each individual change is small and mechanical. The size failsafe is self-contained in `database_service.py`. Source display and session list are additive.
