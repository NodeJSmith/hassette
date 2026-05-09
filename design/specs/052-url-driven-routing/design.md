# Design: URL-Driven Routing

**Date:** 2026-05-09
**Status:** approved
**Scope-mode:** expand

## Problem

View state in the hassette monitoring UI is ephemeral. Refreshing a page resets tab selection, handler focus, sort order, filters, and time window to defaults. There is no way to bookmark a specific view, share a link to a particular handler's detail pane, or use browser back/forward to navigate between previously visited views within a page. Every debugging session starts from scratch.

## Goals

- All of the following interactive controls are URL-driven: tab selection, handler/job selection, sort column, sort direction, status filter, tier filter, app filter, search text, log level, time window preset, instance index, and code focus line. Success metric: every listed control is readable from and writable to the URL.
- Refreshing any page with any combination of the above controls set reproduces the exact view 100% of the time — no control reverts to its default on refresh
- Browser back/forward navigates between tabs and handler selections (history push), while filter/sort/search changes update in-place (history replace)
- Bookmarking a URL with a time window override preserves that specific window without changing the user's global preference
- Invalid URL state (unknown handler, out-of-range instance) is handled through a centralized correction mechanism that can be extended with user-visible notifications in the future

## Non-Goals

- No new UI elements (no "copy link" button, no "share" feature) — the URL bar is the sharing mechanism
- No server-side rendering or SSR-aware routing
- No deep-linkable diagnostics service cards (diagnostics page has no interactive filters)
- No per-row deep-links on the global handlers page — the handlers page is a cross-app summary view with no drill-down; handler detail lives only under `/apps/:key/handlers/:handlerId`

## User Scenarios

### Operator: Home automation developer

- **Goal:** Debug a misfiring automation handler
- **Context:** Notices a handler failing in the hassette monitoring UI

#### Investigate a specific handler

1. **Navigate to the app**
   - Sees: app list with status indicators
   - Decides: clicks the failing app
   - Then: URL changes to the app detail page with handlers tab

2. **Select the failing handler**
   - Sees: handler list with status and error counts
   - Decides: clicks the failing handler row
   - Then: URL changes to include the handler identifier; detail pane shows handler stats, errors, and invocations

3. **Switch to logs tab to correlate errors**
   - Sees: tab strip with handlers, code, logs, config
   - Decides: clicks "logs"
   - Then: URL changes to the logs tab path; handler selection is naturally scoped out

4. **Filter logs to errors only**
   - Sees: log level dropdown, search box
   - Decides: sets level to ERROR
   - Then: URL updates with level filter; table shows only error-level entries

5. **Bookmark this filtered view**
   - Decides: bookmarks the URL
   - Then: returning to the bookmark later restores the exact logs tab with ERROR filter

#### Resume from a bookmark

1. **Open a bookmarked URL**
   - Sees: the page loads with the exact tab, handler, filters, and time window from the bookmark
   - Then: can continue debugging from where they left off

#### Open a stale bookmark

1. **Open a bookmarked handler URL where the handler no longer exists**
   - Sees: the app detail page loads on the handlers tab, but no handler is selected
   - Then: the URL is corrected to remove the invalid handler ID; the centralized correction mechanism records the reason for future notification support

#### Navigate back through history

1. **Press browser back button**
   - Sees: returns to the previous tab or handler selection
   - Then: filter/sort state on the current page is not in the history stack (replaced in-place)

## Functional Requirements

