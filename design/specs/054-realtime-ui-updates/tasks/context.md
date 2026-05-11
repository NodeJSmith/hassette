# Context: Real-Time UI Updates

## Problem & Motivation
The monitoring UI shows stale data once rendered. Handler invocation counts, job execution counts, health metrics, "last fired" timestamps, and activity tables freeze at their initial values and never update until a full page refresh. Relative timestamps like "5m ago" remain frozen indefinitely. This is especially harmful when monitoring after a deploy or during known activity — the UI appears inert, eroding trust in the monitoring tool's core purpose.

## Visual Artifacts
None.

## Key Decisions
1. **Debounced refetch over optimistic updates** — WS events trigger debounced API refetches rather than client-side state updates. More reliable since WS payloads are summaries, not complete snapshots. 500ms debounce + 1500ms max-wait.
2. **Shared `useFilteredSignalRefetch` hook** — replaces all `useDebouncedEffect(() => signal.value, ...)` patterns. Subscribes via `useSignalEffect` (outside render cycle) to avoid blast-radius re-renders. Mandatory for all WS-triggered subscriptions — no inline patterns allowed.
3. **Adopt `useRelativeTime` hook everywhere** — the hook exists but was never adopted. All `formatRelativeTime` calls in components must be replaced. Plain helper functions need architectural threading (hook called at component level, string passed as parameter).
4. **Database `rowid` for activity feed keys** — prefixed with kind (`h-`/`j-`) to ensure uniqueness across the UNION ALL query. Stable across refetches unlike client-generated IDs.
5. **`visibilitychange` listener for tab return** — added to the same `useEffect` as the existing interval timer in `App.tsx`, with cleanup.

## Constraints & Anti-Patterns
- Do NOT introduce new WebSocket message types — existing `invocation_completed` and `execution_completed` payloads are sufficient.
- Do NOT call `formatRelativeTime` directly from components — always use `useRelativeTime` hook.
- Do NOT read signal `.value` in `getValue()` callbacks at render time — this causes blast-radius re-renders.
- Do NOT synthesize activity feed keys client-side — they must come from the database.
- Do NOT use inline debounce patterns — use the shared `useFilteredSignalRefetch` hook.
- `useRelativeTime` is a hook — cannot be called inside plain functions, map callbacks, or conditional blocks. Thread computed strings as parameters where needed.

## Test Strategy
- **Frontend unit tests**: `useRelativeTime` tick subscription, `useFilteredSignalRefetch` filter/debounce behavior, activity feed key uniqueness via `row_id`
- **Frontend integration tests**: Mock WS events with matching/non-matching `app_key`, verify refetch-only-on-match and debounce bounds
- **Backend tests**: `get_app_recent_activity` `row_id` presence and uniqueness across handler/job entries with identical timestamps
- **E2E**: Existing suite for regression; manual verification of live update behavior
- **Test runner**: `cd frontend && npx vitest run` for frontend; `timeout 300 uv run nox -s dev -- -n 2` for backend

## Design Doc References
- "## Architecture > 1. Activity feed unique keys" — backend SQL change + frontend key fix
- "## Architecture > 2. Relative timestamp ticking" — per-location migration plan with hook-call constraints
- "## Architecture > 3. App detail page auto-refresh" — parent-level refetch + RecentLogsSection subscription
- "## Architecture > 4. Reduce re-render blast radius" — `useFilteredSignalRefetch` hook design + mandatory migration list
- "## Architecture > 5. Apps landing page auto-refresh" — dashboard grid refetch subscription
- "## Key Constraints" — explicit prohibitions
- "## Test Strategy" — frontend unit, integration, backend, and E2E test approach
