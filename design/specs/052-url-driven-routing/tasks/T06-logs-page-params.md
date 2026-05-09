---
task_id: "T06"
title: "Wire query params into LogTable and LogsPage"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#6", "FR#7", "AC#3"]
---

## Summary
Replace the signal-based filter state in `LogTable` with URL query parameters. The LogTable is used in two contexts: the global logs page (`/logs`) and the app detail logs tab (`/apps/:key/logs`). In both contexts, filter state (level, tier, app, search, sort, dir) comes from query params. The global page additionally supports tier and app filters.

## Prompt
Modify two files:

1. **Update `frontend/src/components/shared/log-table.tsx`**:
   - Import `useQueryParams` from `../../hooks/use-query-params`
   - Replace the following signal-based state with query param reads:
     - `minLevel` signal (line 86) → `qp.get("level") ?? "INFO"`
     - `tierFilter` signal (line 88) → `qp.get("tier") ?? (appKey ? "all" : "app")`
     - `appFilter` signal (line 87) → `qp.get("app") ?? ""`
     - `search` signal (line 89) → `qp.get("search") ?? ""`
     - `sortConfig` signal (line 91) → `{ column: qp.get("sort") ?? "timestamp", asc: qp.get("dir") === "asc" }` (default dir is "desc" for timestamp sort, "asc" for others — but since default is omitted, absent dir means use the sort column's natural default)
   - Update the level dropdown `onChange`: call `qp.set({ level: newLevel === "INFO" ? null : newLevel })`
   - Update TierToolbar callbacks to write to query params
   - Update search input to write to query params
   - Update `handleSort` to write `sort` and `dir` query params
   - Update `handleResume` to reset sort to timestamp (clear sort/dir params)
   - Keep `expandedRows` and `truncatedRows` as local signals — these are UI-only state, not URL state
   - Keep `initialEntries` as a local signal — this is fetched data, not view state
   - The WS subscription update (`updateLogSubscription`) should still fire when level changes — read the level from the query param
   - Default values to omit: level="INFO", tier="app" (global) / "all" (app-scoped), app="", search="", sort="timestamp", dir="desc"

2. **Update `frontend/src/pages/logs.tsx`** — no structural changes needed; LogTable reads query params directly. Verify the page renders correctly with the new behavior.

## Focus
- LogTable has two modes determined by the `appKey` prop: global (no appKey) and app-scoped (appKey set). The tier and app filters only appear in global mode, but the query params should still work in both modes
- The `sortConfig` default direction is `false` (desc) for timestamp, which is the natural log order. When sort is absent from URL, default to `{ column: "timestamp", asc: false }`
- The live-pause behavior (`livePaused = sortConfig.column !== "timestamp"`) must still work — it reads from the derived sort state, not the signal
- `updateLogSubscription` at line 98 fires on mount — it should read the effective level from query params
- The `recheckTruncation` callback and ResizeObserver logic (lines 180-234) are unaffected — they deal with DOM measurement, not filter state
- When navigating between `/apps/foo/logs` and `/apps/bar/logs`, the LogTable component may stay mounted if AppDetailPage doesn't unmount (single-component model). Query params change naturally with the URL, so filter state resets correctly without needing a `key=` prop

## Verify
- [ ] FR#6: Log level, tier filter, app filter, search text, sort column, and sort direction on the global logs page are determined by query parameters
- [ ] FR#7: Log level, search text, sort column, and sort direction on the app detail logs tab are determined by query parameters
- [ ] AC#3: Navigating to `/apps/motion_lights/logs?level=ERROR&search=timeout` shows the logs tab filtered to ERROR level with "timeout" search
