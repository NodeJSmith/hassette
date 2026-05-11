---
task_id: "T02"
title: "Create useFilteredSignalRefetch hook with signal-effect subscription"
status: "planned"
depends_on: []
implements: ["FR#5", "FR#7", "AC#5", "AC#7"]
---

## Summary
Create a shared `useFilteredSignalRefetch` hook that subscribes to Preact signals outside the render cycle (via `useSignalEffect`), applies a filter function, and triggers a debounced refetch callback only when the filter matches. This replaces the `useDebouncedEffect(() => signal.value, ...)` pattern that causes blast-radius re-renders on every WS event from any app. Define a `WS_DEBOUNCE_MAX_WAIT_MS = 1500` constant.

## Prompt
Create a new hook at `frontend/src/hooks/use-filtered-signal-refetch.ts`.

**Hook signature:**
```typescript
function useFilteredSignalRefetch<T>(
  signal: ReadonlySignal<T>,
  filterFn: (value: T) => boolean,
  refetchFn: () => void,
  delayMs: number,
  maxWaitMs: number,
): void
```

**Behavior:**
1. Subscribe to `signal` via `useSignalEffect` (from `@preact/signals`) — this runs outside the render cycle, so signal reads inside the effect do NOT trigger component re-renders
2. When the signal value changes, call `filterFn(newValue)` immediately inside the effect
3. If `filterFn` returns `false`, do nothing — no debounce timer started
4. If `filterFn` returns `true`, start a trailing debounce timer (`delayMs`). If the timer is already running, reset it (trailing edge)
5. Maintain a `maxWaitMs` guarantee: a second timer fires at `maxWaitMs` after the first matching event, even if new matching events keep resetting the trailing timer
6. When either timer fires, call `refetchFn()`
7. Clean up both timers on unmount
8. Skip initial render — don't fire on mount

**Constants:** Define `WS_DEBOUNCE_DELAY_MS = 500` and `WS_DEBOUNCE_MAX_WAIT_MS = 1500` in the same file (exported).

**Reference:** Study the existing `use-debounced-effect.ts` for debounce + max-wait timer management. The key difference is subscription mechanism: `useSignalEffect` instead of reading `.value` in a render-time `getValue()`.

Also check `use-api.ts:128` where `useSignalEffect` is already imported and used for `reconnectVersion` — follow that import pattern.

**Unit tests** at `frontend/src/hooks/use-filtered-signal-refetch.test.ts`:
1. Does not fire on mount (initial render)
2. Fires `refetchFn` after `delayMs` when `filterFn` returns `true`
3. Does NOT fire when `filterFn` returns `false` — verify `refetchFn` is never called
4. Resets trailing timer on rapid matching events
5. `maxWaitMs` guarantees firing even during sustained matching events
6. Cleans up timers on unmount (no post-unmount calls)
7. Mixed events: matching and non-matching interleaved — only matching trigger debounce

Use the same test patterns as `use-debounced-effect.test.ts` — `@testing-library/preact`, `renderHook`, `signal()` from `@preact/signals`, `vi.useFakeTimers`.

## Focus
- `useSignalEffect` is already used in `use-api.ts:128` — follow that import path (`@preact/signals`)
- The existing `useDebouncedEffect` should NOT be modified or removed — it's still used for non-WS-signal scenarios. The new hook is specifically for WS signal subscriptions.
- The `filterFn` receives the full signal value (e.g., `WsInvocationCompletedPayload[] | null`). Typical filter: `(events) => events?.some(e => e.app_key === appKey) ?? false`.
- For the apps landing page (T05), the filter will be `(events) => events !== null` (all events match).
- Run `cd frontend && npx vitest run` to verify tests pass.

## Verify
- [ ] FR#5: Hook subscribes via `useSignalEffect`, not render-time signal reads; a signal change that doesn't match the filter causes zero component re-renders
- [ ] FR#7: Debounce with `maxWaitMs` caps refetch frequency; sustained matching events at 100ms intervals produce bounded calls (at most ceil(duration / maxWaitMs))
- [ ] AC#5: Unit test confirms non-matching signal changes never call `refetchFn`
- [ ] AC#7: Unit test simulates 50 matching events in 5 seconds with `delayMs=500, maxWaitMs=1500` and verifies at most 4 refetch calls
