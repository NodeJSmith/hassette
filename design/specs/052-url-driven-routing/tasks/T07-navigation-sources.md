---
task_id: "T07"
title: "Update navigation sources and Vite SPA fallback"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#9", "FR#15", "AC#7", "AC#8", "AC#11"]
---

## Summary
Update all navigation sources (AppLink, sidebar, command palette) to generate URLs in the new format. Add the time window button URL sync behavior. Configure Vite's dev server for SPA fallback so direct URL access works during development.

## Prompt
Modify five files:

1. **Update `frontend/src/components/shared/app-link.tsx`**:
   - Change `instanceIndex` prop: instead of appending `/${instanceIndex}` to the path, append `?instance=${instanceIndex}` as a query parameter
   - Replace the `query` prop with an optional `handlerId` prop (string, e.g., "h-42"): when set, append `/handlers/${handlerId}` to the path
   - Update URL construction to handle the combination: `/apps/${appKey}/handlers/${handlerId}?instance=${instanceIndex}`
   - Keep the `children` prop behavior unchanged

2. **Update `frontend/src/components/layout/sidebar.tsx`**:
   - Change instance links (line 161): from `/apps/${manifest.app_key}/${inst.index}` to `/apps/${manifest.app_key}?instance=${inst.index}`
   - Update active-state detection (line 162): `instActive` check should match `/apps/${manifest.app_key}` with `?instance=${inst.index}` in the query string, or use a startsWith check on the path portion only

3. **Update `frontend/src/components/layout/command-palette.tsx`**:
   - Handler items (line 147): change from `/apps/${l.app_key}?focus=${l.handler_method}` to `/apps/${l.app_key}/handlers/h-${l.listener_id}`
   - Instance items (line 126): change from `/apps/${m.app_key}/${inst.index}` to `/apps/${m.app_key}?instance=${inst.index}`

4. **Update time window button behavior** — in whichever component renders the time preset selector (find via grep for `timePreset`):
   - On button click: update localStorage via `timePreset.value = newPreset`, update `urlWindowParam.value = newPreset`, AND call `qp.set({ window: newPreset === timePreset.value ? null : newPreset })`
   - On page load: read `?window=` from query params; if present, write to `urlWindowParam.value` (do NOT write to `timePreset` / localStorage)
   - This implements the "read-only override" model from the design doc

5. **Update `frontend/vite.config.ts`**:
   - Add `appType: 'spa'` to the Vite config to enable history fallback for the dev server. This ensures direct URL access (pasting a deep URL into the browser) serves `index.html` instead of 404.

## Focus
- The sidebar active-state detection for instances is tricky — the current check uses path matching (`location === instPath || location.startsWith(instPath + "/")`). With query params, the path is `/apps/${appKey}` for all instances; the instance is in the query string. Consider checking `location.startsWith(\`/apps/${manifest.app_key}\`) && new URLSearchParams(searchString).get("instance") === String(inst.index)` — but this requires access to `useSearch()` in the sidebar. Alternatively, simplify: instances are active when the path matches and the query string contains the right instance param.
- The time preset selector is rendered by the StatusBar component — grep for `timePreset` to find the exact file and component
- `command-palette.tsx` only indexes listeners (not jobs) via `buildHandlerItems` — this is a pre-existing limitation, not something to fix in this task
- The Vite `appType: 'spa'` setting may conflict with the existing proxy configuration — test that `/api` and `/api/ws` proxies still work after the change

## Verify
- [ ] FR#9: Clicking the time preset button updates both the URL `?window=` param and the persisted global preference
- [ ] FR#15: Sidebar instance links, command palette handler items, and AppLink all generate URLs in the new format
- [ ] AC#7: Bookmarking `/handlers?window=24h` and opening later shows 24h data; navigating to `/apps` (no window param) shows the persisted global preference
- [ ] AC#8: Clicking the time preset button on any page updates both the URL and the persisted global preference
- [ ] AC#11: All navigation sources produce URLs in the new format
