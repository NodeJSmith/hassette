# Context: URL-Driven Routing

## Problem & Motivation
View state in the hassette monitoring UI is ephemeral — refreshing a page resets tab selection, handler focus, sort order, filters, and time window to defaults. There is no way to bookmark a specific view or use browser back/forward to navigate between previously visited views within a page. This feature makes every interactive control URL-driven so that refreshing, bookmarking, and browser navigation all preserve the exact view state.

## Visual Artifacts
None.

## Key Decisions
1. **Path segments for identity, query params for view state.** Tabs and handler selection are path segments (`/apps/:key/handlers/h-42`); sort, filter, search, instance, time window are query params. Rationale: path segments identify what you're looking at; query params modify how you see it.
2. **Single-component mounting model.** `AppDetailPage` stays mounted when tabs change — the active tab is derived from the URL path via `useLocation()`. Tabs do NOT use nested Route components. Rationale: preserves the existing `staleListeners`/`staleJobs` ref pattern and avoids data refetches on tab switches.
3. **Handler IDs use `h-{id}` and `j-{id}` prefixes.** Not `handler_method` (not unique within an app). The `h-` prefix matches the existing convention in `handlers.tsx`.
4. **Multi-instance index as query param** (`?instance=N`), not path segment. Rationale: path segment conflicts with tab names in wouter's route matching. Exception: `?instance=0` is retained for multi-instance apps (not omitted as default) because no-param URL is reserved for the parent overview.
5. **Time window: read-only URL override.** `effectiveTimePreset = computed(() => urlWindowParam ?? timePreset)`. URL `?window=` overrides localStorage for the current page without writing to localStorage. Clicking the time preset button updates both.
6. **History behavior.** Tab/handler changes push history (back/forward navigates). Filter/sort/search/time window changes replace (no history pollution).
7. **Centralized URL correction via `correctUrl`.** Silently fixes invalid URL state now; future-proofed for toast notifications. Must only fire after data fetch is complete.
8. **"Back to handlers" button removed.** Browser back handles this now that tab switches push history entries.

## Constraints & Anti-Patterns
- Do NOT use nested Route components for tabs — AppDetailPage must stay mounted
- Do NOT use `handler_method` as URL slug — it's not unique within an app
- Do NOT remove localStorage time preset persistence — URL override is additive
- Do NOT fire `correctUrl` during loading state or with stale data
- Do NOT include `?instance=0` omission for multi-instance apps — it would show parent overview instead
- Do NOT put multi-instance index in a path segment — it conflicts with tab names
- Do NOT build URLs via raw string interpolation — use `useQueryParams.set()` which handles encoding
- Default query param values must be omitted from the URL (except instance on multi-instance apps)

## Design Doc References
- `## Architecture > URL Scheme` — complete route table and query param table
- `## Architecture > Route Definition Order` — wouter Switch ordering rules
- `## Architecture > useQueryParams Hook` — hook API contract
- `## Architecture > Time Window Sync` — effectiveTimePreset computed signal design
- `## Architecture > URL Correction Mechanism` — correctUrl function contract
- `## Architecture > View in Code` — ?line= param replacing signal-based focusLine
- `## Architecture > Component Changes` — per-component migration notes
- `## Key Constraints` — three hard constraints on handler IDs, instance routing, localStorage