- **FR#1** Tab selection on the app detail page is determined by the URL path segment
- **FR#2** Handler/job selection on the app detail page is determined by the URL path segment using a kind-and-id identifier
- **FR#3** Multi-instance app index is determined by a query parameter, not a path segment
- **FR#4** Status filter, sort column, sort direction, and search text on the apps page are determined by query parameters
- **FR#5** Tier filter, app filter, sort column, sort direction, and search text on the handlers page are determined by query parameters
- **FR#6** Log level, tier filter, app filter, search text, sort column, and sort direction on the global logs page are determined by query parameters
- **FR#7** Log level, search text, sort column, and sort direction on the app detail logs tab are determined by query parameters
- **FR#8** Time window preset is determined by a query parameter when present; falls back to the user's persisted global preference when absent
- **FR#9** Clicking the time window preset button updates both the URL query parameter and the user's persisted global preference
- **FR#10** Arriving at a URL with a time window query parameter does not update the user's persisted global preference
- **FR#11** Tab and handler selection changes push new browser history entries
- **FR#12** Filter, sort, search, and time window changes replace the current browser history entry
- **FR#13** The "view in code" action is encoded as a query parameter on the code tab path, allowing it to be bookmarked and restored on refresh
- **FR#14** Query parameters with default values are omitted from the URL to keep URLs clean. Exception: `?instance=0` is retained on multi-instance apps because the no-param URL is reserved for the parent-overview state
- **FR#15** All navigation sources (sidebar, command palette, in-page links) generate URLs in the new format
- **FR#16** Invalid URL state corrections (unknown handler ID, out-of-range instance, unrecognized filter value) are routed through a centralized correction function that silently fixes the URL now, but can be extended to emit user-visible notifications (e.g., toasts) in the future without reworking each page. The correction function must only fire after the relevant data fetch is complete and confirms the item does not exist — it must not fire during loading or while stale data is in use.

## Edge Cases

- **Handler method name collisions**: Multiple handlers within an app may share the same `handler_method` string. Deep-links use the kind-and-numeric-id pattern (e.g., `h-42`, `j-7`) to ensure deterministic targeting.
- **Invalid handler ID in URL**: If a URL references a handler ID that doesn't exist (deleted, different instance), the handlers tab loads with no selection rather than erroring.
- **Invalid tab segment**: If a URL contains an unrecognized tab name (e.g., `/apps/foo/metrics`), the page renders 404.
- **Instance index out of range**: If `?instance=99` exceeds the app's instance count, the page corrects to instance 0 via the centralized correction mechanism (FR#16).
- **Empty query param values**: `?search=` (empty string) is treated as absent — the parameter is omitted from the URL entirely.
- **Direct URL access (browser refresh)**: Entering a deep URL directly in the browser (or refreshing) must load the correct view, not a 404. The server must be configured to serve the single-page application for all client-side route paths.
- **Time window override expiry**: A bookmarked URL with `?window=since-restart` always means "since the current restart" — the window recalculates on each load, not from the bookmark creation time.

## Acceptance Criteria

- **AC#1** Refreshing any page in the app restores the exact view state visible before refresh (FR#1–FR#8)
- **AC#2** Navigating to `/apps/motion_lights/handlers/h-42` selects listener 42 on the handlers tab (FR#1, FR#2)
- **AC#3** Navigating to `/apps/motion_lights/logs?level=ERROR&search=timeout` shows the logs tab filtered to ERROR level with "timeout" search (FR#1, FR#7)
- **AC#4** Clicking "view in code" from a handler navigates to the code tab with a line query parameter; refreshing restores the scroll position and highlight (FR#13)
- **AC#5** Pressing browser back after switching from handlers tab to logs tab returns to the handlers tab (FR#11)
- **AC#6** Changing the sort column on the handlers page does NOT create a new history entry (FR#12)
- **AC#7** Bookmarking `/handlers?window=24h` and opening it later shows 24h data, while navigating to `/apps` (no window param) shows the user's persisted global preference (FR#8, FR#10)
- **AC#8** Clicking the time preset button on any page updates both the URL and the persisted global preference (FR#9)
- **AC#9** All default query parameters are omitted from the URL — navigating to the apps page with default filters produces `/apps` not `/apps?filter=all&sort=status&dir=asc` (FR#14)
- **AC#10** Navigating to a URL with an invalid handler ID shows the handlers tab with no selection and corrects the URL via the centralized correction mechanism (FR#16)
- **AC#11** All navigation sources produce URLs in the new format (FR#15)
- **AC#12** Navigating to `/apps/multi_app?instance=1` loads instance 1; navigating to `/apps/multi_app` (no instance param) shows the parent overview grid (FR#3, FR#14)
- **AC#13** Navigating to `/apps` with default filter, sort, and search produces a clean URL with no query parameters (FR#14)
- **AC#14** Navigating to a URL with `?instance=99` on an app with 2 instances corrects the URL to `?instance=0` and loads instance 0 (FR#16)

