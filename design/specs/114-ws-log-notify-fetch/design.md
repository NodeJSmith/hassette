# Design: WS Log Notify-and-Fetch

**Date:** 2026-09-25
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-09-25-ws-log-notify-fetch/research.md

## Problem

Log entries are assembled two different ways depending on the delivery path:

- **REST** — `get_log_records()` in `src/hassette/core/telemetry/summary_queries.py` does a LEFT JOIN on the `executions` table to pull `execution_kind`, `listener_id`, and `job_id` alongside the log row. The DB query is the single source of truth.
- **WebSocket** — `CorrelationFilter` stamps fields onto the log record from structlog context vars, `_extract_correlation_attrs` pulls them into a `LogEntry` dataclass, and `LogCaptureHandler.emit()` broadcasts that entry over the WS. No DB access — every linking field must be independently threaded through context vars → filter → dataclass → WS message.

This dual-path assembly already caused a bug where WS log entries lacked `execution_kind`, `listener_id`, and `job_id` that REST had for free via the JOIN. Any future correlation field added to the DB-backed query must be remembered and re-implemented on the WS side, with no structural guarantee the two stay in sync.

## Goals

- Eliminate the dual-path log assembly so new correlation fields only need to be added in one place (the SQL query / REST model).
- Make the DB query in `summary_queries.py` the single source of truth for the full enriched log shape.
- Maintain identical user experience — logs stream in real-time, execution links work, filtering works.

## Non-Goals

- Log pagination UI — the REST endpoint supports `limit` but not `offset`; pagination is a separate concern.
- #1250 (execution linking UI enrichment) — this change unblocks it but does not implement it.
- Richer filtering on the REST endpoint beyond `since_id`.
- Complete removal of `CorrelationFilter` — it still stamps `execution_id`, `app_key`, `source_tier`, `instance_name`, `instance_index` for DB persistence via `LOG_RECORD_COLUMNS`.
- Per-client WS message filtering / topic subscriptions beyond the existing `subscribe_logs` gate — relevant to future HACS integration but orthogonal to this change. The WS broadcast is unfiltered for most message types, but `log`/`log_hint` messages are already gated per-client via `subscribe_logs` in `ws.py`'s `_send_from_queue`. This change extends that gate to also match `log_hint` (gated on `subscribe_logs` only — no `min_log_level` sub-filter, since hints carry no level).

## User Scenarios

### Developer: Dashboard operator

- **Goal:** Monitor live logs and investigate execution context
- **Context:** Hassette dashboard open in browser, watching automations run

#### Live log tailing

1. **Opens the logs page or an app's log tab**
   - Sees: log entries streaming in real-time with level, message, timestamp, app, function
   - Decides: whether to filter by level, tier, app, or search term
   - Then: entries continue streaming through the filter

2. **Clicks a log entry to inspect execution context**
   - Sees: log detail drawer with execution_kind, listener_id, job_id, linking to the related handler/job
   - Decides: whether to navigate to the execution detail
   - Then: navigates via execution link (this linking metadata comes from REST, not WS)

