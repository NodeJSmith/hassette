---
task_id: "T02"
title: "Migrate all signal consumers and tests to Zustand"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "FR#4", "FR#5", "FR#9", "FR#11", "AC#2", "AC#5"]
---

## Summary

Migrate every signal consumer to the Zustand store created in T01, rewrite the test infrastructure for Zustand, and delete the old state layer. This is the bulk of Phase 1 — it converts ~20 global signal consumers, rewrites the WebSocket handler, converts 3 `useSignalEffect` files, fixes stale-closure sites, rewrites ~10 test files, and removes `@preact/signals`. After this task, the app runs on Zustand under Preact with a green test suite.

This task is large in file count but atomic — the test suite can only be green once ALL consumers are migrated, because `renderWithAppState` can only serve one state paradigm at a time.

## Target Files

- modify: `frontend/src/hooks/use-websocket.ts`
- modify: `frontend/src/hooks/use-query-invalidator.ts`
- modify: `frontend/src/components/shared/log-table/use-log-data.ts`
- modify: `frontend/src/components/shared/log-table/use-log-table.tsx`
- modify: `frontend/src/hooks/use-telemetry-health.ts`
- modify: `frontend/src/app.tsx`
- modify: `frontend/src/pages/apps.tsx`
- modify: `frontend/src/pages/handlers.tsx`
- modify: `frontend/src/pages/diagnostics.tsx`
- modify: `frontend/src/pages/app-detail.tsx`
- modify: `frontend/src/pages/logs.tsx`
- modify: `frontend/src/hooks/use-scoped-query.ts`
- modify: `frontend/src/hooks/use-relative-time.ts`
- modify: `frontend/src/hooks/use-sidebar-hidden.ts`
- modify: `frontend/src/hooks/use-async-action.ts`
- modify: `frontend/src/components/layout/sidebar.tsx`
- modify: `frontend/src/components/layout/status-bar.tsx`
- modify: `frontend/src/components/layout/time-preset-selector.tsx`
- modify: `frontend/src/components/layout/alert-banner.tsx`
- modify: `frontend/src/components/shared/theme-toggle.tsx`
- modify: `frontend/src/components/shared/system-health.tsx`
- modify: `frontend/src/components/shared/show-more-button.tsx`
- modify: `frontend/src/components/shared/log-table/use-log-filters.ts`
- modify: `frontend/src/components/app-detail/overview-tab.tsx`
- modify: `frontend/src/components/app-detail/recent-activity-section.tsx`
- modify: `frontend/src/components/app-detail/listener-detail.tsx`
- modify: `frontend/src/components/app-detail/job-detail.tsx`
- modify: `frontend/src/test/render-helpers.tsx`
- modify: `frontend/src/test/query-test-utils.tsx`
- modify: `frontend/src/hooks/use-websocket.test.ts`
- modify: `frontend/src/hooks/use-scoped-query.test.ts`
- modify: `frontend/src/hooks/use-telemetry-health.test.ts`
- modify: `frontend/src/hooks/use-relative-time.test.ts`
- modify: `frontend/src/hooks/use-breadcrumbs.test.tsx`
- modify: `frontend/src/components/app-detail/unified-handler-row.test.tsx`
- modify: `frontend/src/components/shared/log-table/use-log-table.test.tsx`
- modify: `frontend/src/components/shared/log-table/use-log-data.test.ts`
- modify: `frontend/package.json`
- delete: `frontend/src/state/create-app-state.ts`
- delete: `frontend/src/state/create-app-state.test.ts`
- delete: `frontend/src/state/context.ts`
- delete: `frontend/src/hooks/use-subscribe.ts`
- read: `frontend/src/state/store.ts`
- read: `design/specs/020-frontend-foundation-migration/design.md`

## Prompt

Migrate all signal consumers to the Zustand store and delete the old state layer. This task touches ~40 files. Work in this order:

### 1. Rewrite test infrastructure

**`src/test/render-helpers.tsx`:** Rewrite `renderWithAppState` to wrap components in `QueryClientProvider` only — Zustand doesn't need a context provider. Replace `stateOverrides` with `storeOverrides` that calls `useAppStore.setState(overrides)` before render.

**`src/test/query-test-utils.tsx`:** Replace `createAppState()` call with Zustand store seeding.

**Add afterEach hook** to `src/test-setup.ts` or a shared test utility:
```typescript
afterEach(() => useAppStore.setState({ ...initialState(), logBuffer: new RingBuffer(LOG_BUFFER_CAPACITY) }));
```
Note: plain `setState(initialState)` is insufficient — it reuses the same mutable RingBuffer instance.

### 2. Migrate structural-rewrite files (complex)

These files use Preact-specific reactive primitives that have no 1:1 Zustand equivalent:

**`use-websocket.ts`:** Replace `batch()` calls with Zustand actions via `useAppStore.getState()`. The `connected` case calls `handleWsConnected(data, isReconnect)` — pass `isReconnect` from the existing `hasConnectedRef.current` guard. Keep `queryClient.invalidateQueries()` outside the composite action, gated by the reconnect check.

