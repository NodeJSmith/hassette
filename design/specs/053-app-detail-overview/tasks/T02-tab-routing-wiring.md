---
task_id: "T02"
title: "Add overview tab routing and wiring"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#13", "FR#14", "AC#1", "AC#8", "AC#9"]
---

## Summary
Wire the overview tab into the app detail page: add "overview" to the TabId union, change the default from "handlers" to "overview", add the route, update the tab bar order, and create a skeleton overview tab component. Also handle mobile layout. This is the structural plumbing — content sections are added in T03 and T04.

## Prompt
**1. Update TabId** in `frontend/src/pages/app-detail.tsx` line 20: Add `"overview"` to the union type.

**2. Change default tab** in `frontend/src/pages/app-detail.tsx` line 150: Change `params.tab ?? "handlers"` to `params.tab ?? "overview"`.

**3. Add route** in `frontend/src/app.tsx`: Add `<Route path="/apps/:key/overview">` following the existing tab route pattern (lines 117-119). Place it before the catch-all `/apps/:key` route.

**4. Update tab bar** in `frontend/src/pages/app-detail.tsx` around line 338: Add `<Tab id="overview" label="overview" {...tabProps} />` as the FIRST tab, before the existing handlers tab.

**5. Add render branch** in `frontend/src/pages/app-detail.tsx` around line 345: Add a conditional block for `activeTab === "overview"` that renders the new `OverviewTab` component.

**6. Create skeleton component** at `frontend/src/components/app-detail/overview-tab.tsx`: Create the component with props matching what app-detail.tsx provides: `listeners: ListenerData[]`, `jobs: JobData[]`, `appKey: string`, `instanceQs: string`. Render two placeholder sections (handler health grid, recent activity + logs) with `<EmptyState>` placeholders — T03 and T04 will fill these in. Do NOT add an error spotlight placeholder — per FR#5, this section must be absent when nothing is failing, so it cannot have a static placeholder. T03 will add it conditionally.

**7. Mobile layout**: The overview tab should use the existing `BREAKPOINT_MOBILE` from `frontend/src/hooks/use-media-query.tsx` for any responsive adjustments. Stack sections vertically on mobile (natural flow — no special layout needed beyond the default column layout).

**8. Update tests** in `frontend/src/pages/app-detail.test.tsx`:
- Line 391: The test "handlers tab is selected by default when no params.tab provided" must change to assert overview tab is selected by default
- Add a test verifying the overview tab appears first in the tab bar
- Existing tests that pass `tab: "handlers"` explicitly should continue to work unchanged

## Focus
**Reuse**: Import `EmptyState` from `../shared/empty-state` for the skeleton placeholders. Import `ListenerData`, `JobData` types from `../../api/endpoints`.

**Gap found in reverse-dependency check**: `app-detail.test.tsx` line 391 asserts `handlers` is the default tab — this test MUST be updated or it will fail.

**No regressions**: All existing routes (`/apps/:key/handlers`, `/apps/:key/handlers/h-42`, `/apps/:key/code`, etc.) must continue to work. Only the bare `/apps/:key` default changes.

**Command palette**: `command-palette.tsx` line 173 maps handler items to the `handlers` tab explicitly (`handler: "handlers"`) — this is unaffected by the default change.

## Verify
- [ ] FR#1: Navigating to `/apps/{appKey}` (no tab segment) loads the overview tab
- [ ] FR#13: Tab bar order is overview, handlers, code, logs, config
- [ ] FR#14: Overview tab sections stack vertically and fit within viewport width at 390px (no horizontal scroll, no content clipping)
- [ ] AC#1: Navigating to `/apps/{appKey}` loads the overview tab
- [ ] AC#8: Tab bar shows overview as the first tab
- [ ] AC#9: Overview sections stack vertically at 390px width with no horizontal overflow
