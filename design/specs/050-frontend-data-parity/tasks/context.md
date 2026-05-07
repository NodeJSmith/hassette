# Context: Frontend Data Parity

## Problem & Motivation
The hassette monitoring UI surfaces only a fraction of the data the backend computes. Job detail panels lack error context that handler detail panels have — no last error, no traceback, no min/max duration. Handlers are missing successful/cancelled counts and min/max duration breakdown. There is no way to view all handlers or jobs globally without clicking into each app. Internal service health is compressed into a dashboard badge with no drill-down. Drop counters are a badge in the status bar with no category breakdown. The operator must fall back to logs or piece together information from multiple views to diagnose issues.

## Visual Artifacts
None.

## Key Decisions
1. **Job metric parity with handlers** — extend `JobSummary` with `last_error_message/type/ts`, `min_duration_ms`, `max_duration_ms` using the same LEFT JOIN subquery pattern as `get_listener_summary()`. No migration needed (columns already exist in `job_executions`).
2. **NULL sentinel for new min/max fields** — use `float | None = None` (no `COALESCE`) so `None` means "never executed" and `0.0` means "executed in under 1ms." Drop existing `COALESCE(MIN(...), 0.0)` from handler queries too.
3. **Client-side tier filtering** — endpoints return all tiers; the frontend filters by `source_tier` field in-component. `gather_all_listeners()` must drop its hardcoded `source_tier="app"` filter.
4. **New `get_all_jobs_summary()`** — single efficient query on `TelemetryQueryService` with no `app_key` filter, consistent with `get_all_app_summaries()`. Not a fan-out via `gather_all_jobs()`.
5. **Two-phase service init on diagnostics page** — seed from `GET /api/health` (extended `ServiceInfoResponse`), then subscribe to WS `service_status` broadcasts for live updates.
6. **Drop counters read from global state** — the diagnostics page reads `useAppState()` signals already populated by `useTelemetryHealth`. No additional fetch.
7. **Dashboard dropped events always visible** — "0 events dropped" in muted, "N events dropped" in warn. Links to diagnostics page.
8. **Cancellation race accepted** — global jobs endpoint has a brief inconsistency window between DB query and heap snapshot. Frontend handles `next_run < now` on non-cancelled jobs as "overdue."

## Constraints & Anti-Patterns
- Do NOT surface `entity_id`, `topic`, `handler_summary`, or `predicate_description` on handler detail — cut as redundant in prior work
- Do NOT surface `di_failures` count — too niche
- Do NOT build session history or session-dependent features
- Do NOT add new WebSocket subscription types — use existing broadcasts
- All UI follows `design/context.md` tokens: `--bg-surface` for cards, `--err`/`--err-bg` for errors, Geist Mono for data, compact density (10-12px), no left-border accents, no emoji
- Status indicators use shape + color via the existing `StatusShape` component
- New pages must be added to sidebar nav AND command palette

## Design Doc References
- ## Problem — what's broken and why
- ## Goals — measurable success criteria (4 items)
- ## Functional Requirements — FR#1-18, the complete behavior spec
- ## Edge Cases — 11 specific boundary conditions including race acceptance
- ## Acceptance Criteria — AC#1-14, testable outcomes
- ## Key Constraints — 5 design constraints including field exclusions
- ## Architecture — backend changes (models, queries, endpoints) and frontend changes (detail panes, new pages, navigation)
- ## Test Strategy — backend unit, frontend component, E2E Playwright