**`use-query-invalidator.ts`:** Change signature from `(signal: ReadonlySignal<T>, ...)` to `(value: T, ...)`. Replace `useSignalEffect(() => { const value = signal.value; ...})` with `useEffect(() => {...}, [value])`. Drop the internal `Object.is`/`peek()` staleness guard. Update all 8 call sites across 6 files (`pages/apps.tsx:135`, `pages/handlers.tsx:63,68`, `pages/app-detail.tsx:134,139`, `components/app-detail/job-detail.tsx:114`, `components/app-detail/listener-detail.tsx:86`, `components/app-detail/recent-activity-section.tsx:127`).

**`use-log-data.ts` (`useThrottledLogVersion`):** Replace `useSignalEffect` with `useEffect` + dependency on `logVersion`. Preserve the throttle.

**`use-log-table.tsx`:** Replace `useSignalEffect` with `useEffect` + dependency on filter level. Call `useAppStore.getState().sendLogLevel(level)` imperatively (not as a selected value).

**`use-telemetry-health.ts`:** The `poll` closure runs via `setInterval` and writes 5 global fields. Use `useAppStore.getState()` at each write point — the closure is captured once and goes stale.

**`app.tsx`:** Two stale-closure sites:
- `app.tsx:106-111` — keydown handler reads `sidebarCollapsed`: use `useAppStore.getState().sidebarCollapsed`
- `app.tsx:55-58` — `setInterval` tick updater: use `useAppStore.getState().incrementTick()`
- `app.tsx:43` — replace `createAppState()` with Zustand store initialization (the `useMemo` wrapping `createAppState` is no longer needed)

### 3. Migrate global signal consumers (mechanical)

For each of the ~20 files using `useAppState()`: replace `const state = useAppState()` with individual `useAppStore(s => s.field)` calls — one per field read. Delete all `useSubscribe()` calls (13 call sites across 12 files). See design doc Architecture > Phase 1 > "Global signal consumer migration" for the full rule.

### 4. Rewrite test files that construct createAppState()

9 test files directly construct `createAppState()`. Rewrite each to seed the Zustand store via `useAppStore.setState()` or the updated `renderWithAppState` helper. See design doc Test Strategy > "Tests requiring structural rewrites" for the complete list with instance counts.

### 5. Delete old state files and remove @preact/signals

- Delete `src/state/create-app-state.ts`, `src/state/create-app-state.test.ts`, `src/state/context.ts`
- Delete `src/hooks/use-subscribe.ts`
- Run `cd frontend && npm uninstall @preact/signals`

### 6. Run tests

Run `cd frontend && npm run test` and confirm 0 failures across all 104 test files.

## Focus

- **Stale-closure audit:** Before starting, run `grep -rn "addEventListener\|setTimeout\|setInterval" --include='*.ts' --include='*.tsx' src/ | grep -B2 -A2 '\.value'` in `frontend/` to find ALL stale-closure sites. The known list is in the design doc (Architecture > Phase 1 > Stale-closure rule) but the grep may surface additional sites.
- **useQueryInvalidator call sites:** 8 calls across 6 files. After changing the signature from `(signal, ...)` to `(value, ...)`, each call site needs to pass the selected Zustand value instead of the signal.
- **Behavioral invariants:** Debounced WS-triggered cache invalidation must remain independent from immediate reconnect invalidation (`create-app-state.ts:104-109` documents this as an INVARIANT). Log-table rendering must stay throttled during high-volume streaming.
- **sendLogLevel stability:** Components must read it imperatively (`useAppStore.getState().sendLogLevel(level)`), not select it. It changes identity on every WS state transition.
- **useSubscribe deletion:** 13 call sites. Each `useSubscribe(signal)` call is simply deleted — with Zustand selectors, components re-render automatically.
- **show-more-button.tsx** imports `@preact/signals` but only for a type (`ReadonlySignal`). Replace with the Zustand value type.

## Verify

- [ ] FR#3: All ~20 files that previously used `useAppState()` now use individual `useAppStore(s => s.field)` selectors. No file uses multi-field object selectors.
- [ ] FR#4: `use-websocket.ts` uses Zustand actions via `useAppStore.getState()`. `batch()` calls are replaced. `handleWsConnected` is called with the `isReconnect` flag.
- [ ] FR#5: `src/state/context.ts` is deleted. No file imports `AppStateContext` or `useAppState`.
- [ ] FR#9: `renderWithAppState` in `src/test/render-helpers.tsx` wraps in `QueryClientProvider` only and seeds state via `useAppStore.setState()`. The afterEach hook reconstructs a fresh `RingBuffer`.
- [ ] FR#11: `logBuffer` is stored as a plain field in the Zustand store. `sendLogLevel` is read imperatively at point of use. Log subscription wiring uses `setSendLogLevel`.
- [ ] AC#2: `cd frontend && npm run test` reports 0 failures across all 104 test files.
- [ ] AC#5: `grep -rn '@preact/signals' frontend/src/ --include='*.ts' --include='*.tsx'` returns no results.