## Key Constraints

- **Handler deep-link identifiers must use kind+numeric-id** (e.g., `h-42` for listeners, `j-7` for jobs), not `handler_method` — the method string is not unique within an app. The `h-` prefix matches the existing convention in `handlers.tsx`.
- **Multi-instance index must not occupy a path segment** — it conflicts with tab name segments in wouter's route matching. Query parameter is the only safe location.
- **Do not remove localStorage time preset persistence** — URL override is additive, not a replacement. The global preference must survive across pages without `?window=` params.

## Dependencies and Assumptions

- Wouter v3.9.0 supports the required routing patterns: literal path segments match before parameter segments in a Switch, and `useSearch()` provides query string access.
- The Vite dev server can be configured with `appType: 'spa'` or history fallback middleware for direct URL access during development.
- Production deployment (Docker/Traefik) already serves the SPA correctly for known routes; adding new path patterns under `/apps/` should not require Traefik configuration changes since the backend serves `index.html` for unknown paths.

## Architecture

### URL Scheme

**Path segments** (identity — what you're looking at):

```
/apps                                  app list
/apps/:key                             app detail (defaults to handlers tab)
/apps/:key/handlers                    handlers tab (explicit)
/apps/:key/handlers/:handlerId         specific handler selected (e.g., h-42, j-7)
/apps/:key/code                        code tab
/apps/:key/logs                        logs tab
/apps/:key/config                      config tab
/handlers                              global handlers list
/logs                                  global logs
/diagnostics                           diagnostics
/config                                config
```

**Query parameters** (view state — how you're looking at it):

| Param | Pages | Values | Default |
|---|---|---|---|
| `instance` | `/apps/:key/*` | non-negative integer | 0 (omitted) |
| `filter` | `/apps` | all, running, failed, stopped, disabled, blocked | all (omitted) |
| `sort` | `/apps`, `/handlers`, `/logs`, app logs tab | column key string | page-specific default (omitted) |
| `dir` | same as sort | asc, desc | page-specific default (omitted) |
| `search` | `/apps`, `/handlers`, `/logs`, app logs tab | free text | empty (omitted) |
| `tier` | `/handlers`, `/logs` | all, app, framework | app (omitted) |
| `app` | `/handlers`, `/logs` | app_key string | empty = all (omitted) |
| `level` | `/logs`, app logs tab | DEBUG, INFO, WARNING, ERROR, CRITICAL | INFO (omitted) |
| `line` | `/apps/:key/code` | positive integer (source line number) | absent (omitted) |
| `window` | all data pages | since-restart, 1h, 24h, 7d | absent = use localStorage |

### Route Definition Order

Wouter's Switch matches top-to-bottom, first match wins. Routes with literal path segments (e.g., `/apps/:key/handlers`) must appear before shorter parameter routes (e.g., `/apps/:key`) to avoid premature matching.

```
/apps/:key/handlers/:handlerId    (4 segments, literal "handlers" at pos 2)
/apps/:key/handlers               (3 segments, literal "handlers" at pos 2)
/apps/:key/code                   (3 segments, literal "code" at pos 2)
/apps/:key/logs                   (3 segments, literal "logs" at pos 2)
/apps/:key/config                 (3 segments, literal "config" at pos 2)
/apps/:key                        (2 segments, base app route)
/apps                             (1 segment, app list)
```

Unrecognized segments under `/apps/:key/` (e.g., `/apps/foo/metrics`) fall through to the 404 catch-all.

### useQueryParams Hook

A thin reusable hook wrapping wouter's `useSearch()` and `useLocation()`:

```typescript
function useQueryParams(): {
  get(key: string): string | null;
  set(updates: Record<string, string | null>, options?: { push?: boolean }): void;
}
```

- `set()` with `push: false` (default) replaces the current history entry
- `set()` with `push: true` pushes a new history entry
- Setting a value to `null` or `""` removes the parameter from the URL
- Each page reads its parameters on mount and uses them to initialize state

### Time Window Sync

An `effectiveTimePreset` computed signal is added to the global app state, derived from the URL `?window=` param and the existing `timePreset` signal:

```
effectiveTimePreset = computed(() => urlWindowParam.value ?? timePreset.value)
```

`useScopedApi` reads `effectiveTimePreset` instead of `timePreset` to determine the API time window. This ensures URL overrides reach the data layer without writing to localStorage.

- **On page load**: a page-level effect reads `?window=` from query params and writes it to a `urlWindowParam` signal (page-scoped, not persisted). `effectiveTimePreset` picks it up.
- **On button click**: update localStorage via the existing `timePreset` signal, update the `urlWindowParam` signal, AND update the URL via `set({ window: value })`
- **On navigation without `?window=`**: `urlWindowParam` is null, so `effectiveTimePreset` falls back to the localStorage-backed `timePreset` signal

### URL Correction Mechanism

A centralized `correctUrl` function handles invalid URL state. When a page detects that URL parameters don't match available data (handler ID not found, instance out of range, unrecognized filter value), it calls `correctUrl` with:

- The corrected URL (with invalid params removed or fixed)
- A reason string describing what was wrong (e.g., `"handler h-999 not found"`, `"instance 5 out of range, using 0"`)

`correctUrl` replaces the URL via `navigate(correctedUrl, { replace: true })`. The reason string is currently unused but is the future hook point — when toast notifications are added, `correctUrl` emits the reason as a toast instead of silently correcting. No page-level code changes are needed when that happens.

### View in Code

The "view in code" button navigates to `/apps/:key/code?line=N&instance=M` instead of mutating signals. The code tab reads `?line=` on mount, scrolls to and highlights the target line. The `cameFromHandlers` signal and "back to handlers" button are both removed — browser back handles this navigation now that tab switches push history entries (FR#11).

### Component Changes

**Tab strip** (`app-detail.tsx`): Tab buttons become `<Link>` elements pointing to `/apps/:key/{tab}?instance=N`. The `activeTab` signal is removed — the active tab is derived from the route. **Mounting model:** `AppDetailPage` remains a single mounted component; the active tab is read from the URL path via `useLocation()` without unmounting. Tabs do not use nested Route components. This preserves the existing `staleListeners`/`staleJobs` ref pattern and avoids data refetches on tab switches.

**Handler selection** (`handlers-tab.tsx`): The `selectedId` signal is removed. Selection is derived from the `:handlerId` route parameter. Clicking a handler navigates to `/apps/:key/handlers/{kind}-{id}`. The `focusMethod` / `?focus=` pattern is replaced by handler deep-links.

**Instance switcher** (`app-detail.tsx`): Navigation changes from `/apps/:key/:index` to the current tab path with `?instance=N`.

**AppLink component** (`app-link.tsx`): The `instanceIndex` prop changes from appending `/:index` to appending `?instance=N`. The `query` prop for `?focus=` is replaced by `handlerId` prop that builds handler deep-links.

**Command palette** (`command-palette.tsx`): Handler items navigate to `/apps/:key/handlers/h-{id}` instead of `/apps/:key?focus=method`.

**Sidebar** (`sidebar.tsx`): Instance links change from `/apps/:key/:index` to `/apps/:key?instance=N`.

**List pages** (`apps.tsx`, `handlers.tsx`): `useState` calls for filter/sort/search are replaced with `useQueryParams().get()` reads and `useQueryParams().set()` writes.

**Log table** (`log-table.tsx`): Signal-based filter state is replaced with query param reads/writes when used on the global logs page. When embedded in the app detail logs tab, the same query params are used (scoped to the `/apps/:key/logs` route).

### Vite SPA Fallback

Add history fallback to `vite.config.ts` for the dev server so direct URL access works during development:

```typescript
server: {
  // existing proxy config...
},
appType: 'spa',
```

Production builds already serve through the hassette backend which returns `index.html` for unmatched paths.

## Alternatives Considered

**History state only (no URL changes)**: Using `history.pushState` with state objects would enable back/forward navigation without changing URLs. Rejected because the primary goal is bookmarkable, shareable URLs. History state is invisible to the user and cannot be bookmarked.

**Hash-based routing**: Encoding state after `#` (e.g., `#/apps/foo/handlers?sort=name`). Rejected because wouter already uses browser history mode, the codebase has no hash routing, and hash URLs look dated. Also requires rewriting all existing route definitions.

**TanStack Router migration**: TanStack Router has built-in type-safe search params and route validation. Rejected because it's a much larger migration (replace wouter entirely), the codebase is Preact-based (TanStack Router primarily targets React), and the `useQueryParams` hook provides sufficient functionality for this use case.

**handler_method as URL slug**: Using the human-readable method name (e.g., `/apps/foo/handlers/on_motion`) instead of kind+id. Rejected because `handler_method` is not guaranteed unique within an app — two listeners could share the same method name, leading to ambiguous URLs.

## Test Strategy

- **Unit tests** for `useQueryParams` hook: verify reading, writing, default omission, and history push vs replace behavior
- **Unit tests** for `correctUrl`: verify it replaces the URL and records the reason string
- **Update existing e2e tests** (`test_navigation.py`, `test_app_detail.py`): adjust URL assertions for new path patterns and query parameters
- **New e2e tests**: verify tab deep-links, handler deep-links, filter persistence across refresh, browser back/forward for tab changes, time window override behavior, view-in-code line param, URL correction for invalid handler IDs
- **Manual verification**: test direct URL access (paste URL into fresh browser tab) in both dev server and Docker deployment

## Documentation Updates

- Update `design/context.md` Component Inventory sections that reference URL patterns (App Detail, Handlers Page, Layout)
- No user-facing documentation changes needed — this is internal UI behavior

## Impact

**Files modified:**

- `frontend/src/app.tsx` — route definitions expanded
- `frontend/src/hooks/use-query-params.ts` — new hook (new file)
- `frontend/src/pages/app-detail.tsx` — tab from route, handler from route, instance from query param
- `frontend/src/pages/apps.tsx` — filter/sort/search from query params
- `frontend/src/pages/handlers.tsx` — tier/app/sort/search from query params
- `frontend/src/pages/logs.tsx` — may need to pass query param context to LogTable
- `frontend/src/components/shared/log-table.tsx` — filter state from query params (global mode)
- `frontend/src/components/shared/app-link.tsx` — instance via query param, handler deep-links
- `frontend/src/components/app-detail/handlers-tab.tsx` — selection from route param
- `frontend/src/components/app-detail/handler-list.tsx` — selection callback changes
- `frontend/src/components/layout/command-palette.tsx` — handler navigation URLs
- `frontend/src/components/layout/sidebar.tsx` — instance link URLs
- `frontend/src/hooks/use-correct-url.ts` — centralized URL correction (new file)
- `frontend/src/state/create-app-state.ts` — time preset URL sync layer
- `frontend/vite.config.ts` — SPA fallback for dev server
- `tests/e2e/test_navigation.py` — URL assertion updates for new path patterns
- `tests/e2e/test_app_detail.py` — URL assertion updates for new path patterns

<!-- Gap check 2026-05-09: 3 gaps included — use-scoped-api.ts:62 (reads timePreset) → T01, code-tab.tsx:12 (focusLine prop) → T03, use-scoped-api.test.ts (timePreset tests) → T01 -->

**Blast radius:** Frontend-only. No backend changes. No API changes. No database changes. All changes are within the `frontend/` directory except e2e test updates and vite config.

## Open Questions

None — all decisions resolved during discovery.
