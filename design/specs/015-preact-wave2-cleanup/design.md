# Design: Preact Wave 2 Cleanup

**Date:** 2026-03-22
**Status:** approved

## Problem

The Preact SPA migration (#343) left 7 post-migration rough edges: untyped API returns with `as never` casts, duplicated SVG icons across 6 files, action buttons with no error display, a fragile log buffer/version pair that requires manual coordination, stale cached invocations that never refresh, relative timestamps that freeze at render time, and dead CSS with broken/missing BEM class names. Each is individually small but collectively they create type-safety gaps, maintenance burden, and UX issues (including an invisible spinner component).

## Non-Goals

- No backend API changes
- No new npm dependencies
- No architectural refactoring beyond these 7 issues
- No new pages (new hooks and extracted components are allowed)

## Architecture

### Issues #373 + #360 — Refactor handler/job rows to useApi with proper types (merged WP)

**Files:** `handler-row.tsx`, `job-row.tsx`, `api/endpoints.ts`, `handler-invocations.tsx`, `job-executions.tsx`

**Why merged:** Both issues modify the same region of `handler-row.tsx` (lines 21-34) and `job-row.tsx` (lines 25-37). Executing them separately creates merge conflicts.

**Current state:** `handler-row.tsx` and `job-row.tsx` call `getHandlerInvocations()`/`getJobExecutions()` directly with raw `await` — they do NOT use `useApi`. A `loaded` signal caches forever after first expand. The endpoints return `unknown[]`, and components cast with `as never[]` to pass data to children.

**Proposed change:**
1. **Add `lazy` option to `useApi`:** When `lazy: true`, skip the initial `useEffect` fetch on mount. The hook returns `loading: false`, `data: null` until `refetch()` is called manually. This is needed because rows are collapsed on mount and should make zero API calls until expanded.
2. Define typed interfaces in `endpoints.ts` for `JobData`, `HandlerInvocationData`, `JobExecutionData` matching the backend Pydantic models (shapes documented in CLAUDE.md). Keep the existing local interfaces in `handler-invocations.tsx` and `job-executions.tsx` as component props — they may intentionally subset the API shape. Type the endpoint return values, then cast at the call site boundary if needed.
3. Refactor `handler-row.tsx` and `job-row.tsx` to use `useApi` with `lazy: true`. This gives: `requestIdRef` race condition protection, reconnect-auto-refetch, and proper typing. The `loaded` guard is removed — `useApi` handles fetch lifecycle. Also update `job-list.tsx` which has `as never` casts and `unknown[]` props.
4. Remove all `as never` casts from components.

**Expand/collapse behavior:** On expand, call `refetch()`. On collapse, hide the section but keep cached data. On re-expand, call `refetch()` again. `refetch()` sets `loading.value = true` but does NOT clear `data.value` — so stale data remains visible during the refetch (stale-while-revalidate). Row components should render data when `data.value` is non-null, regardless of `loading.value`, and show a subtle refresh indicator (not a full spinner) when both are truthy.

### Issue #356 — Extract shared icons module

**Files:** New `components/shared/icons.tsx`, `pages/app-detail.tsx:19-39`, `pages/logs.tsx:12-15`, `components/layout/sidebar.tsx:9-51`, `pages/apps.tsx:26-31`, `components/apps/action-buttons.tsx:11-28`

8+ SVG icons are defined inline across 6 files. Create a `components/shared/icons.tsx` module exporting named functional components. Each icon preserves its original SVG attributes — do NOT normalize to uniform stroke/fill, as sidebar icons use fill-based paths while other icons use stroke-based paths. Each gets `class="ht-icon-svg"` and its original `viewBox`.

### Issue #365 — Add error display to action buttons

**Files:** `components/apps/action-buttons.tsx`

**Correction from critique:** The code already has loading state and button disabling via a `loading` signal with `try/finally`. Only error display is missing — there is no `catch` block, so API errors are silently swallowed.

**Proposed change:** Add an `error` signal. In the existing `exec()` function, add a `catch` block that sets `error.value`. Display the error message below the buttons (inline text, not a new component — respects the non-goal of no new components). Clear `error.value` when a new action starts. Track the pending action by name and disable all buttons unconditionally while any action is in flight (prevents race conditions when WS `appStatus` events change the button set mid-flight).

### Issue #358 — Encapsulate RingBuffer + version into atomic log store

**Files:** `state/create-app-state.ts:25-28`, `hooks/use-websocket.ts:66-67`, `components/shared/log-table.tsx:33,36`

The log state is a plain object with `buffer` and `version` managed separately. `use-websocket.ts:66-67` manually pushes to the buffer then increments the version.

Create a `createLogStore()` factory that returns `{ push(entry), toArray(), version }` where `push` atomically appends to the buffer and increments the version signal. **`push()` must internally call `batch()`** so it is safe to call from any context (not just inside an existing `batch()` block). Replace the raw `logs` object in `createAppState()` with this factory.

### Issue #372 — Periodic tick for stale relative timestamps

**Files:** New `hooks/use-relative-time.ts`, `state/create-app-state.ts`, `app.tsx`, `handler-row.tsx`, `job-row.tsx`, `components/dashboard/app-card.tsx`, `components/dashboard/error-feed.tsx`

`formatRelativeTime()` computes once at render time and never updates.

**Proposed change:** Create a `useRelativeTime(timestamp)` hook that:
1. Reads a `tick` signal from `AppState` (added as `tick: signal(0)`)
2. Calls `formatRelativeTime(timestamp)` — the signal read creates a dependency
3. Returns the formatted string

Start the tick interval (every 30 seconds) in `App` via `setInterval` in a `useEffect` with `clearInterval` in the cleanup return (prevents interval leaks on HMR remount).

Replace all direct `formatRelativeTime(ts)` calls with `useRelativeTime(ts)` at the component level. This is self-documenting (the hook name explains why it re-renders) and impossible to accidentally break by removing an "unused" parameter.

**Call sites:** `handler-row.tsx`, `job-row.tsx`, `app-card.tsx`, `error-feed.tsx` (the design doc previously missed the dashboard components).

### Issue #353 — Strip dead CSS and fix missing BEM class names

**Files:** `frontend/src/global.css` (1706 lines), `components/layout/alert-banner.tsx`, `components/shared/spinner.tsx`, `components/shared/log-table.tsx`, `components/app-detail/handler-invocations.tsx`, `components/app-detail/job-executions.tsx`

Two sub-tasks:

**Dead CSS removal:** Build a class inventory from all `.tsx` files, accounting for dynamic class construction (template literals like `` `ht-badge--${variant}` `` — expand to all known variant values). Cross-reference against `global.css`. Remove rules whose selectors are not referenced. **Verify with Playwright screenshots before/after** to catch any false positives.

Known dead sections (confirmed by grep): `.ht-entity-*`, `.ht-timeline*`, `.ht-invocation*` (old htmx/Alpine UI). The total dead line count needs verification during implementation — the "~650 lines" estimate from the original analysis was unsubstantiated.

**Missing CSS definitions (user-facing bugs):**
- `ht-spinner` — no CSS rule exists. The `<Spinner />` component renders as an invisible empty div. **Add keyframe animation + styles.**
- `ht-alert-danger` — no CSS rule. Should be `ht-alert--danger` per BEM. Fix the class name in `alert-banner.tsx` and ensure the CSS rule exists.
- `ht-text-mono` — no CSS rule. Add a `font-family: monospace` utility class definition.
- `ht-alert-list` — verify if styled or unstyled.
- `ht-tag` / `ht-tag-${kind}` — used in `error-feed.tsx:18` with no CSS definition. Add tag/badge styles.

## Alternatives Considered

**Batch all into a single giant commit** — Rejected. Each issue gets its own commit for clean history and easy revert.

**Type API returns via OpenAPI codegen** — Over-engineering for 3 small interfaces.

**Pass tick.value as unused parameter to formatRelativeTime** — Rejected after critique. A dedicated `useRelativeTime` hook is self-documenting and won't be accidentally deleted.

**Keep #373 and #360 as separate WPs** — Rejected after critique. They modify the same 5-line region of the same files.

## Open Questions

None — all issues are well-scoped with clear solutions.

## Impact

| WP | Files changed | New files |
|----|--------------|-----------|
| #373+#360 | endpoints.ts, handler-row.tsx, job-row.tsx, job-list.tsx, handler-invocations.tsx, job-executions.tsx, use-api.ts | use-api.ts (lazy option) |
| #356 | app-detail.tsx, logs.tsx, sidebar.tsx, apps.tsx, action-buttons.tsx, dashboard.tsx | icons.tsx |
| #365 | action-buttons.tsx | — |
| #358 | create-app-state.ts, use-websocket.ts, log-table.tsx | — |
| #372 | create-app-state.ts, app.tsx, handler-row.tsx, job-row.tsx, app-card.tsx, error-feed.tsx | use-relative-time.ts |
| #353 | global.css, alert-banner.tsx, spinner.tsx, log-table.tsx, handler-invocations.tsx, job-executions.tsx | — |

Total: ~20 files modified, 2 new files. Estimated ~350-450 LOC changed.

## Execution Order

1. **#373+#360** — Add `lazy` option to useApi, type APIs, refactor rows (foundation for other WPs touching these files)
2. **#356** — Extract icons (independent; must precede #365 since both touch action-buttons.tsx)
3. **#365** — Action button error display (after #356 completes on action-buttons.tsx)
4. **#358** — Log store encapsulation (touches create-app-state.ts before #372)
5. **#372** — Timestamp tick (depends on #358 being done since both touch create-app-state.ts; also touches handler-row/job-row after #373+#360 refactor)
6. **#353** — CSS cleanup (last — touches the most files and benefits from all other changes being stable)
