# Frontend WTF Check — 2026-05-22

**Scope:** `frontend/src/` — 177 files, 16,144 lines (path mode, all existing code)
**Code Review:** WARN
**Integration Review:** BLOCK (two parallel-drift type issues, low-effort fixes)
**WTF Readability:** 17 findings (5 HIGH, 8 MEDIUM, 4 LOW)

## Critical / High

### F1: Instance rows show app-level liveStatus instead of per-instance status
**Source:** Code
**File:** `pages/apps-table-row.tsx:126`

`liveStatus` comes from `appStatus.value[app.app_key]?.status` — the status of the app as a whole, not a specific instance. For multi-instance apps, the WS `app_status_changed` message carries an `index` field, but the parent strips that and passes one `liveStatus`. All instance rows show the same status regardless of which instance changed.

**Fix:** Thread the full `appStatus` entry (which has `index`) down to the row, or read per-instance status from `manifest.instances`.

### F2: Log watermark data-loss window on WS reconnect
**Source:** Code
**File:** `components/shared/log-table/use-log-data.ts:39-50`

When `reconnectVersion` triggers a re-fetch, `watermarkRef.current` is reset to `0` and the REST response updates it to the max timestamp. WS entries arriving during the fetch with timestamps between the old and new watermarks can be filtered out after the watermark updates.

**Fix:** Set `watermarkRef.current = Date.now() / 1000` immediately when the effect starts, so WS entries newer than the fetch start are accepted.

### F3: URL sort params cast without validation
**Source:** Code
**File:** `pages/handlers.tsx:31-34`

```ts
const sort: SortState<HandlerSortKey> = {
  key: (qp.get("sort") ?? "app") as HandlerSortKey,
  dir: (qp.get("dir") ?? "asc") as "asc" | "desc",
};
```

`as HandlerSortKey` accepts any string from the URL. Inconsistent with `apps.tsx` which validates the sort key. A user with `?sort=garbage` will see an incorrect active sort indicator.

**Fix:** Add a validation guard matching the `apps.tsx` pattern with a `VALID_HANDLER_SORT_KEYS` set.

### F4: ChipKind vs StatusKind parallel drift
**Source:** Integration
**Files:** `components/shared/chip.tsx:7` + `utils/status.ts:97`

`ChipKind = "ok" | "warn" | "err" | "mute"` and `StatusKind = "ok" | "warn" | "err" | "mute"` are identical types defined independently. `handler-detail-layout.tsx` imports `ChipKind`; `handler-list.tsx`, `handler-health-card.tsx`, `unified-handler-row.tsx`, and `status-shape.tsx` import `StatusKind`. A future change to one won't update the other.

**Fix:** Have `chip.tsx` import and re-export `StatusKind` as `ChipKind`, or use `StatusKind` directly everywhere.

### F5: StatsStripCell.tone vs DetailStatsCell.tone type mismatch
**Source:** Integration
**Files:** `components/shared/stats-strip.tsx:9` + `components/shared/detail-stats.tsx:8`

`StatsStripCell.tone` accepts `StatusKind` (4 values). `DetailStatsCell.tone` accepts `"err" | "warn"` (2 values). Same concept, inconsistent width.

**Fix:** Widen `DetailStatsCell.tone` to `StatusKind` and implement missing CSS classes, or document the intentional restriction.

### F6: useLogFilters duplicated branching for local vs URL mode
**Source:** WTF
**File:** `components/shared/log-table/use-log-filters.ts:161-246`

Every filter setter (`setLevel`, `setTier`, `setApp`, `setSearch`, `setFunc`, `setSort`, `resetSort`) branches on `useLocalState` — 7 duplicated code paths in 263 lines. Adding a new filter means branching in both places.

**Fix:** Abstract the storage strategy (signal vs URL) behind a common interface so setters don't need to branch.

### F7: _updateLogSubscription hand-rolled observer slot
**Source:** WTF
**File:** `state/create-app-state.ts:74,231-241`

