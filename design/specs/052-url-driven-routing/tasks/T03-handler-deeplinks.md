---
task_id: "T03"
title: "Add handler deep-links and view-in-code URL param"
status: "planned"
depends_on: ["T02"]
implements: ["FR#2", "FR#13", "AC#2", "AC#4", "AC#10"]
---

## Summary
Make handler/job selection URL-driven via the `:handlerId` route parameter (format: `h-42`, `j-7`). Replace the signal-based `selectedId` in HandlersTab with route-derived selection. Replace the `focusMethod`/`?focus=` pattern with handler deep-links. Convert the "view in code" button to navigate to `/apps/:key/code?line=N` instead of mutating signals. Add `correctUrl` calls for invalid handler IDs.

## Prompt
Modify four files:

1. **Update `frontend/src/components/app-detail/handlers-tab.tsx`**:
   - Change props: replace `focusMethod: string | null` with `selectedHandler: string | null` (the raw `:handlerId` param, e.g., "h-42") and add `appKey: string` and `instanceQs: string`
   - Remove the `selectedId` signal (line 375) and `showDetail` signal (line 377)
   - Parse `selectedHandler` to extract kind and id: split on `-`, map `h` to `"listener"`, `j` to `"job"`
   - Look up the selected listener/job from the parsed kind+id
   - If `selectedHandler` is set but no matching item found (and data is loaded), call `correctUrl` to strip the handler segment from the URL with reason `"handler {id} not found"`
   - The `correctUrl` guard: only fire when `listeners` and `jobs` arrays are populated (not during loading)
   - Clicking a handler row navigates to `/apps/${appKey}/handlers/${kind}-${id}${instanceQs}` using wouter's `navigate()`
   - Update mobile back button to navigate to `/apps/${appKey}/handlers${instanceQs}` instead of toggling signal
   - Remove the `focusMethod` useEffect (lines 398-405) — selection is now URL-driven

2. **Update `frontend/src/components/app-detail/handler-list.tsx`**:
   - Change `onSelect` callback type: instead of receiving `SelectedHandlerId`, the parent handles navigation. Keep `onSelect` as `(id: SelectedHandlerId) => void` — the parent (`HandlersTab`) converts it to navigation

3. **Update `frontend/src/components/app-detail/code-tab.tsx`**:
   - Add `useQueryParams` import
   - Read `?line=` from query params instead of receiving `focusLine` as a prop
   - Parse to integer; use for the scroll-to-line and highlight behavior (existing lines 113-122)
   - Remove the `focusLine` prop from the interface

4. **Update `frontend/src/pages/app-detail.tsx`**:
   - Pass `selectedHandler={params.handler ?? null}` to HandlersTab instead of `focusMethod`
   - Pass `appKey` and `instanceQs` to HandlersTab
   - Remove the `codeFocusLine` signal — no longer needed
   - The "view in code" button: `onSwitchToCode` callback navigates to `/apps/${appKey}/code?line=${line}${instanceQs.replace('?', '&')}` instead of mutating `codeFocusLine`
   - Remove `CodeTab focusLine={codeFocusLine.value}` prop — CodeTab reads from URL now

## Focus
- Handler IDs: `h-` prefix for listeners (matching existing `handlers.tsx:37` convention), `j-` prefix for jobs
- The `correctUrl` timing guard is critical — only fire when data is loaded, not during the initial fetch. Check `listeners.length > 0 || jobs.length > 0` OR that the parent's loading state is false
- `handler-list.tsx` exports `SelectedHandlerId` type — keep this export, it's used by HandlersTab
- The mobile detail/list toggle (`showDetail` signal) needs replacement — on mobile, navigating to a handler deep-link shows the detail pane; navigating back to `/handlers` (no handler ID) shows the list. Use `selectedHandler !== null` as the mobile detail trigger
- `code-tab.tsx:117` queries `[data-testid="code-line-${focusLine}"]` — this pattern stays the same, just the source changes from prop to URL param

## Verify
- [ ] FR#2: Navigating to `/apps/my_app/handlers/h-42` selects listener 42 in the detail pane
- [ ] FR#13: Clicking "view in code" navigates to `/apps/my_app/code?line=15`; refreshing restores the scroll position and highlight
- [ ] AC#2: `/apps/motion_lights/handlers/h-42` selects listener 42 on the handlers tab
- [ ] AC#4: "View in code" navigates to code tab with `?line=` param; refresh restores scroll/highlight
- [ ] AC#10: Navigating to `/apps/my_app/handlers/h-999` (nonexistent) shows handlers tab with no selection and corrects URL