3. **Reconnects after a browser tab is backgrounded**
   - Sees: log entries catch up to current state
   - Decides: nothing — automatic
   - Then: cursor-based fetch fills the gap from `lastSeenId` (the DB's auto-incrementing `id`)

## Functional Requirements

- **FR#1** The WS broadcast for log events sends a `log_hint` message containing only `type` and `timestamp` — a pure notification with no log content, no linking metadata, and no cursor value. `log_hint` is gated per-client on `subscribe_logs` (same as the current `log` type) but bypasses `min_log_level` filtering since it carries no level.
- **FR#2** `_extract_correlation_attrs` and `LogEntry` no longer extract or carry `execution_kind`, `listener_id`, or `job_id` for WS broadcast. `CorrelationFilter` continues to stamp these fields onto log records (they are still used by `promote_record_attrs` for console/JSON log output via `_RECORD_FIELDS`, which is unchanged).
- **FR#3** `LogEntry` dataclass no longer carries `execution_kind`, `listener_id`, or `job_id` fields.
- **FR#4** A new REST endpoint (`GET /logs/since/{since_id}`) returns only records with `id > since_id`, ordered by `id ASC`, where `id` is the DB's auto-incrementing primary key. This is a separate endpoint from `GET /logs/recent` (which remains unchanged as the latest-N DESC query).
- **FR#5** REST `get_log_records` remains the single source of truth for the full enriched log shape, including all linking metadata via its LEFT JOIN on `executions`.
- **FR#6** The frontend, on receiving a `log_hint` WS message, debounces and fetches the enriched batch from the REST endpoint using its locally tracked `lastSeenId` cursor (the max `id` from the most recent REST response), preserving the same filter set (`appKey`, `executionId`, `level`, `source_tier`, `since`) the view's existing base query applies.
- **FR#7** Under bursty log rates, multiple `log_hint` messages received within the debounce window are coalesced into a single REST fetch.
- **FR#8** On WS reconnect, the frontend fetches from its `lastSeenId` to fill the gap — the DB `id` cursor is persistent across server restarts, unlike the in-process `seq` counter.
- **FR#9** `LogEntryResponse` includes the DB `id` field so the frontend can track its cursor.
- **FR#10** `get_log_records_since` orders by `lr.id ASC` to guarantee completeness — the frontend gets records in insertion order starting from its cursor. This is a separate function from `get_log_records` (which remains `timestamp DESC, seq DESC`), not a mode switch on the same function.
- **FR#11** Independent of hint-triggered fetches, the frontend re-syncs from its cursor every 5 seconds while the log view is mounted. This closes the residual gap in FR#6: a hint-triggered fetch that races an uncommitted DB write (see the "Hint arrives before DB write completes" edge case) only self-corrects on a *subsequent* hint, and if the app goes quiet right after, none may ever arrive.

## Edge Cases

- **Rapid burst of log_hint messages:** Frontend must coalesce multiple hints into one REST fetch. The debounce pattern from `SEARCH_DEBOUNCE_MS` in `use-log-filters.ts` is the model.
- **WS reconnect gap:** After a reconnect, the frontend's `lastSeenId` may be behind. The first `log_hint` after reconnect triggers a fetch using `since_id=lastSeenId`, which catches up all missed records in one batch. Because `id` is the DB's `INTEGER PRIMARY KEY AUTOINCREMENT`, it is persistent and monotonic across server restarts — unlike the in-process `seq` counter (`CorrelationFilter._seq = itertools.count(1)`) which resets to 1 on every process restart.
- **Log record written to DB but no hint delivered:** Possible under WS disconnection. The next reconnect-triggered fetch covers this via the cursor. No data loss — just delayed visibility until the next REST fetch.
- **DB `id` overflow:** SQLite's max rowid is 2^63 - 1. Not a practical concern.
- **DB `id` regression (backup restore, telemetry wipe):** If the DB is replaced or wiped, `id` values restart below the frontend's `lastSeenId`. The frontend detects this: if a catch-up fetch returns a max `id` smaller than `lastSeenId`, reset `lastSeenId` to the fresh value and surface a one-time "log stream reset" notice so the gap is visible rather than a silent indefinite stall.
- **Empty fetch result:** `since_id` returns no records (all hints were for records already fetched). Frontend handles this gracefully — no UI change, no error.
- **Hint arrives before DB write completes:** `LogCaptureHandler.emit()` fires synchronously, before the async DB persistence queue commits the record. The hint carries no cursor — it's just a "go fetch" signal. The frontend's fetch uses its own `lastSeenId` from prior REST responses. If the fetch fires before the new record is committed, it returns the already-committed records; the record appears on the next fetch. A *subsequent hint* isn't guaranteed to happen — if the app goes quiet right after the record that lost this race, nothing else would prompt a retry. FR#11's periodic re-sync is the fallback: it bounds this delay to one re-sync interval regardless of whether further logging occurs, rather than depending on it.
- **DB write-queue saturation (accepted regression):** `DatabaseService.enqueue()` drops entire batches (up to 50 records) on `QueueFull`. Today, WS broadcasts log content independently of DB write success — two independent best-effort paths. After this change, WS carries no content, so a dropped DB write means those logs never become visible. This is an accepted behavioral regression for a self-hosted personal tool: DB write-queue saturation under extreme sustained load is a narrow edge case, and building a fallback reconciliation path adds complexity disproportionate to the risk. The "no data loss" guarantee is bounded by DB write-queue capacity.
- **`since` (timestamp) and `since_id` interaction:** `get_log_records_since` accepts the same filter set as `get_log_records` (including `since` for timestamp filtering). When both `since_id` and `since` are provided, they combine via AND — `since_id` filters by row identity, `since` filters by time range. They are independent and composable.

## Acceptance Criteria

- **AC#1** `LogWsMessage` is replaced by `LogHintWsMessage` carrying only `type` and `timestamp` — no log content, no cursor. (FR#1)
- **AC#2** `_extract_correlation_attrs()` no longer returns `execution_kind`, `listener_id`, or `job_id`, and `LogEntry` no longer carries these fields. `_RECORD_FIELDS` is unchanged (it serves console/JSON log output, not WS). (FR#2, FR#3)
- **AC#3** `GET /logs/since/{N}` returns only log records with `id > N`, ordered by `id ASC`, with full linking metadata via LEFT JOIN. `GET /logs/recent` remains unchanged. (FR#4, FR#5)
- **AC#4** Frontend log table displays log entries with execution linking metadata that was fetched from REST, not from the WS payload. (FR#6)
- **AC#5** Under a burst of 10+ log_hint messages within 100ms, only 1 REST fetch is issued. (FR#7)
- **AC#6** After a WS reconnect, log entries from the disconnected period appear without manual refresh. The cursor (`lastSeenId`) survives server restarts because it uses the DB's `id` column, not the in-process `seq`. (FR#8)
- **AC#7** Regenerated schemas (`export_schemas.py --types`) reflect the new `LogHintWsMessage` and any changes to REST response models.
- **AC#8** All existing backend and frontend tests pass (with updates for the changed WS message shape).
- **AC#9** If a catch-up fetch or the base query's own refresh returns a max `id` below the current `lastSeenId`, the cursor resets and a one-time "log stream reset" notice is surfaced. Both producers write through the same merge function, so this guard is not bypassable by a base-query refetch (e.g. a WS reconnect or preset/filter change) racing a catch-up merge. (FR#6, FR#8, edge case: DB id regression)
- **AC#10** The catch-up loop fires at most 5 consecutive full-page fetches per episode, with at least 100ms between fetches, and backs off on non-2xx responses. (FR#10, edge case: burst catch-up)
- **AC#11** The frontend re-syncs from its cursor every 5 seconds independent of hint activity, so a record that lost the "hint arrives before DB write completes" race is never invisible for longer than one re-sync interval, even if no further logging occurs. A permanent (4xx) failure discovered by this periodic re-sync still surfaces a toast (once per catch-up chain lifetime, same gate as a hint-triggered failure); a transient failure discovered by the periodic re-sync does not toast, since a hint-triggered attempt already covers that case and a 5-second poll would otherwise spam the toast during any sustained outage. (FR#11)

## Key Constraints

- `LogCaptureHandler.emit()` is a synchronous logging handler — it cannot perform DB queries, await coroutines, or block. The hint payload must be constructable from in-process state only (which is why the hint carries no DB-assigned cursor).
- The in-process `seq` counter (`CorrelationFilter._seq = itertools.count(1)`) resets to 1 on every process restart. It is not suitable as a cross-restart cursor. The DB `id` column is the correct cursor substrate.
- The frontend's `rowKey()` dedup function primarily keys on `(timestamp, seq)`, falling back to `(timestamp, logger_name, lineno)` when `seq` is null/undefined, and `(timestamp, 0, logger_name, lineno)` when `seq === 0`. This key does not change — REST entries always carry `seq`, and WS no longer delivers log content at all.

## Dependencies and Assumptions

- The `id` column (`INTEGER PRIMARY KEY AUTOINCREMENT`) is already present on the `log_records` table and is selected by `lr.*` in the SQL query. However, `LogEntryResponse` does not currently include an `id` field — Pydantic silently drops it. Adding `id: int` to `LogEntryResponse` is required for the frontend cursor to work. No DB schema migration needed.
- The REST endpoint `/logs/recent` already exists and returns `LogEntryResponse` with full linking metadata. The new `/logs/since/{since_id}` endpoint reuses the same response model and filter set.
- **Accepted risk:** There is a small latency window between a log event and its appearance in the UI — the debounce interval plus the REST round trip, rather than the previous near-instant WS delivery. For a monitoring dashboard this is acceptable.
- **Related issue:** There is an existing issue for migrating WS-pushed logs to TanStack Query. This PR addresses that concern as part of the notify-and-fetch migration — link the issue when creating the PR.

## Architecture

### Backend

**Add `id: int` to `LogEntryResponse`** in `src/hassette/web/models.py`. The SQL query already selects `lr.*` which includes `id`, but `LogEntryResponse` currently lacks the field — Pydantic silently drops it. The frontend cursor (`lastSeenId`) needs this field in REST responses.

**Replace `LogWsMessage` with `LogHintWsMessage`** in `src/hassette/web/models.py`. The new model:

```python
class LogHintWsMessage(BaseModel):
    type: Literal["log_hint"]
    timestamp: float
```

A pure notification — no cursor value, no log content. Named `LogHintWsMessage` to follow the established `*WsMessage` suffix convention (`AppStatusChangedWsMessage`, `ConnectedWsMessage`, etc.). Register it in the WS message discriminated union.

**Trim `LogCaptureHandler.emit()`** in `src/hassette/logging_.py`. Instead of building a full `LogEntry` and broadcasting its dict, broadcast a `LogHintWsMessage`-shaped dict: `{"type": "log_hint", "timestamp": time.time()}`. The handler no longer needs to construct a `LogEntry` for broadcast purposes. Note: `record.seq` is stamped synchronously by `CorrelationFilter.filter()` (via `itertools.count(1)`) before `emit()` runs, so it is available at emit time — but it is an in-process counter that resets to 1 on every process restart, making it unsuitable as a cursor. The hint carries no cursor; the cursor lives in the frontend (see below).

**Trim `_extract_correlation_attrs` and `LogEntry`** — remove `execution_kind`, `listener_id`, `job_id` from `_extract_correlation_attrs()` and from the `LogEntry` dataclass. These fields are consumed only by the WS broadcast path (`LogCaptureHandler.emit()` → `LogEntry.to_dict()`), not by DB persistence (`LOG_RECORD_COLUMNS`). **Leave `_RECORD_FIELDS` unchanged** — `_RECORD_FIELDS` is used by `promote_record_attrs()` in the `ProcessorFormatter` chain (console/JSON log output), not the WS path. Linking fields (`execution_kind`, `listener_id`, `job_id`) in console logs are useful diagnostics and not the problem this design solves. `CorrelationFilter` continues to stamp all fields it does today — its role as the context-var→record bridge is unchanged; the only change is that `_extract_correlation_attrs()` and `LogEntry` no longer read the linking fields off the record for WS broadcast purposes.

**Trim `LogEntry` dataclass** — remove the three linking fields. `LogEntry` is only instantiated by `LogCaptureHandler.emit()` for the in-memory buffer/WS payload — `LogPersistenceHandler` builds its own dict directly from the `LogRecord` via `record_to_dict()`, never constructing a `LogEntry`. The linking fields were never in `LOG_RECORD_COLUMNS` (the DB insert tuple), so removing them from `LogEntry` has zero persistence impact.

**Add a new `get_log_records_since(since_id, *, limit, app_key, execution_id, level, source_tier, since)` function** in `src/hassette/core/telemetry/summary_queries.py` — a dedicated cursor-based catch-up query, separate from the existing `get_log_records()`. It uses the same LEFT JOIN and filter set but orders `lr.id ASC` (not the existing `timestamp DESC, seq DESC`) and requires `since_id` as a non-optional parameter. ASC ordering guarantees completeness — the frontend gets records in insertion order starting from its cursor, and advances `lastSeenId` to the max `id` in the batch. If the response is full (`len(results) == limit`), the frontend knows there may be more and fetches again (subject to the catch-up loop bounds). `id` is the table's `INTEGER PRIMARY KEY AUTOINCREMENT` — persistent, monotonic, and collision-free across restarts (unlike `seq`). The existing `get_log_records()` is unchanged — it remains the latest-N DESC query for initial page loads and preset-driven refetches.

**Add a new REST route** for the catch-up query (`GET /logs/since/{since_id}`) in `src/hassette/web/routes/logs.py`, calling `get_log_records_since()`. The existing `GET /logs/recent` route and `get_log_records()` function are unchanged.

### Frontend

**Add `log_hint` handler to WS message dispatch** in `frontend/src/hooks/use-websocket.ts`. On receiving a `log_hint` message, update a Zustand store value (e.g., increment a `logHintVersion` counter) that triggers a debounced REST fetch.

**Replace WS log merge with hint-triggered REST fetch** in `frontend/src/components/shared/log-table/use-log-data.ts`. The current pattern merges WS-pushed log entries with REST-fetched entries. Replace:
- Remove the WS log entry accumulation path entirely.
- On `log_hint`, debounce, then fetch `getLogsSince(lastSeenId, currentFilters)` — the hint-triggered fetch must carry the same filter set (`appKey`, `executionId`, `level`, `source_tier`, `since`) the view's existing base query already applies.
- Merge the fetched batch into the existing REST entries (dedup by `rowKey()`).
- Update `lastSeenId` to the max `id` in the response.

**Update `endpoints.ts`** — add a new `getLogsSince(since_id, filters)` function for cursor-based catch-up fetches (existing `getRecentLogs()` unchanged).

**Cursor tracking:** `lastSeenId` is derived from the max `id` in the TanStack Query cache entry that `useScopedQuery` already owns — not maintained as separate local state. Hint-triggered fetches write their results into that same cache entry via `queryClient.setQueryData`, so `lastSeenId` recomputes from any write regardless of trigger (base fetch, hint-triggered incremental, preset change, reconnect-driven invalidation). This keeps a single source of truth for "what's currently shown" and avoids cursor/base-query desynchronization when the user changes the time preset or the WS reconnects. Each `useLogData` hook instance maintains its own `lastSeenId` derived from its own scoped cache entry — not a shared global value — so differently-filtered concurrent views (app panel, execution panel, global logs page) track independent cursors. The cursor is persistent across server restarts because it uses the DB's auto-incrementing primary key. The WS hint carries no cursor value.

**Coalescing strategy:** Use a debounce with `maxWait` (~200ms debounce, ~500ms maxWait). Each `log_hint` resets the debounce timer, but the `maxWait` cap guarantees a fetch fires at least every 500ms even under continuous hints — preventing a sustained burst from silencing the log table for its entire duration. The `SEARCH_DEBOUNCE_MS` pattern in `use-log-filters.ts` is the starting shape, extended with a `maxWait` cap.

**Catch-up loop:** When a hint-triggered fetch returns a full page (`len(results) === limit`), there may be more records. The frontend re-fetches with the new `lastSeenId`, subject to bounds: max 5 consecutive full-page fetches per catch-up episode, minimum 100ms inter-fetch delay, and exponential backoff on non-2xx responses (reuse the `INITIAL_BACKOFF_MS`/`MAX_BACKOFF_MS` pattern from `use-websocket.ts`). If the cap is reached, stop and let the next hint trigger another catch-up round. Route all catch-up fetches through `queryClient.fetchQuery` so TanStack's retry and error-state propagation apply.

### Cursor design rationale

**Why DB `id`, not in-process `seq`:** `seq` comes from `CorrelationFilter._seq = itertools.count(1)`, which resets to 1 on every process restart. A cursor based on `seq` would silently miss post-restart records when the counter re-traverses previously-seen values. The DB's `id` column (`INTEGER PRIMARY KEY AUTOINCREMENT`) is persistent, monotonic, and collision-free across restarts — the right substrate for a cursor.

**Why the cursor lives in the frontend, not the hint:** `LogCaptureHandler.emit()` runs synchronously before the DB write completes (persistence goes through an async queue). The handler has no access to the DB `id` that will be assigned on INSERT. Rather than building cross-component signaling to feed the committed `id` back to the handler, the hint is a pure notification and the frontend tracks its own `lastSeenId` from REST responses — simpler and equally correct.

## Implementation Preferences

No specific implementation preferences — follow codebase conventions. Pydantic models for WS messages, FastAPI query params for REST, vitest for frontend tests, existing debounce patterns.

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `LogWsMessage` in `web/models.py` | `LogHintWsMessage` | Remove `LogWsMessage` class, update discriminated union |
| `LogEntry.execution_kind`, `.listener_id`, `.job_id` in `logging_.py` | (removed — not needed) | Remove fields from dataclass and `_RECORD_FIELDS` |
| `_extract_correlation_attrs` linking field extraction | (trimmed — WS broadcast no longer reads them) | Remove `execution_kind`/`listener_id`/`job_id` from extraction output |
| Frontend WS log entry accumulation in `use-log-data.ts` | Hint-triggered REST fetch | Replace WS merge path with debounced REST fetch on `log_hint` |

## Convention Examples

### WS message model registration

**Source:** `src/hassette/web/models.py:260-263`

```python
class AppStatusChangedWsMessage(BaseModel):
    type: Literal["app_status_changed"]
    data: AppStatusChangedData
    timestamp: float
```

New `LogHintWsMessage` follows this `*WsMessage` naming convention and Literal type discriminator. Note: existing classes use bare `Literal["..."]` with no default value on `type`.

### REST endpoint with query params

**Source:** `src/hassette/web/routes/` (log endpoint)

Existing log endpoint accepts `limit` and `since` (timestamp). The new `GET /logs/since/{since_id}` route follows the same FastAPI route/query-param patterns, backed by the separate `get_log_records_since()` function.

### Frontend WS message dispatch

**Source:** `frontend/src/hooks/use-websocket.ts:120-129`

```typescript
case "app_status_changed":
  useAppStore.getState().updateAppStatus(appStatusKey(msg.data.app_key, msg.data.index), {
    status: msg.data.status,
    index: msg.data.index,
    previous_status: msg.data.previous_status,
    instance_name: msg.data.instance_name,
    class_name: msg.data.class_name,
    exception: msg.data.exception,
  });
  break;
```

New `log_hint` case follows this switch dispatch pattern — call a store action (e.g., increment a `logHintVersion` counter) that triggers the debounced fetch.

### Debounce pattern

**Source:** `frontend/src/components/shared/log-table/use-log-filters.ts`

```typescript
const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
// ...
if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
searchDebounceRef.current = setTimeout(() => {
  // perform the debounced action
}, SEARCH_DEBOUNCE_MS);
```

Hint coalescing uses this same clearTimeout/setTimeout pattern.

## Alternatives Considered

### Keep full payload over WS (status quo)

Continue threading linking fields through context vars → CorrelationFilter → LogEntry → WS broadcast. Rejected because this is the source of the problem — every new field requires independent implementation on both paths, with no structural sync guarantee.

### Periodic polling (no WS involvement)

Frontend polls REST on a fixed interval. Simpler but adds latency (bounded by poll interval) and wastes requests when nothing changed. The hint pattern gives the same "poll only when there's new data" property without wasted requests.

### Full enriched payload via deferred broadcast

Defer the WS broadcast until after the DB write completes, then query the DB for the enriched record and broadcast it. This would maintain single-source-of-truth while keeping WS as the delivery mechanism. Rejected because `LogCaptureHandler.emit()` is synchronous — introducing async DB queries or deferred broadcast would require significant refactoring of the logging pipeline.

## Test Strategy

### Required Test Types

- **Unit (backend):** LogHintWsMessage construction, CorrelationFilter trimming, LogEntry shape, `since_id` query filtering. Single-module changes in `logging_.py` and `summary_queries.py`.
- **Unit (frontend):** `log_hint` handler in WS dispatch, debounce/coalesce behavior, cursor tracking in use-log-data.
- **Integration (backend):** WS broadcast sends `log_hint` not full log payload. REST endpoint returns filtered results with `since_id`.

Not needed: System tests (no reconnection behavior changes), E2E (transparent plumbing change, no UI interaction changes).

### Existing Tests to Adapt

- `tests/unit/test_logging_setup.py` — tests asserting `LogEntry` field set, `_RECORD_FIELDS` contents, `CorrelationFilter` behavior for linking fields.
- `tests/unit/core/test_logging_service.py` — tests asserting WS broadcast payload shape (if any assert `LogWsMessage` structure).
- `tests/integration/web_api/` — tests asserting WS log message shape will need updating from full `LogWsMessage` to `LogHintWsMessage`.
- `frontend/src/components/shared/log-table/use-log-table.test.tsx` — may need updating if it mocks WS log entries.
- `frontend/src/components/shared/log-table/use-log-data` tests (if they exist) — will need rewrite for hint-triggered fetch pattern.
- `tests/integration/test_schema_freshness.py` — hardcodes `LogWsMessage` in a parametrize list; will `KeyError` on the removed schema key.
- `tests/unit/test_ws_models.py` — imports `LogWsMessage`, asserts `isinstance`; needs updating to `LogHintWsMessage`.
- `tests/unit/test_logging_capture_handler.py` — imports `LogWsMessage`, validates broadcast envelope against it; needs updating for new hint shape.

### New Test Coverage

- LogHintWsMessage contains only `type` and `timestamp` (FR#1)
- `_RECORD_FIELDS` excludes linking fields (FR#2)
- `get_log_records_since(since_id=N)` returns only records with `id > N`, ordered `id ASC` (FR#4, FR#10)
- Frontend debounce: 10+ hints within 100ms → 1 REST fetch (FR#7)
- Frontend cursor tracking: `lastSeenId` advances to max `id` in response (FR#6)
- Frontend cursor regression: `lastSeenId` resets when fetch returns max `id` below current cursor (AC#9)
- Frontend catch-up loop bounds: max 5 consecutive full-page fetches, 100ms minimum delay, backoff on non-2xx (AC#10)

### Tests to Remove

- Tests asserting `LogWsMessage` structure (replaced by `LogHintWsMessage` assertions).
- Tests asserting `CorrelationFilter` stamps `execution_kind`/`listener_id`/`job_id` (those are no longer stamped).

## Documentation Updates

- No user-facing documentation changes — this is transparent plumbing. The log table docs describe what the user sees, not the delivery mechanism.
- Update `CLAUDE.md` if it references `LogWsMessage` or the WS log broadcast mechanism directly (check for references).

## Impact

### Changed Files

- **modify** `src/hassette/web/models.py` — add `id: int` to `LogEntryResponse`, replace `LogWsMessage` with `LogHintWsMessage`, update discriminated union
- **modify** `src/hassette/logging_.py` — trim `LogEntry`, `_RECORD_FIELDS`, `_extract_correlation_attrs`, `CorrelationFilter`; change `LogCaptureHandler.emit()` to broadcast hint instead of full entry
- **modify** `src/hassette/core/telemetry/summary_queries.py` — add new `get_log_records_since()` function (existing `get_log_records()` unchanged)
- **modify** `src/hassette/web/routes/logs.py` — add new `GET /logs/since/{since_id}` route (existing `GET /logs/recent` unchanged)
- **modify** `src/hassette/web/routes/ws.py` — extend `_send_from_queue`'s log filter to also match `log_hint` (gated on `subscribe_logs` only, no `min_log_level` sub-filter)
- **modify** `frontend/src/hooks/use-websocket.ts` — add `log_hint` case to message dispatch
- **modify** `frontend/src/components/shared/log-table/use-log-data.ts` — replace WS log merge with hint-triggered REST fetch
- **modify** `frontend/src/api/endpoints.ts` — add new `getLogsSince()` function for cursor-based catch-up (existing `getRecentLogs()` unchanged)
- **modify** `frontend/src/state/store.ts` — remove dead code: `pushLog`, `logBuffer`, `getLogEntries`, `logVersion`, `WsLogPayload` (orphaned after WS log content path is removed)
- **regenerate** `openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`, `ws-validator.generated.ts`
- **modify** tests in `tests/unit/test_logging_setup.py`, `tests/unit/core/test_logging_service.py`, `tests/integration/web_api/`
- **modify** frontend tests for log table/data hooks

<!-- Gap check 2026-09-25: 7 gaps included —
  tests/support/web_telemetry_helpers.py:make_log_entry_response (LogEntryResponse needs id) → T01 Focus
  tests/unit/test_model_types.py:minimal_log_entry_response (LogEntryResponse needs id) → T01 Focus
  frontend/src/test/factories.ts (LogEntryResponse needs id) → T06 Focus
  frontend/src/test/handlers.ts (LogEntryResponse needs id) → T06 Focus
  frontend/src/test/log-data-test-utils.ts (WsLogPayload, WS merge pattern) → T05 Target Files
  frontend/src/hooks/use-websocket.test.ts (pushLog/getLogEntries assertions) → T04 Target Files
  frontend/src/state/store.test.ts (pushLog/logBuffer/logVersion tests) → T04 Target Files
-->

### Behavioral Invariants

- REST `get_log_records` continues to return the full enriched log shape with linking metadata — no change to the response model.
- Frontend log table continues to display the same columns, filters, and sorting as today.
- Frontend log detail drawer continues to show execution links (execution_kind, listener_id, job_id) — sourced from REST data.
- `LogPersistenceHandler` DB writes are unaffected — `LOG_RECORD_COLUMNS` does not change.
- Other WS message types (`app_status_changed`, `connectivity`, `service_status`, `app_manifests_changed`) are unaffected.

### Blast Radius

- **Frontend log consumers:** All components using `useLogTable` / `useLogData` — `app-logs-panel.tsx`, `overview-tab.tsx`, `execution-logs.tsx`, `logs.tsx`. These consume the hook's output (which will now be REST-only), not the WS messages directly.
- **WS schema consumers:** `ws-schema.json` and generated `ws-types.ts` / `ws-validator.generated.ts` — the `log` message type is replaced by `log_hint`.
- **HACS integration (future):** Will receive `log_hint` messages it doesn't need. Benign — same as today with `log` messages. Per-client filtering is a separate concern.

## Open Questions

(None — all questions resolved during discovery.)
