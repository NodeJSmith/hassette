# Design: Ink UI Redesign

**Date:** 2026-05-02
**Status:** archived
**Research:** /tmp/ink-redesign-research-brief.md, /tmp/sessions-prior-art-brief.md

## Problem

The monitoring UI was a functional first pass that got the framework working, but it has accumulated gaps that degrade the developer experience:

1. **Stale data**: Handler invocation tables and job execution tables go stale between manual refreshes. There is no real-time push when automations fire or jobs complete. Users must collapse and re-expand rows to see current data.

2. **Missing surfaces**: The backend tracks rich data — human-readable handler descriptions, predicate conditions, execution cross-links, handler modifiers (debounce, throttle, priority), framework vs app error separation, telemetry health counters — that the UI does not display. Users who need this information must query the API directly.

3. **Visual design**: The current design (Graphite+Emerald, Space Grotesk/DM Sans/JetBrains Mono) was a pragmatic choice to ship quickly. A comprehensive design exploration has since produced a more intentional design system ("Ink") with editorial typography, a monochrome editorial aesthetic, and a deliberate status-color vocabulary that better serves the diagnostic use case.

4. **Session scoping confusion**: The "This Session | All Time" toggle conflates a daemon implementation detail (session IDs) with what users actually want (time-windowed data). No comparable monitoring tool uses this pattern.

5. **Narrow sidebar**: The current 56px icon-only sidebar rail provides no context about app health. Users must navigate to the Apps page to see which apps are running, failing, or stopped.

## Goals

- Every piece of data the backend tracks is visible in the UI without requiring API calls
- Handler and job tables update in real-time when automations fire, within 2 seconds of completion
- Users can identify failing apps, see error details, and navigate to the relevant handler within 3 clicks from any page
- The time-scoping mechanism matches the mental model of comparable monitoring tools (time-window presets, not session IDs)
- Light and dark themes are first-class, with correct contrast ratios across all status colors
- All existing Playwright E2E user workflows continue to pass against the new UI
- Component-level and E2E test coverage for all pages

## Non-Goals

- **Events inspector page**: A live event firehose with handler cross-linking is valuable but requires significant backend enrichment. Deferred to a separate effort.
- **Code editing in the UI**: The Code tab is read-only. Users write code in their editor.
- **App creation/deletion UI**: No "New app" or "Delete app" flows. Apps are managed via the filesystem.
- **Full backend session removal**: The backend write infrastructure (SessionManager, DB schema with session_id FK, telemetry repository session writes) is retained for now. Sessions are removed from the API surface (routes, query methods, WS messages) but the internal plumbing is a dedicated follow-up migration.
- **CSS architecture migration**: The redesign uses the same global CSS + string class reference pattern. CSS modules or utility-class adoption is out of scope.

## User Scenarios

### Alex: Home automation developer

- **Goal:** Verify that a newly deployed automation is working correctly
- **Context:** Just pushed a code change and restarted hassette. Opens the UI to confirm.

#### Deploy verification

1. **Opens the UI**
   - Sees: Overview page with greeting, system health, app status cards, recent errors
   - Decides: Scans for red — any failing apps or recent errors?
   - Then: If all green, checks the specific app they changed

2. **Clicks the app in the sidebar**
   - Sees: App detail with health strip, handler list with invocation counts, last-run times
   - Decides: Has my handler fired since the restart? What was the result?
   - Then: Expands the handler to see invocation history

3. **Reviews invocation detail**
   - Sees: Most recent invocations with status, duration, trigger entity, and (if errored) exception type and traceback
   - Decides: Is the handler working correctly? Any unexpected errors?
   - Then: If satisfied, closes the tab. If errored, clicks through to see the full traceback.

#### Mid-incident debugging

1. **Opens the UI after noticing an automation didn't fire**
   - Sees: Overview with error banner showing which app has failed, error count, most recent exception
   - Decides: Which app is failing? What's the error?
   - Then: Clicks the failing app in the sidebar (highlighted in the "failing" group)

2. **Reviews the failing app**
   - Sees: Error banner with exception type and message, handler list with failure counts, last error time
   - Decides: Which handler is broken? Is it a code bug or a configuration issue?
   - Then: Expands the failing handler to see the traceback

