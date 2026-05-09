---
task_id: "T05"
title: "Wire query params into HandlersPage"
status: "planned"
depends_on: ["T01"]
implements: ["FR#5", "AC#6"]
---

## Summary
Replace the `useState`-based tier filter, app filter, sort, and search state on the handlers page with URL query parameters via `useQueryParams`. Changes replace the current history entry. Default values are omitted from the URL.

## Prompt
Modify one file:

**Update `frontend/src/pages/handlers.tsx`**:
- Import `useQueryParams` from `../hooks/use-query-params`
- Replace `useState<TierFilter>("app")` with `qp.get("tier") ?? "app"` (cast to TierFilter)
- Replace `useState("")` for selectedApp with `qp.get("app") ?? ""`
- Replace `useState("")` for search with `qp.get("search") ?? ""`
- Replace `useState<SortState<SortKey>>({ key: "app", dir: "asc" })` with reads from `sort` and `dir` params, defaulting to `"app"` and `"asc"`
- When any of these change, call `qp.set()` with the updated values, omitting defaults:
  - `tier: "app"` → omit, `app: ""` → omit, `search: ""` → omit, `sort: "app"` → omit, `dir: "asc"` → omit
- TierToolbar callbacks: `onTierChange` → `qp.set({ tier: v === "app" ? null : v })`
- App dropdown: `onAppChange` → `qp.set({ app: v || null })`
- Search input: `onSearchChange` → `qp.set({ search: v || null })`
- SortHeader: `onSort` → `qp.set({ sort: s.key === "app" ? null : s.key, dir: s.dir === "asc" ? null : s.dir })`
- The handler row links (mobile card href at line 257, AppLink at line 310): change from `?focus=${handler_method}` to direct handler deep-link `/apps/${row.app_key}/handlers/h-${row.id.slice(2)}` for handlers and `/apps/${row.app_key}/handlers/j-${row.id.slice(2)}` for jobs. Use the numeric ID from the UnifiedRow's `id` field (strip the `h-`/`j-` prefix that's already there).

## Focus
- Default values for handlers page: tier="app", app="", sort="app", dir="asc", search="" — omit all from URL
- The UnifiedRow `id` field already uses `h-${listener_id}` and `j-${job_id}` format (handlers.tsx:37,53) — these match the handler deep-link format exactly
- The mobile card `href` at line 257 currently uses `?focus=` — change to handler deep-link
- The AppLink at line 310 currently uses `query={focus=...}` — change to a direct `<a>` with handler deep-link href, or update AppLink to accept a `handlerId` prop (done in T07)
- For now, use raw `<a>` tags for handler deep-links until T07 updates AppLink

## Verify
- [ ] FR#5: Tier filter, app filter, sort column, sort direction, and search text are readable from and writable to query parameters
- [ ] AC#6: Changing the sort column on the handlers page does NOT create a new history entry
