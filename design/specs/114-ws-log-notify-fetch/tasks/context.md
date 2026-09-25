# Context: WS Log Notify-and-Fetch

## Problem & Motivation
Log entries are assembled two different ways: the REST API uses a LEFT JOIN on the `executions` table for linking metadata (`execution_kind`, `listener_id`, `job_id`), while the WebSocket path threads the same fields through context vars → CorrelationFilter → LogEntry dataclass. This dual-path assembly already caused a bug where WS entries lacked linking fields REST had. Any new correlation field must be independently re-implemented on both paths with no structural sync guarantee. This change collapses the two paths into one: WS sends a lightweight `log_hint` notification, the frontend fetches the full enriched shape from REST via a cursor-based catch-up query, making the DB query the single source of truth.

## Visual Artifacts
None.

## Key Decisions
1. **Pure notification hint** — WS `log_hint` carries only `type` and `timestamp`, no cursor, no log content. The cursor lives in the frontend (`lastSeenId` from REST responses), not the hint.
2. **DB `id` as cursor, not in-process `seq`** — `seq` comes from `CorrelationFilter._seq = itertools.count(1)`, which resets to 1 on every process restart. The DB's `id INTEGER PRIMARY KEY AUTOINCREMENT` is persistent, monotonic, collision-free.
3. **Separate catch-up function and route** — `get_log_records_since()` + `GET /logs/since/{since_id}` is a dedicated cursor-based query (ORDER BY id ASC), not a mode switch on the existing `get_log_records()` (which stays ORDER BY timestamp DESC, seq DESC).
4. **`log_hint` gated on `subscribe_logs` only** — `ws.py`'s `_send_from_queue` already filters `type=="log"` per-client via `subscribe_logs` and `min_log_level`. `log_hint` is gated on `subscribe_logs` only (no `min_log_level` sub-filter, since hints carry no level).
5. **Hint-triggered fetch preserves view filters** — The fetch carries the same filter set (`appKey`, `executionId`, `level`, `source_tier`, `since`) as the view's existing base query.
6. **Cursor routed through TanStack Query cache** — `lastSeenId` derives from the max `id` in the TanStack Query cache entry `useScopedQuery` owns. Hint-triggered fetches write into that same cache entry via `queryClient.setQueryData`. Per-hook-instance cursor scope (not global).
7. **Debounce with maxWait** — ~200ms debounce, ~500ms maxWait cap to prevent sustained bursts from silencing live tailing.
8. **Bounded catch-up loop** — Max 5 consecutive full-page fetches per episode, 100ms minimum inter-fetch delay, exponential backoff on non-2xx. Routed through `queryClient.fetchQuery` for TanStack retry/error propagation.
9. **DB write-queue loss accepted** — Collapsing WS content broadcast means a dropped DB write (QueueFull) is now permanent log loss, not delayed visibility. Accepted for a self-hosted personal tool.
10. **`id` field added to `LogEntryResponse`** — The SQL already selects `lr.*` including `id`, but `LogEntryResponse` currently lacks it (Pydantic silently drops it). Required for the frontend cursor.

## Constraints & Anti-Patterns
- `LogCaptureHandler.emit()` is synchronous — cannot perform DB queries, await coroutines, or block. Hint must be constructable from in-process state only.
- Do NOT use `seq` as the cursor — it resets on process restart.
- Do NOT add `since_id` as a parameter to the existing `get_log_records()` — use the separate `get_log_records_since()` function.
- Do NOT implement: log pagination UI, #1250 execution linking enrichment, complete CorrelationFilter removal, per-client WS topic subscriptions beyond `subscribe_logs`.
- `CorrelationFilter` still stamps `execution_id`, `app_key`, `source_tier`, `instance_name`, `instance_index` for DB persistence — only the three linking fields (`execution_kind`, `listener_id`, `job_id`) are removed.

## Design Doc References
- `## Problem` — dual-path assembly bug and maintenance burden
- `## Architecture > Backend` — LogHintWsMessage, LogEntry trim, get_log_records_since, ws.py filter
- `## Architecture > Frontend` — hint handler, cursor tracking via TanStack cache, debounce-with-maxWait, catch-up loop
- `## Architecture > Cursor design rationale` — why DB id, why cursor in frontend
- `## Edge Cases` — burst, reconnect, DB write loss, id regression, hint-before-write timing
- `## Replacement Targets` — LogWsMessage, LogEntry linking fields, CorrelationFilter linking fields, frontend WS merge path
- `## Test Strategy` — required test types, existing tests to adapt, new coverage, tests to remove

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

**Source:** `src/hassette/web/routes/logs.py`

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

Hint coalescing uses this same clearTimeout/setTimeout pattern, extended with a maxWait cap.