3. **Reads the traceback**
   - Sees: Full Python traceback with file, line, and function. Handler registration code snippet showing the decorator/subscription. The event data that triggered the invocation.
   - Decides: Understands the root cause, goes to fix the code
   - Then: After fixing, watches the handler's invocation list update in real-time to confirm the fix works

### Robin: New hassette user

- **Goal:** Get oriented with hassette's monitoring capabilities
- **Context:** Just installed hassette, has 1-2 simple automations running

#### First-time orientation

1. **Opens the UI for the first time**
   - Sees: Overview with welcome message, code snippet showing how to write a first app, system health showing connected to HA
   - Decides: Explores the sidebar to understand the navigation
   - Then: Clicks through each section to understand what's available

2. **Navigates to their running app**
   - Sees: App detail with handlers, health metrics, and configuration
   - Decides: Understands what the UI monitors — handler invocations, errors, performance
   - Then: Gains confidence that hassette is tracking their automations

### Sam: Power user with multi-instance apps

- **Goal:** Monitor a multi-instance automation (same app class, different configs per room/zone)
- **Context:** Has a "remote_app" with 4 instances (one per family member), each with different entity configs

#### Multi-instance monitoring

1. **Clicks the multi-instance app in the sidebar**
   - Sees: Parent app overview with instance grid showing each instance's status, run count, and inline error preview
   - Decides: Identifies which instance (if any) is failing
   - Then: Clicks the failing instance card to drill in

2. **Reviews instance detail**
   - Sees: Instance-specific handlers, invocations, and errors. Instance switcher in the header to flip between siblings.
   - Decides: The issue is specific to this instance's config
   - Then: Checks the Config tab to see instance-specific configuration values

## Functional Requirements

### Design System

