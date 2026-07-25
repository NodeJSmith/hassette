---
task_id: "T12"
title: "Split handlers-tab.test.tsx"
status: "planned"
depends_on: ["T10"]
implements: ["FR#11", "AC#3"]
---

## Summary

Split `frontend/src/components/app-detail/handlers-tab.test.tsx` (725 lines) into 4 topic-grouped test files + a shared helper file. Delete the original file.

## Target Files

- create: `frontend/src/components/app-detail/handlers-tab.rendering.test.tsx`
- create: `frontend/src/components/app-detail/handlers-tab.listener.test.tsx`
- create: `frontend/src/components/app-detail/handlers-tab.job.test.tsx`
- create: `frontend/src/components/app-detail/handlers-tab.navigation.test.tsx`
- create: `frontend/src/components/app-detail/handlers-tab.test-helpers.ts`
- delete: `frontend/src/components/app-detail/handlers-tab.test.tsx`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Read `frontend/src/components/app-detail/handlers-tab.test.tsx` fully. Split the tests into topic-grouped files:

**`handlers-tab.test-helpers.ts`** (shared, `.ts` not `.test.ts`):
- `renderHandlersTab(...)` helper function (lines 36-51)
- Shared constants and factory data

**`handlers-tab.rendering.test.tsx`** — basic rendering, empty states:
- Master list rendering
- Empty state display
- Detail placeholder

**`handlers-tab.listener.test.tsx`** — listener detail, stats, errors:
- Listener detail rendering
- Modifier chips (debounce, throttle, once, priority, immediate, duration, backpressure)
- Error banner and traceback display
- Registration source toggle
- Stats row cells (calls, failed, err%, avg, timed out, cancelled, thread leaked, suppressed, dropped, backpressure dropped)

**`handlers-tab.job.test.tsx`** — job detail, stats, Run Now:
- Job detail rendering
- Schedule chips (jitter, group)
- Trigger labels and next-run text
- Mode chip, failing badge
- Stats row cells (runs, failed, err%, avg, skipped)
- Run Now button (loading state, error handling, re-enable after request)

**`handlers-tab.navigation.test.tsx`** — selection, URL handling, callbacks:
- Selecting listeners/jobs via prop
- Clicking rows for navigation
- Instance query param preservation
- Deep-link URLs, correctUrl calls
- View-in-code callback with line number
- Execution detail without handlers

Each split file must declare its own `vi.mock()` calls at module scope — Vitest hoists these and they cannot be imported from a helper. The 4 mock declarations (execution-table, execution-detail, wouter, use-correct-url) must be duplicated in each test file.

Each split file imports `renderHandlersTab` from `./handlers-tab.test-helpers`.

Delete the original `handlers-tab.test.tsx` after all tests are distributed.

## Focus

- Count tests before splitting: `cd frontend && npx vitest run src/components/app-detail/handlers-tab.test.tsx --reporter=verbose 2>&1 | grep -c "✓"`. Do the same across split files after.
- The `vi.mock()` declarations MUST be duplicated — Vitest hoists them to the top of each file at compile time. They cannot be shared via imports.
- `renderHandlersTab` uses `renderWithAppState` (not the local `createWrapper` pattern) — no migration needed.
- The nested `describe("job detail: Run Now button")` block goes entirely into `handlers-tab.job.test.tsx`.

## Verify

- [ ] FR#11: `handlers-tab.test.tsx` no longer exists; 4 test files + shared helper exist
- [ ] AC#3: `cd frontend && npm test` passes with the same test count as before the split
