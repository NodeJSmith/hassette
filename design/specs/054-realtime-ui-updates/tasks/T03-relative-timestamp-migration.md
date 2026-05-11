---
task_id: "T03"
title: "Migrate all components to useRelativeTime and add tab-visibility recovery"
status: "done"
depends_on: []
implements: ["FR#4", "FR#8", "AC#4", "AC#8"]
---

## Summary
Replace all direct `formatRelativeTime` calls in components with the `useRelativeTime` hook, which subscribes to the 30-second tick signal. Several call sites are inside plain helper functions — these require architectural threading (hook called at component top level, computed string passed as parameter). Add a `visibilitychange` listener to `App.tsx` for immediate timestamp recalculation when a background tab returns to foreground.

## Prompt
Migrate every component that displays relative timestamps to use the `useRelativeTime` hook. The hook is defined at `frontend/src/hooks/use-relative-time.ts` — it calls `useSubscribe(tick)` to subscribe to the tick signal and returns `formatRelativeTime(timestamp)`.

**Per-location changes (follow exactly — hook-call constraints matter):**

1. **`frontend/src/components/app-detail/handlers-tab.tsx`**:
   - `handlerStatsCells()` (line 98) — pure function, cannot call hooks. In `ListenerDetail` component, call `const lastInvokedLabel = useRelativeTime(listener.last_invoked_at)` at the top level. Pass `lastInvokedLabel` as a parameter to `handlerStatsCells`. Update `handlerStatsCells` signature to accept the pre-computed string.
   - `jobStatsCells()` (line 115) — same pattern. In `JobDetail`, call `const lastExecutedLabel = useRelativeTime(job.last_executed_at)` and pass to `jobStatsCells`.
   - Lines 271–273 in `JobDetail` — conditional next-run / fire-at display. Call `const nextRunLabel = useRelativeTime(job.next_run)` and `const fireAtLabel = useRelativeTime(job.fire_at)` at the top of `JobDetail`. Use these computed strings in the conditional instead of inline `formatRelativeTime` calls.

2. **`frontend/src/components/app-detail/overview-tab.tsx`**:
   - Line 244 in `ActivityRow` — already a component. Replace `formatRelativeTime(entry.timestamp)` with `useRelativeTime(entry.timestamp)` at the top level.
   - Line 334 in `LogRow` — already a component. Same replacement.

3. **`frontend/src/components/app-detail/unified-handler-row.tsx`** (lines 64, 67):
   - Already a component. Call `useRelativeTime` at the top level for `next_run` and `fire_at` timestamps. Replace the inline `formatRelativeTime` calls with the hook results.

4. **`frontend/src/pages/apps.tsx`** (lines 159, 172):
   - Row rendering is inline in a `.map()` callback. Extract an `AppRow` component that receives the app data and calls `useRelativeTime(app.last_error_ts)` and `useRelativeTime(app.last_activity_ts)` at its top level. Move the row JSX into this component.

5. **`frontend/src/pages/handlers.tsx`** (line 79):
   - `formatNextRunValue()` is a data-mapping helper. The `UnifiedRow` type already has `next_run_ts: number | null`. Stop pre-computing the string in `jobToRow()` — leave `next_run_ts` as the raw timestamp. In the `UnifiedHandlerRow` component (which already receives row data), call `useRelativeTime(row.next_run_ts)` to render the relative time.

6. **`frontend/src/pages/diagnostics.tsx`** (line 111):
   - Currently uses a `tick` prop threading workaround (`void _tick`). Remove the `tick` prop from `DiagServiceRow`. Call `useRelativeTime(service.retry_at)` at the top of `DiagServiceRow` instead. Remove the `tick.value` read from the parent `DiagnosticsPage`.

7. **`frontend/src/components/shared/log-table.tsx`** (line 418):
   - If the row is rendered inside a component, call `useRelativeTime` at its top level. If the row is inline in a map, extract a row component.

**Tab visibility recovery in `frontend/src/App.tsx`:**
In the existing `useEffect` that creates the `setInterval` for `state.tick` (around lines 34–36), add a `visibilitychange` event listener:
```typescript
const onVisible = () => { if (!document.hidden) state.tick.value++; };
document.addEventListener("visibilitychange", onVisible);
```
Add `document.removeEventListener("visibilitychange", onVisible)` to the cleanup alongside `clearInterval`.

**After all changes**, remove unused `formatRelativeTime` imports from migrated files. The function itself stays in `utils/format.ts` (it's used by `useRelativeTime` internally and may be used in tests).

**Tests:**
- Add a test for `useRelativeTime` at `frontend/src/hooks/use-relative-time.test.ts`: render the hook with a timestamp, increment `state.tick`, verify the returned string updates.
- Update `frontend/src/app.test.tsx` if it tests the tick interval — verify `visibilitychange` triggers an immediate tick.

## Focus
- The key constraint is hooks rules: `useRelativeTime` CANNOT be called inside `map()` callbacks, plain functions, or conditional blocks. Every call must be at the top level of a function component.
- `useRelativeTime(null)` returns `""` — safe for optional timestamps.
- When extracting `AppRow` from `apps.tsx`, keep it in the same file (not a new component file) since it's only used here.
- `diagnostics.tsx` currently imports `tick` from `useAppState` and passes it as a prop. After migration, the `tick` prop and the `useAppState` destructuring of `tick` can be removed from the parent.
- Run `cd frontend && npx vitest run` after changes to verify all existing tests pass plus new ones.

## Verify
- [ ] FR#4: Every relative timestamp in the UI updates on every tick increment — no `formatRelativeTime` calls remain in component render paths (only inside `useRelativeTime` hook)
- [ ] FR#8: A `visibilitychange` event when the document becomes visible immediately increments `state.tick`, causing all visible relative timestamps to recalculate
- [ ] AC#4: `useRelativeTime` test confirms that incrementing `state.tick` produces an updated string from the hook
- [ ] AC#8: `visibilitychange` test confirms `state.tick` increments immediately on visibility change (not waiting up to 30 seconds)