Module-level closure variable with two exposed methods: `updateLogSubscription()` (public call) and `setUpdateLogSubscription()` (`@internal`). The `@internal` comment is the only thing preventing callers from wiring a second socket. No enforcement of one-write-only semantics.

**Fix:** Use a typed callback signal or add runtime invariant check.

### F8: useApi render-phase signal mutations
**Source:** WTF
**File:** `hooks/use-api.ts:98-115`

Writes to signals (`data.value = null`, `loading.value = true`, `error.value = null`) during the render phase with a comment saying "safe." Non-idiomatic for Preact and the comment doesn't explain what invariant makes it safe.

**Fix:** Either move mutations to an effect, or expand the comment to explain the invariant (e.g., "signals batch updates within the same microtask, so these writes are committed atomically before the next render cycle").

## Medium

### F9: No AbortController on log fetches
**Source:** Code
**File:** `components/shared/log-table/use-log-data.ts:39-50`

Uses a `cancelled` flag but doesn't cancel the in-flight `fetch`. Navigating quickly accumulates open requests. `useTelemetryHealth` correctly uses `AbortController`.

### F10: filterState computed reads non-signal ref
**Source:** Code
**File:** `components/shared/log-table/use-log-filters.ts:94-119`

`filterState` computed reads `qpRef.current.get(...)` — a plain ref, not a signal. In URL-backed mode, the computed depends on no signals, meaning `filterState` won't reactively update on URL back/forward navigation.

### F11: Immutability violation in running average calculation
**Source:** Code
**File:** `components/app-detail/recent-activity-section.tsx:39-44`

Mutates `prev` (an element of `groups`) in-place across iterations. Violates the project's immutability rule. Works because `groups` is local, but fragile.

### F12: O(n) column visibility check per row
**Source:** Code
**File:** `components/shared/log-table/log-table-row.tsx:24`

`visibleColumns.includes(id)` is O(n), called 8 times per row. With `RENDER_CAP = 500` rows = 4000 array scans per render.

**Fix:** Convert to `Set` lookup.

### F13: Stale closure in use-telemetry-health
**Source:** Code
**File:** `hooks/use-telemetry-health.ts:70-75`

`restartInterval` recreated every render, captured stale by `poll` ref. Works by accident because refs are mutable, but invisible to readers.

### F14: Raw useRef(signal()) instead of useSignal utility
**Source:** Code+WTF
**File:** `pages/apps.tsx:169`

`useRef(signal<Set<string>>(new Set())).current` — the project has a `useSignal` hook that does exactly this. Two idioms for the same pattern.

### F15: Undocumented ResizeObserver divergence
**Source:** Integration
**File:** `components/app-detail/handlers-tab.tsx:45-58`

Uses inline `ResizeObserver` instead of `useMediaQuery`. There's a valid reason (container-relative breakpoint), but no comment explaining why the shared hook wasn't used.

### F16: Inconsistent search placeholder/aria-label
**Source:** Integration
**File:** `pages/handlers.tsx:129`

`apps.tsx`: `placeholder="search apps…"`, `aria-label="Search apps"`. `handlers.tsx`: `placeholder="Search..."`, `aria-label="Search"`. Different casing, missing noun, ASCII `...` vs `…`.

### F17: Props interface naming inconsistency
**Source:** Integration
**Files:** `components/shared/empty-state.tsx`, `error-banner.tsx`

Use generic `interface Props` while siblings (`badge.tsx`, `chip.tsx`, `card.tsx`) use component-named interfaces (`BadgeProps`, etc.).

### F18: StatusKind naming suggests live status
**Source:** WTF
**File:** `components/app-detail/handler-list.tsx:19-28`

`listenerStatusKind`/`jobStatusKind` named like live-status indicators but actually reflect time-window aggregates. A handler that failed once 7 days ago shows `"err"` until the window rolls over.

### F19: "starting" status group mapping unclear
**Source:** WTF
**File:** `components/layout/sidebar-groups.ts:34-43`

`"starting"` falls to `"ok"` group via default case. Has its own priority (3) in `status-priority.ts` but isn't explicitly mapped in `getGroupKey`. Unclear if intentional.

