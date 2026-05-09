---
task_id: "T02"
title: "Expand route definitions and refactor AppDetailPage for tab routing"
status: "done"
depends_on: ["T01"]
implements: ["FR#1", "FR#3", "FR#11", "AC#1", "AC#5", "AC#12"]
---

## Summary
Expand the wouter route definitions in `app.tsx` to include tab-specific paths and handler deep-link paths. Refactor `AppDetailPage` to derive the active tab from the URL path instead of a signal, switch instance selection from path segment to query parameter, and convert tab buttons from signal-mutating buttons to `<Link>` elements. The component stays mounted across tab switches (single-component mounting model).

## Prompt
Modify two files:

1. **Update `frontend/src/app.tsx`** — replace the existing route definitions (lines 113-123) with the expanded route table from the design doc "Architecture > Route Definition Order":
   - `/apps/:key/handlers/:handlerId` — AppDetailPage with tab="handlers" and handlerId param
   - `/apps/:key/handlers` — AppDetailPage with tab="handlers"
   - `/apps/:key/code` — AppDetailPage with tab="code"
   - `/apps/:key/logs` — AppDetailPage with tab="logs"
   - `/apps/:key/config` — AppDetailPage with tab="config"
   - `/apps/:key` — AppDetailPage with no tab (defaults to handlers)
   - Remove the old `/apps/:key/:index` route entirely (no backward compat needed)
   - Import the `TabId` type from app-detail.tsx (export it there)
   - Each route passes `params` with `key`, optional `tab`, optional `handler` to AppDetailPage

2. **Refactor `frontend/src/pages/app-detail.tsx`**:
   - Export the `TabId` type
   - Change the `Props` interface: `params: { key: string; tab?: TabId; handler?: string }`
   - Remove the `activeTab` signal (line 136) — derive active tab from `params.tab ?? "handlers"`
   - Remove the `cameFromHandlers` signal (line 138) and the "back to handlers" button (lines 348-356)
   - Read `?instance=N` from `useQueryParams().get("instance")` instead of parsing `params.index`
   - Keep `?instance=0` explicit for multi-instance apps (do not omit as default)
   - Convert tab buttons to `<Link>` elements: each points to `/apps/${appKey}/${tabId}${instanceQs}` where `instanceQs` preserves the current `?instance=N`
   - Preserve ARIA attributes (`role="tab"`, `aria-selected`, `aria-controls`) on the Link elements
   - Update InstanceSwitcher navigation: change from `/apps/${appKey}/${idx}` to `/apps/${appKey}/${activeTab}?instance=${idx}`
   - Update MultiInstanceOverview navigation: change from `/apps/${appKey}/${idx}` to `/apps/${appKey}?instance=${idx}`
   - Remove the `focusMethod` ref and the `?focus=` query param parsing (lines 141-152) — handler deep-links replace this in T03
   - Remove the `useSearch` import (no longer needed after focusMethod removal)
   - Update breadcrumb links: multi-instance parent link goes to `/apps/${appKey}` (no instance param = parent overview)

## Focus
- The single-component mounting model is critical — all tab routes must render the same `AppDetailPage` component, not separate components. Wouter's Switch matches the route but the component reads the tab from props.
- `staleListeners` and `staleJobs` refs (lines 168-173) must survive tab switches — this only works if the component doesn't unmount
- The `codeFocusLine` signal (line 137) is still used temporarily — T03 will replace it with `?line=`
- The `HandlersTab` still receives `focusMethod` prop temporarily — pass `null` until T03 replaces it with `selectedHandler`
- ARIA tab semantics: keep `role="tab"`, `aria-selected`, `aria-controls` on the Link elements. Add `onKeyDown` handler for Space key activation (native links don't respond to Space like buttons do)
- `app-detail.tsx:200` currently uses `activeTab.value === id` — change to `activeTab === id` (plain string comparison)

## Verify
- [ ] FR#1: Navigating to `/apps/my_app/logs` shows the logs tab; `/apps/my_app/code` shows the code tab
- [ ] FR#3: Navigating to `/apps/my_app?instance=1` loads instance 1; `/apps/my_app` (no param) shows parent overview for multi-instance apps
- [ ] FR#11: Clicking a tab pushes a new browser history entry (browser back returns to previous tab)
- [ ] AC#1: Refreshing a page on the logs tab restores the logs tab (not handlers default)
- [ ] AC#5: Pressing browser back after switching from handlers to logs returns to handlers
- [ ] AC#12: `/apps/multi_app?instance=1` loads instance 1; `/apps/multi_app` shows parent overview grid
