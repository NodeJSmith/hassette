---
task_id: "T08"
title: "Migrate log data fetching to useQuery"
status: "done"
depends_on: ["T01", "T03"]
implements: ["FR#1"]
---

## Summary

Migrate `use-log-data.ts` from a hand-rolled REST fetch + `reconnectVersion` dependency to `useQuery`. This is the most complex single-file migration: the hook merges a REST initial batch with live WebSocket log entries using a timestamp watermark. The REST fetch becomes a `useQuery` call, the WS merge moves from `computed()` signals to `useMemo`, and the return type changes from signals to plain values. All downstream consumers and their tests are updated.

## Prompt

### 1. Rewrite `frontend/src/components/shared/log-table/use-log-data.ts`

Read the full file (78 lines). The current implementation:
- Lines 25-33: reads `logs` and `reconnectVersion` from `useAppState()`
- Lines 39-54: `useEffect` calls `getRecentLogs()`, stores in `initialEntries` signal
- Lines 61-74: `computed()` signals merge REST + WS data with watermark dedup

Replace with:

```typescript
export function useLogData({ appKey, executionId }: UseLogDataOptions): UseLogDataResult {
  const { logs } = useAppState();

  // REST initial batch via useQuery
  const { data: restData, isPending: loading } = useQuery({
    queryKey: ["recent-logs", appKey, executionId],
    queryFn: () => getRecentLogs(/* pass appKey/executionId as needed */),
  });

  // Force re-render on WS updates
  useSubscribe(logs.version);

  // Merge REST + WS via useMemo
  const restEntries = restData ?? [];

  const allEntries = useMemo(() => {
    if (!restData) return [];
    // Set watermark from REST data
    const watermark = restData.length > 0 ? Math.max(...restData.map(e => e.timestamp)) : 0;
    // Filter WS entries newer than watermark, scoped by appKey/executionId
    const wsEntries = logs.toArray().filter(e => {
      if (e.timestamp <= watermark) return false;
      if (appKey && !e.logger_name.includes(appKey)) return false;
      if (executionId && e.execution_id !== executionId) return false;
      return true;
    });
    return [...restData, ...wsEntries];
  }, [restData, logs.version.value, appKey, executionId]);

  return { allEntries, restEntries, loading };
}
```

Read the existing implementation carefully — the watermark logic, scope filtering, and WS entry format may differ from the sketch above. Replicate the exact filtering behavior.

Update the return type interface:
```typescript
interface UseLogDataResult {
  allEntries: LogEntry[];     // was ReadonlySignal<LogEntry[]>
  restEntries: LogEntry[];    // was ReadonlySignal<LogEntry[]>
  loading: boolean;           // was ReadonlySignal<boolean>
}
```

Remove:
- The `reconnectVersion` dependency — global reconnect invalidation (T03) handles refetch
- The `initialEntries` signal and manual `useEffect` fetch
- The `computed()` signal wrappers
- The `cancelled` flag pattern

### 2. Update `frontend/src/components/shared/log-table/use-log-table.tsx`

Read the full file. At line 84-87, it destructures `{ allEntries, restEntries, loading }` from `useLogData`. After the type change:
- `allEntries` and `restEntries` are now `LogEntry[]` instead of `ReadonlySignal<LogEntry[]>`
- `loading` is now `boolean` instead of `ReadonlySignal<boolean>`

Find all `.value` reads on these variables throughout the file and remove them. For example, if the code reads `allEntries.value`, change to just `allEntries`.

### 3. Update `frontend/src/components/shared/log-table/use-log-filters.ts`

Read the full file (262 lines). This file is the most complex restructuring in the migration — it uses Preact `computed()` signals internally.

**Parameter type change** (lines 11-12):
```typescript
// Before
allEntries: ReadonlySignal<LogEntry[]>;
restEntries: ReadonlySignal<LogEntry[]>;

// After
allEntries: LogEntry[];
restEntries: LogEntry[];
```

**Internal restructuring required**: The `filtered` computed signal (line 123) reads `restEntries.value` and `allEntries.value`. After migration, these are plain arrays — `computed()` cannot track non-signal values reactively. The restructuring:

