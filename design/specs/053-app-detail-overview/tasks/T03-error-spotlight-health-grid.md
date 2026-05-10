---
task_id: "T03"
title: "Build error spotlight and handler health grid"
status: "done"
depends_on: ["T02"]
implements: ["FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "FR#8", "AC#2", "AC#3", "AC#4"]
---

## Summary
Implement the error spotlight and handler health grid sections of the overview tab. The error spotlight surfaces failing handlers/jobs with error details and links to handler detail. The handler health grid shows all handlers/jobs in a compact status-colored view. Both sections reuse existing components heavily — no new components should be created when an existing one serves the purpose.

## Prompt
Replace the placeholder sections in `frontend/src/components/app-detail/overview-tab.tsx` (created in T02) with the real implementations.

### Error Spotlight Section

Filter the `listeners` and `jobs` props for items where `failed > 0 || timed_out > 0`. If none are failing, do NOT render this section at all (FR#5).

For each failing item (up to 3 expanded):
- **Reuse** `StatusShape` from `../shared/status-shape` for the status indicator
- **Reuse** `handlerKindLabel` from `../../utils/status` to get the kind label ("state change", "interval", "after", "cron")
- **Reuse** `statusToKind` from `../../utils/status` to determine the StatusShape kind
- Show handler/job name (monospace), error type, and error message (truncated)
- **Reuse** `ErrorBanner` from `../shared/error-banner` if showing traceback, OR keep it compact with just error_type + error_message inline (no traceback in the spotlight — that's in handler detail)
- Link each entry to `/apps/${appKey}/handlers/${prefix}-${id}${instanceQs}` where prefix is "h" for listeners, "j" for jobs

If more than 3 items are failing, show a "show N more" button that expands the remaining entries. Use a local signal (`useSignal(false)`) for the expanded state.

### Handler Health Grid Section

Show ALL handlers and jobs in a compact list. This section is always rendered (even when everything is healthy).

**Reuse** the data transformation from `buildItems()` in `frontend/src/components/app-detail/handler-list.tsx` — import `buildItems` and the `UnifiedItem` type rather than recreating the listener/job → unified item conversion. If `buildItems` is not currently exported, export it.

Sort: failing items first, then by most recent activity (use `total_invocations`/`total_executions` as proxy, or `last_invoked_at`/`last_executed_at` if available).

Each row: `StatusShape` + kind badge (reuse the chip pattern from `UnifiedHandlerRow`) + handler name (monospace) + run count. Each row links to `/apps/${appKey}/handlers/${prefix}-${id}${instanceQs}`.

**Do NOT duplicate `UnifiedHandlerRow`**. If the existing row component can be used with a `compact` prop or a simpler variant, prefer that. If the existing component is too specific to the handlers tab's interactive selection behavior, create a minimal read-only variant that delegates to the same data model.

### CSS

Add CSS classes to `frontend/src/global.css` for the overview tab sections. Use existing design tokens — no raw hex values. Follow the naming convention: `ht-overview-*` with BEM structure.

### Tests

Add unit tests to `frontend/src/components/app-detail/overview-tab.test.tsx`:
- Error spotlight renders when handlers have failures
- Error spotlight is absent when no failures
- Error spotlight shows max 3 expanded, with "show N more" for excess
- Error spotlight entries link to the handlers tab with correct handler ID
- Handler health grid renders all handlers and jobs
- Handler health grid orders failing items first
- Handler health grid entries link to the handlers tab

Use the existing test patterns from `handlers-tab.test.tsx` and `handler-list.test.tsx` — import `createHassetteStub()` or whichever mock strategy those tests use.

## Focus
**Critical reuse points:**
- `buildItems()` from `handler-list.tsx` — DO NOT rewrite the listener/job → unified item conversion
- `StatusShape` — already handles ok/warn/err/mute with shape+color
- `statusToKind` and `handlerKindLabel` — already map statuses to display values
- `ErrorBanner` — already renders error type + message + optional traceback
- `EmptyState` — for the "no handlers registered" case

**Pattern reference**: Look at how `HandlerList` in `handler-list.tsx` renders items — the overview health grid is a read-only, compact version of the same data.

**Gotcha**: The `UnifiedHandlerRow` component in `unified-handler-row.tsx` handles click/selection state for the handlers tab's master-detail pattern. The health grid doesn't need selection — it links directly. Don't import selection-related props.

## Verify
- [ ] FR#2: Error spotlight section lists handlers and jobs with failures or timeouts in the current time window
- [ ] FR#3: Error spotlight shows up to 3 expanded entries with "show N more" for remaining
- [ ] FR#4: Each error spotlight entry links to the handlers tab with that handler/job pre-selected
- [ ] FR#5: Error spotlight section is absent when no handlers or jobs are failing
- [ ] FR#6: Handler health grid shows all handlers and jobs with status, run count, and last error info
- [ ] FR#7: Handler health grid orders failing items first
- [ ] FR#8: Each handler health grid entry links to the handlers tab with the handler/job pre-selected
- [ ] AC#2: Failing handlers visible in error spotlight with error details and links
- [ ] AC#3: Error spotlight not rendered when no failures
- [ ] AC#4: All handlers/jobs visible in health grid with status indicators and links