1. The UI uses the "Ink" design system with two themes: Ink Light (default) and Ink Dark
2. Light theme uses monochrome accent (primary text color as accent); dark theme uses periwinkle (#7A8AFF) accent
3. Status indicators use shape coding in addition to color: circle (ok), triangle (warn), square (err), ring (mute) — legible in grayscale
4. Typography uses three font families: a serif display face for page titles and big numbers, a sans-serif for body text and UI, and a monospace for code, IDs, timestamps, and log lines
5. Spacing follows a 4px base grid with 10 named steps
6. Borders are the primary depth mechanism; shadows are reserved for floating surfaces (modals, command palette)
7. Status colors appear only when they carry meaning — no decorative use of red, amber, or green

### Layout and Navigation

8. The main layout is a 240px fixed sidebar + flexible main content area
9. The sidebar contains: wordmark, version + connection status, search trigger, top-level navigation (Overview, Logs, Config), and a searchable app list grouped by status (failing > blocked > slow > running > stopped > disabled)
10. Multi-instance apps in the sidebar expand to show instance children with tree connectors; parent status rolls up as worst-of-children
11. On viewports narrower than 768px, the sidebar becomes an off-canvas drawer activated by a hamburger button
12. A command palette (keyboard shortcut) provides global search across pages, apps, instances, handlers, and quick actions (reload all, stop all failing, open docs)

### Overview Page

13. The overview page displays a greeting, system metadata (HA version, app count, run rate), and a status summary
14. A framework error banner appears when boot-time configuration issues exist, separate from app errors
15. The overview adapts to system state: healthy (green hero card), single failure (error card with app detail), multiple failures (error list with crash counts), first install (onboarding code snippet), quiet (no recent activity message)
16. Summary cards show: top apps with status and run counts, activity metrics with trend visualization, and system service health
17. A recent errors table shows: timestamp, app, source location (module.function:line), exception type and message, and age

### App Detail Pages

18. Single-instance and per-instance detail pages show: app metadata (key, class, file, uptime), lifecycle status with action buttons (start/stop/reload), health strip (error rate, handler avg duration, job avg duration, last activity), and tabbed content
19. The Handlers tab uses a master/detail layout: scrollable handler list on the left, selected handler's detail on the right. On narrow viewports, this collapses to a drill-down pattern. Event handlers and scheduled jobs appear in a single unified list, differentiated by kind chip.
20. Each handler row shows: status indicator, kind chip (state/event/cron/svc), name, human-readable description, invocation or execution count, and last-error preview if errored
21. The handler detail pane shows kind-appropriate content. For state/event handlers: full registration signature, modifier chips (debounce, throttle, once, priority, immediate, registration source), predicate description, and an invocation history table. For scheduled jobs: trigger schedule chips (cron expression, human-readable label, next run, jitter, group), and an execution history table.
22. Each invocation/execution row shows: status, timestamp, trigger description, duration, and error note. Expandable to show event payload and full traceback.
23. Invocation rows include a link to the triggering event (via trigger context ID) for future cross-linking
25. The Code tab displays the app's source file with syntax highlighting and line numbers. Handler names are annotated in the gutter for quick navigation.
26. The Config tab displays the app's configuration: filename, class name, enabled state, and per-instance config values in a structured format
27. Multi-instance parent pages show an instance grid with per-instance status cards, shared code, and aggregate metrics. Each instance card links to its detail page.
28. The instance detail header includes a sibling switcher to navigate between instances without returning to the parent

### Logs Page

29. The logs page displays a filterable, sortable table with columns: timestamp, level badge, source location (module:function:line), app, message, and age
30. Log entries stream in real-time via the existing WebSocket subscription
31. Level filtering controls which log levels are displayed and which are streamed from the backend

### Config Page

32. The config page displays the system configuration as a structured table of allowlisted fields from hassette's configuration file. Add `app_dir`, `data_dir`, and `config_dir` (as string values) to the existing `ConfigResponse` allowlist — these are non-sensitive path values useful for debugging in HA addon installs where default paths are non-obvious.

### Time Scoping

33. The session scope toggle is replaced by a time-preset selector with options: "Since restart" (default), "Last 1 hour", "Last 24 hours", "Last 7 days"
34. "Since restart" computes its boundary from the system status `uptime_seconds` field (derived from `RuntimeQueryService._start_time`) — no session infrastructure required. Note: this timestamp differs slightly from `sessions.started_at` (set later by `SessionManager`); the difference is milliseconds under normal startup and irrelevant for UI display, but worth knowing if comparing raw DB queries.
35. The daemon's current uptime is displayed prominently in the sidebar or status area
36. All telemetry queries that previously accepted a session ID parameter instead accept an optional timestamp boundary

### Real-Time Updates

37. When a handler invocation completes, the backend broadcasts a completion event via WebSocket containing the handler ID, app key, status, duration, and error summary
38. When a job execution completes, the backend broadcasts a completion event via WebSocket containing the job ID, app key, status, duration, and error summary
39. The frontend uses these events to update handler/job tables without requiring a full refetch — either by appending to the visible invocation list or by triggering a targeted refetch of the affected handler/job
40. Dashboard KPIs and app health metrics refresh when invocation/execution events arrive, debounced to avoid excessive re-rendering
41. The broadcast volume for new events is managed through per-drain batching: one WS message per `_drain_and_persist()` cycle summarizing all completions in that batch. The frontend coalesces rapid updates via its existing refetch debounce.

### Data Surfacing

42. Handler rows display the human-readable description from the backend's handler summary field
43. ~~Predicate description chip deferred~~ — the backend currently returns raw `repr()` strings (e.g., `AllOf(predicates=(EntityMatches(...)))`) that are not suitable for chip display. Issue #692 tracks producing human-readable strings. Once that ships, the chip can be added.
44. Handler detail shows modifier chips for: debounce (with millisecond value), throttle (with value), once, priority (with level), and immediate. Registration source chip (decorator vs programmatic) is deferred — decorator registration is not yet implemented, so the value is always "programmatic" and the chip would be visual noise.
45. Handler and job rows separately display timed-out count distinct from failed count. Note: `ListenerWithSummary` is currently missing the `timed_out` field (the SQL computes it and `ListenerSummary` carries it, but the response model and mapper omit it). Add `timed_out: int = 0` to `ListenerWithSummary` and wire it in `to_listener_with_summary()` as a prerequisite.
46. The dashboard shows a framework error chip in the system health section, separate from app errors, using the framework summary endpoint
47. When telemetry drop counters are non-zero, a degraded-telemetry banner appears indicating data may be incomplete
48. App cards and sidebar entries show the auto-loaded badge for autodiscovered apps
49. Blocked apps display their block reason in a banner
50. ~~The slow handlers widget is deferred~~ — the existing `get_slow_handlers()` returns individual slow invocations (not per-handler averages), has no time filter, and requires a `threshold_ms` default that is not yet decided. `ListenerWithSummary` already carries `avg_duration_ms` — if this widget is added later, the frontend can sort existing listener data without a new endpoint.

### Backend Endpoints

51. A new endpoint returns the per-app configuration including filename, class name, enabled state, and resolved per-instance config values
52. A new endpoint returns the app's source code file contents, scoped to the configured apps directory with path traversal protection
53. ~~Slow-handlers endpoint deferred~~ — see FR#50. Issue #494 remains open for future consideration.

## Edge Cases

1. **Daemon just started, no telemetry yet**: Overview shows "Since restart" with zero data. Health metrics show "no data" rather than zeros. Handler tables are empty with an appropriate empty state message.
2. **Multi-instance app with mixed health**: Parent sidebar entry shows worst-of-children status. Instance grid on parent page clearly shows which instances are healthy vs failing. Aggregate metrics note partial health.
3. **App source file not found**: Code tab shows an error state ("File not found at expected path") rather than crashing. This can happen if the app was loaded from a path that has since been moved.
4. **WebSocket disconnection during data updates**: Invocation/execution events are lost during disconnect. On reconnect, the existing reconnect-refetch pattern fires to bring all data current. No data corruption.
5. **High-frequency automation (hundreds of invocations/second)**: WS broadcast debouncing prevents queue overflow. The UI batches incoming events rather than rendering each individually. Invocation history shows the most recent N entries with a "load more" pattern.
6. **App with no handlers or jobs**: Detail page shows empty states for both tabs rather than hiding them. The empty state message is informative ("No handlers registered — handlers appear when your app subscribes to events").
7. **Very long error tracebacks**: Tracebacks are displayed in a scrollable, monospace code block. Long lines wrap. The error summary (type + message) is always visible without scrolling.
8. **Time preset "Since restart" with very long uptime**: If the daemon has been running for weeks, "Since restart" returns a large dataset. The time preset selector offers shorter windows (1h, 24h, 7d) as alternatives. Queries use LIMIT clauses.
9. **Config with sensitive values**: The config endpoint only returns allowlisted fields (matching the existing sanitization pattern). Secrets and credentials are never exposed.
10. **Source code endpoint path traversal**: The endpoint validates that `manifest.full_path` resolves within `manifest.app_dir` (the per-manifest directory). Attempts to read files outside this boundary return 403.

## Acceptance Criteria

1. All five overview page state variants render correctly: healthy, single failure, multiple failures, first install, and quiet
2. Handler invocation tables update within 2 seconds of a handler completing, without manual refresh
3. Job execution tables update within 2 seconds of a job completing, without manual refresh
4. Every handler row displays its human-readable description, and errored handlers show the last error message inline
5. The handler detail pane shows all modifier chips (debounce, throttle, once, priority, immediate, registration source) when present
6. Multi-instance apps expand in the sidebar and show per-instance status; clicking an instance navigates to its detail
7. The command palette indexes all pages, apps, instances, and handlers, and navigating via the palette lands on the correct page with correct focus
8. The time preset selector defaults to "Since restart" and all telemetry queries respect the selected time boundary
9. Light and dark themes render correctly with no contrast failures on status colors
10. The off-canvas drawer opens and closes on mobile viewports, providing full navigation access
11. ~~Slow handlers widget deferred~~ — see FR#50
12. The config tab on app detail shows per-instance configuration values from the new endpoint
13. The code tab on app detail shows the app's source with syntax highlighting
14. Telemetry degradation banner appears when drop counters are non-zero
15. Framework errors display separately from app errors on the overview page
16. All pages have component-level tests covering primary render paths and key interactions
17. Playwright E2E tests cover: dashboard overview, app navigation, handler drill-down, job drill-down, log filtering, config display, theme switching, mobile drawer navigation, and command palette search
18. Status indicators are distinguishable in grayscale screenshots — each status level uses a distinct shape (circle, triangle, square, ring) not just color
19. Page titles render in the serif display font; body text in the sans-serif; code/timestamps/IDs in monospace
20. No card, row, or container uses a box-shadow for depth — only floating surfaces (modals, command palette) have shadows; all other depth is conveyed via borders
21. Red, amber, and green do not appear on any element that lacks a corresponding status meaning (no decorative status color)
22. Autodiscovered apps display an "auto-loaded" badge in both the sidebar entry and the app detail header
23. Blocked apps display their block reason text in a visible banner on the app detail page

## Dependencies and Assumptions

**Dependencies:**
- Font files for Newsreader, Geist, and Geist Mono (self-hosted — no CDN dependency since hassette runs as an HA addon)
- Shiki library for syntax highlighting in the Code tab (or an equivalent that supports server-side rendering of Python code)
- The existing OpenAPI schema generation pipeline (`scripts/export_schemas.py`) for keeping frontend types in sync with new backend models

**Assumptions:**
- The Preact + TypeScript + wouter + @preact/signals stack is retained without changes
- The existing WebSocket broadcast infrastructure (`RuntimeQueryService.broadcast()`) can handle the additional event volume with per-drain batching (one message per persist cycle, not per-invocation). No new debounce state is required — `broadcast()` is fire-and-drop with a 256-message queue per client and existing drop tracking.
- The telemetry database schema is not modified — session_id remains as a NOT NULL FK on invocation/execution tables, but the frontend stops sending it as a query parameter
- Vite continues as the build tool; no bundler migration

## Architecture

### Trade-offs of the chosen approach

The big-bang replacement optimizes for visual coherence (no period of mixed old/new design) and implementation simplicity (no shimming between two token systems). It sacrifices: merge safety (main branch changes during development may cause conflicts on rebase) and incremental user-facing feedback (no intermediate states on main). Mitigations: the dedicated worktree branch isolates risk from main development, backend changes are additive (no existing endpoints modified), and periodic rebases keep the branch current.

To preserve reviewability, work is split into multiple PRs that merge into the `new-ui` branch (not main). Each PR is self-contained and reviewable — e.g., "design tokens + component kit", "backend endpoints + WS events", "overview page", "app detail page", etc. The final merge from `new-ui` to main is one large diff, but the intermediate work is scoped and reviewed incrementally.

### Design Tokens

Replace `frontend/src/tokens.css` entirely with the Ink token system from `colors_and_type.css` in the design bundle. The new token naming convention:

- Surfaces: `--bg-page`, `--bg-surface`, `--bg-sunken`, `--bg-active`
- Text: `--ink-1` through `--ink-4` (primary → disabled)
- Borders: `--line-1`, `--line-2`, `--line-strong`
- Status: `--ok`, `--warn`, `--err`, `--mute` with paired `-bg` tints
- Accent: `--accent`, `--accent-ink`, `--accent-hover`, `--accent-soft`

Light theme is `:root` default. Dark theme via `[data-theme="dark"]`. Drop the `--ht-*` prefix convention — the new tokens are unprefixed (matching the design bundle).

Typography tokens reference Newsreader (display), Geist (body), Geist Mono (mono). Type scale: 38px display → 11px micro.

Update `design/context.md` to reflect the Ink design system tokens and direction.

### CSS Architecture

Rewrite `frontend/src/global.css` to implement the Ink component styles. Adopt the same component naming convention but with clean Ink styling (borders over shadows, Newsreader headings, Geist body text, shape-coded status indicators).

Retain the BEM-like class naming pattern (consider switching from `ht-` to a fresh prefix if desired, or keep `ht-` for continuity). All values must reference token custom properties — no raw hex or pixel values in component CSS.

### Frontend Component Structure

Retain the existing organizational pattern: components grouped by feature (`components/dashboard/`, `components/app-detail/`, `components/layout/`, `components/shared/`), pages in `pages/`, hooks in `hooks/`, state in `state/`. Co-locate tests with their components. The specific files created, deleted, and rewritten are defined in the individual work packages — the design doc does not prescribe exact filenames.

### Backend Additions

**New WS event types** in `src/hassette/web/models.py`:

- `InvocationCompletedWsMessage`: type="invocation_completed", payload includes listener_id, app_key, instance_index, status, duration_ms, error_type (if failed)
- `ExecutionCompletedWsMessage`: type="execution_completed", payload includes job_id, app_key, instance_index, status, duration_ms, error_type (if failed)

Emit via the existing BusService topic pattern — consistent with how `app_status_changed` and `service_status` events are already delivered. `CommandExecutor` emits a lightweight topic event (carrying `listener_id` / `job_id`) after persistence succeeds — both from the normal `_drain_and_persist()` path and from the FK-fallback path (`_handle_fk_violation()` → `persist_batch_with_fk_fallback()`), so recovered invocations also trigger real-time UI updates. `RuntimeQueryService` subscribes to these topics, resolves `app_key` and `instance_index` from its own `AppRegistry` reference, and broadcasts the enriched WS message. This keeps `CommandExecutor` unaware of the web layer (no new cross-service coupling) and places batching state in `RuntimeQueryService` where the broadcast machinery already lives. Note: `HandlerInvocationRecord` and `JobExecutionRecord` do not carry `app_key` or `instance_index` — `RuntimeQueryService` resolves these from the listener/job registry at broadcast time.

Both new message models must be added to the `WsServerMessage` discriminated union in `web/models.py` (the `TypeAdapter(WsServerMessage)` in `export_schemas.py` drives WS schema generation). On the frontend, `ws-types.ts` requires corresponding `interface` blocks and union members. The schema regeneration pipeline (`export_schemas.py` → `openapi-typescript`) handles the REST types automatically, but the WS types in `ws-types.ts` are hand-maintained and must be updated manually.

**New REST endpoints:**

- `GET /apps/{app_key}/config` in `src/hassette/web/routes/apps.py` — returns `AppManifest.app_config` (raw user-authored TOML values) for all app states including stopped/failed apps. Response model: `AppConfigResponse` with fields `app_key`, `filename`, `class_name`, `enabled`, `app_config` (the raw dict/list from the manifest). This endpoint returns user-provided configuration as-is and may contain sensitive data — the UI renders values redacted-by-default with a reveal toggle. No allowlist filtering (unlike the system `ConfigResponse`) because app config schemas are user-defined and opaque to the framework.
- `GET /apps/{app_key}/source` in `src/hassette/web/routes/apps.py` — reads file via `manifest.full_path` (the resolved absolute path, validated at manifest construction). Path traversal check validates that `manifest.full_path` resolves within `manifest.app_dir` (the per-manifest directory, not the global `config.app_dir`), which correctly handles auto-detected apps in subdirectories.
- ~~`GET /telemetry/slow-handlers`~~ — deferred (see FR#50). The existing `get_slow_handlers()` doesn't match the widget's needs.

**Time-window filtering:** Replace `session_id` with `since` (`float | None`, Unix epoch — matching the existing `since_ts` convention used by `get_error_counts()` and `get_recent_errors()`) on all telemetry route signatures and query methods. The `session_id` query parameter is removed from all routes entirely — nothing new we build should reference sessions. When `since` is provided, filter records with `timestamp >= since`. When absent, return unfiltered results. The frontend computes the `since` value from the selected preset (e.g., "Since restart" → `Date.now()/1000 - uptime_seconds`).

Six query methods are refactored from `session_id` to `since: float | None`: `get_listener_summary()`, `get_job_summary()`, `get_all_app_summaries()`, `get_global_summary()`, `get_handler_invocations()`, and `get_job_executions()`. Add a `_since_clause()` SQL helper (mirroring the existing `_source_tier_clause()` pattern) to keep the filter consistent across all methods. The existing `session_id` code paths in these methods are removed, not preserved alongside `since`.

**Session infrastructure retained for now:** The backend write path (`SessionManager`, `TelemetryRepository`, DB schema with `session_id` FK on `handler_invocations` / `job_executions`) continues to create sessions and stamp records internally. Full removal of backend session infrastructure (DB migration, SessionManager removal, reconciliation logic cleanup) is a follow-up effort. The goal of this redesign is to ensure nothing new depends on sessions, making that future removal clean.

### Session Removal

Remove sessions from the entire API surface (routes, query methods, WS messages). Backend write infrastructure (SessionManager, DB schema, telemetry repository) is retained for now — full backend removal is a follow-up effort.

**Frontend — delete:** `session-scope-toggle.tsx` + test, `session-scope.ts` + test, `pages/sessions.tsx` + test

**Frontend — modify:** Remove `sessionId` and `sessionScope` signals from `create-app-state.ts`. Remove session ID handling from `use-websocket.ts` connected handler. Rewrite `use-scoped-api.ts` to pass `since` instead of `session_id` (the loading gate blocks on `uptime_seconds` from the WS connected message). Remove `session_id` parameter from all functions in `endpoints.ts`. Remove `session_id` field from `ws-types.ts` connected payload type. Remove dead session exports from `endpoints.ts` (`getSessionList`, `SessionListEntry`).

**Backend — routes:** Remove `session_id` query parameter from all telemetry route signatures. Replace with `since: float | None`.

**Backend — query methods:** Refactor the 6 query methods to accept `since` instead of `session_id`. Remove the `session_id` SQL code paths.

**Backend — WS:** Stop sending `session_id` in the WS `connected` message. Remove the field from `ConnectedPayload`. Add `uptime_seconds: float` to `ConnectedPayload` — this replaces `session_id` as the loading gate for the frontend. The `use-scoped-api` hook blocks fetches until the WS connected message arrives (same pattern as today, new field), then computes the "Since restart" boundary from `uptime_seconds`.

**Backend — retained:** `SessionManager`, `TelemetryRepository` session writes, DB schema (`session_id` FK on invocation/execution tables), migration files — all untouched. These are removed in a dedicated follow-up.

**E2E:** Delete `test_sessions.py` and `test_session_toggle.py`. Remove `_default_scope_all` autouse fixture from conftest.

### Schema Regeneration

After backend model changes, run the existing pipeline:
1. `uv run python scripts/export_schemas.py` — regenerates `frontend/openapi.json` and `frontend/ws-schema.json`
2. `cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts` — regenerates TypeScript types

The pre-push hook (`tools/check_schemas_fresh.py`) validates freshness.

### Test Strategy

Three test layers, each with a distinct boundary:

**Component tests** (WP04–10): Individual component render + interaction via `@testing-library/preact` + Vitest + MSW. API calls are mocked at the HTTP boundary — MSW intercepts fetch requests and returns fixture data. These tests verify that components render correct content, respond to user interactions, and update signals correctly. They do NOT test backend behavior or real API integration. Each new or rewritten component ships with a co-located `.test.tsx` file. Test factories in `test/factories.ts` are extended with builders for new response types. MSW handlers in `test/handlers.ts` are updated for new endpoints.

**Backend integration tests** (WP02–03): Route-level tests against the real FastAPI app with a mock hassette stub (`create_hassette_stub()`). These tests verify endpoint contracts (correct status codes, response shapes, error handling), query method behavior (the `since` parameter filters correctly, `timed_out` appears in responses), and WS message delivery (completion events broadcast with correct payloads). They do NOT test frontend rendering or user workflows.

**E2E tests** (WP11): Full browser tests via Playwright against a live uvicorn server with mock fixtures. These tests are the only layer that verifies complete user workflows spanning frontend + backend: dashboard renders correct state → click app in sidebar → handler detail loads with real-time updates → log filtering works. The session-scoped mock fixture infrastructure (`mock_fixtures.py`, `conftest.py`) is retained and extended. Seed data builders are updated for new endpoints and response shapes.

**What automated tests do not cover:** Visual design compliance — correct token usage, font rendering, spacing, status shape appearance, contrast ratios. These are verified by visual review via screenshot comparison during implementation (Visual Verification sections in WPs) and the pre-ship Playwright screenshot pass.

**Cross-boundary flow not unit-testable:** The real-time update pipeline (invocation completes → bus topic → RuntimeQueryService resolves app_key → WS broadcast → frontend signal → debounced refetch → table updates) spans 6 components across backend and frontend. Component tests with MSW verify the frontend half (signal fires → refetch → render). Backend integration tests verify the backend half (persist → topic → broadcast). Only E2E tests verify the full flow end-to-end.

## Alternatives Considered

### Incremental migration (page by page, merging to main)

Swap design tokens first, then migrate one page at a time, merging each as a separate PR to main. This allows earlier user-facing feedback and smaller diffs but creates a prolonged period of visual inconsistency on main where some pages use the old design and others use the new. Given the depth of the token changes (different font families, different color vocabulary, different spacing scale), partial migration would look broken rather than "in progress." The chosen approach gets the best of both: incremental PRs for reviewability (merged into the `new-ui` branch), with a single clean swap to main when everything is ready.

### Retain Graphite+Emerald with incremental feature additions

Add the missing surfaces (events, config, code tabs) and fix the reactivity gaps without changing the visual design. This would be less effort but misses the opportunity to build a cohesive design system. The current design was explicitly a first pass — the Ink system was designed intentionally for this domain with proper mood exploration, typography pairing, and status-color vocabulary. Shipping features on the old design would mean redesigning them again later.

### Adopt CSS modules or Tailwind

Replace the global CSS architecture with CSS modules (scoped class names per component) or Tailwind (utility classes). Either would provide better isolation and reduce the cost of future redesigns. However, migrating the CSS architecture simultaneously with the visual redesign and feature additions would triple the scope. The current global CSS pattern works — it's the same pattern the prototype uses — and can be migrated independently in a future effort.

## Documentation Updates

- **`design/context.md`**: Update to reflect the Ink design system — new token names, new font families, new color vocabulary, new component patterns
- **`CLAUDE.md`**: Update the "Frontend in Worktrees" section if any build process changes. Update font references in any existing documentation.
- **`docs/` site**: No user-facing documentation changes — the UI is self-explanatory and the docs site covers the Python API, not the monitoring UI

## Impact

### Files affected

**Frontend (complete rewrite):**
- `frontend/src/tokens.css` — new Ink tokens
- `frontend/src/global.css` — new component styles (~2265 lines rewritten)
- All 36 `.tsx` component/page files — rebuilt to match Ink design
- All ~50 `.test.tsx` files — rewritten for new components
- `frontend/src/state/create-app-state.ts` — session removal, new signals
- `frontend/src/hooks/` — 6 hooks modified or rewritten
- `frontend/src/api/endpoints.ts` — new endpoints, session param removal
- `frontend/src/api/ws-types.ts` — new event types, session removal
- Font asset files — swap to Newsreader, Geist, Geist Mono

**Backend (additions):**
- `src/hassette/web/models.py` — new WS message models, new response models
- `src/hassette/web/routes/apps.py` — new config and source endpoints
- `src/hassette/web/routes/telemetry.py` — new slow-handlers endpoint, `since` parameter
- `src/hassette/core/command_executor.py` — emit new WS events after persist
- `src/hassette/core/runtime_query_service.py` — broadcast new event types
- `frontend/openapi.json` — regenerated
- `frontend/ws-schema.json` — regenerated

**Tests:**
- `tests/e2e/` — 15 test files rewritten (~2979 lines)
- `tests/e2e/mock_fixtures.py` — extended with new seed data
- Frontend component tests — ~50 files rewritten

**Deleted:**
- `frontend/src/components/layout/session-scope-toggle.tsx` + test
- `frontend/src/components/layout/bottom-nav.tsx` + test
- `frontend/src/utils/session-scope.ts` + test
- `frontend/src/pages/sessions.tsx` + test
- `tests/e2e/test_sessions.py`
- `tests/e2e/test_session_toggle.py`

### Issues closed

**Definitively closed:** #387 (real-time updates), #488 (app instance config), #539 (expose config), #577 (split log-table), #654 (telemetry drop counters)

**Likely closed:** #346 (run-now button), #345 (per-app log level), #521 (deduplicate errors), #556 (surface API errors), #639 (service readiness), #652 (structured error summaries)

**Closed as obsolete:** #468 (session toggle greying), #493 (session/current endpoint), #522 (sessions page improvements)

### Blast radius

This is a large change touching the entire frontend, 5-6 backend files, and the full E2E test suite. The dedicated worktree branch isolates risk from main development. The backend changes are additive (new endpoints, new WS events) — no existing endpoints are modified or removed. The `session_id` query parameter is removed from all telemetry routes and replaced with `since`. Backend session write infrastructure is retained but nothing new references it.

## Open Questions

None — all questions resolved during discovery. The Events inspector page and CSS architecture migration are explicitly deferred as separate efforts.
