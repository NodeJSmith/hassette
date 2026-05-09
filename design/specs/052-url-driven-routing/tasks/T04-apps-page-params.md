---
task_id: "T04"
title: "Wire query params into AppsPage"
status: "done"
depends_on: ["T01"]
implements: ["FR#4", "FR#12", "AC#6"]
---

## Summary
Replace the `useState`-based filter, sort, and search state on the apps page with URL query parameters via `useQueryParams`. Filter/sort/search changes replace the current history entry (no back/forward pollution). Default values are omitted from the URL.

## Prompt
Modify one file:

**Update `frontend/src/pages/apps.tsx`**:
- Import `useQueryParams` from `../hooks/use-query-params`
- Replace `useState<FilterId>("all")` with `useQueryParams().get("filter") ?? "all"` (cast to FilterId)
- Replace `useState<AppSortState>({ key: "status", dir: "asc" })` with reads from `sort` and `dir` query params, defaulting to `"status"` and `"asc"`
- Replace `useState("")` for search with `useQueryParams().get("search") ?? ""`
- When filter/sort/search change, call `qp.set({ filter, sort, dir, search })` with `push: false` (default = replace)
- Omit default values: `filter: "all"` → omit, `sort: "status"` → omit, `dir: "asc"` → omit, `search: ""` → omit
- The `expanded` signal (line 219) stays as local state — multi-instance expand/collapse is UI-only, not URL state
- FilterPills `onChange` should call `qp.set({ filter: newFilter === "all" ? null : newFilter })`
- SortHeader `onSort` should call `qp.set({ sort: newSort.key === "status" ? null : newSort.key, dir: newSort.dir === "asc" ? null : newSort.dir })`
- Search input `onInput` should call `qp.set({ search: value || null })`

## Focus
- Default values for apps page: filter="all", sort="status", dir="asc", search="" — omit all of these from URL
- The `compareAppRows` function and FilterPills component don't need changes — they receive the values the same way
- `useQueryParams().set()` with default `push: false` already replaces history (FR#12)
- Be careful with the sort state shape: current code uses `{ key, dir }` object — the URL stores them as separate params

## Verify
- [ ] FR#4: Status filter, sort column, sort direction, and search text are readable from and writable to query parameters
- [ ] FR#12: Changing the sort column or filter does not create a new browser history entry
- [ ] AC#6: Changing the sort column on a list page does NOT create a new history entry