1. **`filterState` (line 94)** — KEEP as `computed`. It only reads from local signals (`localLevel`, `localTier`, etc.) and `qpRef`. No dependency on `allEntries`/`restEntries`.

2. **`livePaused` (line 121)** — KEEP as `computed`. It only reads from `filterState.value`.

3. **`filtered` (line 123)** — CHANGE from `computed` to `useMemo`. The `computed` currently reads from both signals (`filterState.value`, `livePaused.value`) and the entry parameters (`restEntries.value`, `allEntries.value`). After migration:
   ```typescript
   // Read signal values in the hook body (triggers re-renders on signal changes)
   const paused = livePaused.value;
   const { level, tier, app, search, func, sort } = filterState.value;
   const source = paused ? restEntries : allEntries;

   const filtered = useMemo(() => {
     let result = source;
     // ... existing filter chain (level, tier, app, search, func) ...
     return sortEntries(result, sort.column, sort.asc);
   }, [source, level, tier, app, search, func, sort.column, sort.asc]);
   ```

4. **Return type change** — `filtered` changes from `ReadonlySignal<LogEntry[]>` to `LogEntry[]` in `UseLogFiltersResult`. Consumers that read `filtered.value` change to just `filtered`.

The `filterState` and `livePaused` return values can stay as `ReadonlySignal` — they only depend on internal signals. Update the `UseLogFiltersResult` interface for `filtered` only.

### 4. Rewrite `frontend/src/components/shared/log-table/use-log-data.test.ts`

Read the existing file. Rewrite with MSW-backed tests. Scenarios from design doc:
- REST fetch fires on mount via `useQuery` (MSW handler controls response)
- WS entries newer than the REST watermark are included in `allEntries`
- WS entries at or before the watermark are excluded (dedup)
- WS entries filtered by `appKey` when provided
- WS entries filtered by `executionId` when provided
- `restEntries` contains only REST data (no WS merge)
- Global reconnect invalidation triggers a refetch (remove `reconnectVersion`-specific tests)
- Error from REST fetch is surfaced

### 5. Update `frontend/src/components/shared/log-table/use-log-table.test.tsx`

Read the full file. At lines 23-31, it mocks `useLogData` returning:
```typescript
allEntries: signal([]),
restEntries: signal([]),
```

Change the mock to return plain arrays and a plain boolean for `loading`:
```typescript
allEntries: [],
restEntries: [],
loading: false,
```

Update all mock value mutations — any `allEntries.value = [...]` patterns need to change to re-render with new mock return values.

### 6. Update `frontend/src/components/shared/log-table/use-log-filters.test.ts`

Read the full file. At lines 40-42 and 48-50, it creates `signal<LogEntry[]>(entries)` for `allEntries` and `restEntries`. Change to plain arrays:
```typescript
// Before
const allEntries = signal<LogEntry[]>(entries);
const restEntries = signal<LogEntry[]>(rest);

// After — plain arrays, re-render to update
```

The test mutates signal values with `.value = [...]` (e.g., lines 339-340). These patterns need to change — re-render the hook with new array values instead of mutating signals. Use `renderHook`'s `rerender` function with updated props/parameters.

## Focus

- This is the most complex migration. The WS merge logic is the critical invariant — entries must be deduped by watermark and filtered by scope. Read the existing `computed()` signals carefully.
- The `getRecentLogs` function — read `frontend/src/api/endpoints.ts` to see its exact signature and what parameters it accepts.
- The `logs` object from AppState is a `LogStore` (custom ring buffer with a `.version` signal). `useSubscribe(logs.version)` forces re-renders when WS entries arrive.
- The `useMemo` dependency array must include `logs.version.value` to recompute when WS entries change. But `logs.version.value` changes on every WS message — this is intentional (same frequency as the current `computed()` signal).
- `use-log-filters.ts` is 263 lines and heavily uses signals internally. Changing its parameter types from signals to plain values may require significant refactoring of its internal computation. Read the full file before planning changes. If it uses `computed()` internally over `allEntries.value`, those computations need to change to `useMemo` or inline.
- After this task, `reconnectVersion` has zero consumers. The signal and its increment are removed in T09.

## Verify

- [ ] FR#1: `use-log-data.ts` uses `useQuery` instead of hand-rolled fetch; no `reconnectVersion` dependency — verified by code review and grep