### F20: Regex hardcodes prefix literals
**Source:** WTF
**File:** `utils/handler-ids.ts:1-4`

`HANDLER_ID_RE = /^([hj])-(\d+)$/` hardcodes `h` and `j` instead of referencing `LISTENER_PREFIX`/`JOB_PREFIX` constants.

### F21: columnFilters returned at two paths
**Source:** WTF
**File:** `components/shared/log-table/use-log-table.tsx:252-265`

`columnFilters` appears both inside `tableProps.columnFilters` and as a top-level field in the result.

### F22: Filter naming inconsistency
**Source:** WTF
**File:** `components/shared/log-table/use-log-filters.ts:113,204`

Same concept named `func` (internal), `fn` (URL param), `setFunc` (setter) across three layers.

### F23: Section divider comments in diagnostics
**Source:** WTF
**File:** `pages/diagnostics.tsx:21,71,125,163,205,283`

Horizontal rule divider comments (`// ─────────────────`) prohibited by `coding-style.md`.

### F24: Fragile signal identity coordination
**Source:** WTF
**Files:** `hooks/use-websocket.ts:141-146` + `state/create-app-state.ts:168-176`

`invocationCompleted`/`executionCompleted` signals rely on `Object.is` identity check in `useFilteredSignalRefetch`. Works because each WS message creates a new array, but the contract is invisible to callers.

## Low

### F25: response.json() cast trusts server shape
**Source:** Code
**File:** `api/client.ts:38`

No runtime validation at the HTTP boundary. Acceptable with OpenAPI-generated types but means version-skew errors surface downstream, not at the boundary.

### F26: Key collision on boot issues
**Source:** Code
**File:** `pages/diagnostics.tsx:187`

Key `${issue.severity}-${issue.label}` collides if two issues share both. Add index to key.

### F27: Incomplete focus trap in command palette
**Source:** Code
**File:** `components/layout/command-palette.tsx:128-130`

Sentinel-based focus trap doesn't handle shift-tab from first focusable element. `ConfirmDialog` implements a correct full trap.

### F28: livePaused naming misleading
**Source:** Code
**File:** `components/shared/log-table/use-log-filters.ts:121`

Named "live paused" but triggered by any non-timestamp sort, not explicit user action.

### F29: Redundant undefined check
**Source:** Code+WTF
**File:** `pages/apps.tsx:183`

`uptimeSeconds` is `Signal<number | null>` — the `!== undefined` check is dead code.

### F30-32: Orphaned exports in status.ts
**Source:** Integration
**File:** `utils/status.ts:34,46,56`

`executionStatusVariant`, `APP_STATUSES`, `errorRateToVariant`, `ERROR_RATE_CLASSES` are exported but unused in production code (only in tests).

### F33: Different clock cadences
**Source:** WTF
**File:** `pages/handlers-rows.tsx:55-57`

`isOverdue` derived from render-time `Date.now()` while `useRelativeTime` is tick-driven. Different update cadences for the same row.

### F34: ReadonlySignal type assertion
**Source:** WTF
**File:** `components/shared/log-table/use-log-data.ts:76`

Cast to `ReadonlySignal<boolean>` instead of using a typed return.

### F35: Mixed CSS class strategies in status bar
**Source:** WTF
**File:** `components/layout/status-bar.tsx:35-40`

`statusConfig` mixes CSS module classes (`styles.pulseDot`) with bare global strings (`"connecting"`, `"disconnected"`).

### F36: Dead condition on first connect
**Source:** WTF
**File:** `hooks/use-websocket.ts:34-37`

Condition to set `"connecting"` is dead on first connect (initial state is already `"connecting"`). Documented but puzzling.

### F37: reconnectVersion read outside effect
**Source:** WTF
**File:** `components/shared/log-table/use-log-data.ts:33`

`reconnectVersion.value` read at render time to include as effect dep — causes extra re-render on reconnect.

### F38: setUpdateLogSubscription stale on remount
**Source:** Code
**File:** `hooks/use-websocket.ts:157`

Set to no-op on close; briefly stale between close and reconnect on remount. Short-lived, low impact.
