## Codebase Audit (feature wave 8b9390d..3c40430) — 2026-03-16

### 1. Scheduler API ignores `instance_index` filter — CRITICAL
`web/routes/scheduler.py:42-44` — `/scheduler/jobs` accepts `instance_index` param but never uses it in filtering. Multi-instance apps return jobs from all instances. Bus equivalent handles this correctly.

### 2. Hardcoded `instance_index=0` in app detail partials — CRITICAL
`web/ui/partials.py:136,147` — `app_detail_listeners_partial` and `app_detail_jobs_partial` hardcode `instance_index=0`. Referenced in `app_instance_detail.html` for initial page load. Live HTMX updates use correct instance-aware endpoints.

### 3. Polling-based `wait_for_ready` race window — HIGH
`utils/service_utils.py:8-39` (bug #314) — 100ms polling loop instead of event-based waits. Creates timing-dependent race windows. 5 call sites across CommandExecutor, StateProxy, WebApiService.

### 4. ServiceWatcher doesn't validate readiness after restart — HIGH
`service_watcher.py:177-189` (bug #315) — Listens for RUNNING status but never checks `mark_ready()`. Service that crashes between RUNNING and ready appears recovered but is stuck.

### 5. No coordination for cascading service failures during shutdown — HIGH
Bug #318 — CommandExecutor correctly flushes in normal path, but abnormal shutdown sequences can trigger RuntimeError from submit() if DatabaseService shuts down first.

### 6. No migration downgrade test — MEDIUM
`migrations/versions/001_initial_schema.py` — Upgrade path tested; downgrade never exercised.

### 7. Sentinel ID filtering untested — MEDIUM
`command_executor.py:503-518` — Records with listener_id=0 or session_id=0 silently dropped (correct), but no test verifies this under startup race conditions.

### 8. Inconsistent `mark_ready` timing across services — MEDIUM
Some services mark ready in `on_initialize()` (early), others in `serve()` (late). No documented pattern for when to use which.

## Design Challenge (ui-rebuild PR) — 2026-03-20

### 1. SQL query duplication is a schema-drift time bomb — CRITICAL
Every query method in `TelemetryQueryService` has two full independent SQL copies (session-filtered vs all-time). 5 methods × 2 variants. Fix: `_session_clause()` helper.

### 2. Stats poll DOM mutation is architectural debt — CRITICAL
`live-updates.js:146-218` does 70 lines of manual DOM patching, finds elements by text content substring ("avg") and CSS class names. Fix: `data-stat` attributes, then push via WebSocket.

### 3. `get_recent_errors` returns `list[dict]` — typed model system incomplete — CRITICAL
Three methods bypass the typed model protection the PR introduced. Merged handler+job errors use a `kind` string key. Fix: discriminated union models.

### 4. `context.py` is a god module — HIGH
176 lines mixing CSS classification, string formatting, async data fetching, template context building, and session ID access. Fix: split into classifiers/formatters/context.

### 5. Phased startup is a symptom fix — three defense layers for one invariant — HIGH
`_safe_session_id()` returns 0, `_do_persist_batch()` drops id=0 records. Fix: inject session_id as a value or buffer records until available.

### 6. `db_id is None` dispatch bifurcation — hidden protocol in two services — HIGH
Both BusService._dispatch and SchedulerService.run_job branch on db_id. TOCTOU race for regular listeners. Fix: make CommandExecutor own the decision.

### 7. Dashboard 5 sequential async DB calls — MEDIUM
`router.py:27-32` — independent queries run sequentially. Fix: `asyncio.gather`.

### 8. `_execute_handler`/`_execute_job` identical 80-line methods — MEDIUM
Same timing/exception/queue pattern, different record type. Fix: Template Method with record factory.

### 9. WebSocket delivers status instantly, stats poll lags 5s — MEDIUM
Consistency violation: status dot goes green before counts update. Fix: push stats through existing WS channel.

### 10. `TelemetryQueryService` reads from write connection — MEDIUM
Same aiosqlite connection for reads and writes. Fix: separate read-only connection for WAL mode.

### 11. 501 placeholder routes ship as API surface — MEDIUM
Three POST routes return 501. Premature URL commitment. Fix: remove routes, render disabled buttons.

### 12. `reschedule_job` bare `assert` on time source — MEDIUM
`scheduler_service.py:287` — crashes or silently drops job on DST transition. Fix: runtime guard with fallback.

### 13. Paired route duplication in partials.py — MEDIUM
6 endpoint pairs doing identical work, differing only in path vs query param. Fix: collapse into single routes.

### 14. Health strip over-fetches full summaries for 4 scalars — MEDIUM
Fetches all listener/job fields, reduces to 4 values in Python. Fix: dedicated aggregate query.

### 15. `safe_session_id` catches `AttributeError` — MEDIUM
Masks misconfiguration bugs. `command_executor.py` equivalent catches only `RuntimeError`. Fix: catch only `RuntimeError`.

## Preact SPA (Visual QA + Code Challenge) — 2026-03-20

### CRITICAL

### 0. Preact components don't match the CSS design system's expected HTML structure — CRITICAL
The entire UI looks like flat text in boxes. The CSS in `global.css` (copied from `style.css`) was written for the Jinja2 templates' specific DOM structure — nested `<div>` hierarchies, specific element types, SVG icons, etc. The Preact components use simpler/different markup that doesn't match the CSS selectors, so styles silently don't apply. Affects EVERY page. The sidebar uses Unicode characters (⊞ ⬡ ≡) instead of SVGs and is collapsed into a tiny horizontal row instead of a vertical icon rail. Stat cards lack internal structure. App cards are flat text with a border. Health bars, pulse dot animation, card depth — all missing. Fix: audit every component against the old Jinja2 templates and match the HTML structure the CSS expects, or rewrite the CSS to match the new markup. This is the single highest-priority item — nothing else matters visually until this is fixed.

### 1. `useWebSocket` reconnect loop on unstable `options` reference — CRITICAL
`useEffect` depends on `[state, options]`. Passing `onReconnect` creates new object every render → infinite reconnect. Currently masked because `WebSocketProvider` passes no options. Fix: accept `onReconnect` as standalone param, store in `useRef`.

### 2. `useApi` never refetches when route params change — CRITICAL
`refetch` is a `useRef` constant — fires once on mount. Navigating between `/apps/a` and `/apps/b` shows stale data. Fix: accept dependency array, include in `useEffect` deps.

### HIGH

### 3. Dashboard refetch storm on WS events — CRITICAL (upgraded from HIGH)
Every `app_status_changed` creates new `appStatus` object → triggers `refetchAppGrid()`. 20 apps × 2 transitions = 40+ undebounced requests on startup. No AbortController anywhere. Confirmed by 3 independent critics. Fix: debounce 500ms + AbortController, or patch grid entries from WS payload directly.

### 4. Log table duplicates entries (REST + WS overlap) — CRITICAL (upgraded from HIGH)
`[...initialEntries, ...wsEntries]` concatenates without dedup. No unique ID in LogEntry or WsLogPayload. Activates the moment WS log subscribe is fixed (#23). Confirmed by 3 critics. Fix: use REST response's latest timestamp as watermark, or skip REST and backfill via WS.

### 5. `unknown[]` and `as never` casts defeat type safety — HIGH
`getAppJobs`, `getHandlerInvocations`, `getJobExecutions` return `unknown[]`. Components cast with `as never`. Fix: type with proper interfaces.

### 6. `onReconnect` not wired — stale data after WS reconnection — HIGH
Design doc requires reconnection to trigger page-level data refresh. Implementation ignores it. Fix: wire after fixing #1.

### 7. `useRef(signal(...))` reinvents `useSignal()` — HIGH
Pattern appears 17 times. `@preact/signals` provides `useSignal()`. Fix: replace all instances.

### 8. No CSS Modules — design doc deviation — HIGH
Zero `.module.css` files. All 1,691 lines in `global.css`. Design doc mandates dual strategy.

### 9. Dashboard card text concatenation bug — HIGH
App cards show "0 handlers2 jobs2m ago" with no spacing. Fix AppCard component flex layout.

### 10. Handler/job count mismatch (session vs all-time) — HIGH
Summaries session-scoped, drill-down all-time. No label distinguishes them. Fix: add "(this session)" or scope drill-down.

### MEDIUM

### 11. `ErrorBoundary` wraps router, not individual pages — MEDIUM
One crash blanks the entire app. Design doc says "wraps each page". Fix: wrap each `<Route>` child.

### 12. Action buttons fire-and-forget — no feedback — CRITICAL (upgraded from MEDIUM)
Start/stop/reload: no catch, no post-action state change, no optimistic UI, no refetch. Error silently swallowed. Between API response and WS event, UI in limbo. Confirmed by 3 critics. Fix: optimistic status ("stopping...") + catch errors + refetch on success.

### 13. `AlertBanner` defined but never rendered — HIGH (upgraded from MEDIUM)
Component exists but not used. Primary safety mechanism for failed apps disconnected. Data available in `appStatus` signal. Confirmed by 3 critics. Fix: wire into `app.tsx` between StatusBar and Switch.

### 14. Theme not persisted from localStorage — HIGH (upgraded from MEDIUM)
`create-app-state.ts:31` hardcodes `signal("dark")`. `status-bar.tsx` writes localStorage on toggle but never reads on init. Theme resets every load. Confirmed by 2 critics. Fix: initialize from `localStorage.getItem("ht-theme")` in `createAppState()`.

### 15. Handler names show raw Python paths — MEDIUM
70+ char fully-qualified paths. Fix: show method name only, full path on hover.

### 16. No Enable button for disabled apps — MEDIUM
Dead end for users. Needs new API endpoint + button.

### 17. Single accent color overloaded — MEDIUM
Mint green marks everything. Fix: semantic color differentiation.

### 18. Dashboard card hover nearly invisible — MEDIUM
No visual feedback on clickable cards. Fix: visible hover state.

### LOW

### 19. Page headings oversized — LOW
"Dashboard" / "Apps" are largest text but least useful. Reduce 30-40%.

### 20. Stat card inconsistent structure — LOW
Varying line counts, no hierarchy. Standardize internal layout.

### 21. Horizontal overflow on expanded rows — LOW
ERRORS column truncates. Adjust column widths.

### 22. "1 entries" pluralization bug — LOW
Fix: conditional pluralization in log-table.tsx.

## Architecture Challenge (3-critic adversarial review) — 2026-03-21

### 23. WS log streaming never sends subscribe message — CRITICAL
Frontend WS never calls `socket.send()`. Server starts with `subscribe_logs: False` (`ws.py:91`) and only enables on `{"type":"subscribe","data":{"logs":true}}` (`ws.py:51-55`). All log messages silently dropped (`ws.py:72`). `log-table.tsx:29` comment admits unimplemented. Real-time log streaming — primary SPA justification — does not function. Fix: expose `send()` from WS hook, send subscribe on LogTable mount.

### 24. AppDetailPage fetches ALL manifests for ONE app — CRITICAL
`app-detail.tsx:43` calls `getManifests()` (full list), `.find()` on line 48. O(N) for O(1). Not shared with apps page. Confirmed by 3 critics. Fix: add `GET /api/apps/{key}/manifest` or lift manifests to shared state.

### 25. REST/WS data consistency has no reconciliation layer — CRITICAL
Dashboard refetches app grid on WS events but NOT KPIs or errors. App detail never refreshes after mount. Manifest list patches status from WS but all other fields stale. Confirmed by 3 critics. Fix: WS-driven invalidation (mark domains as stale) or server-pushed snapshots.

### 26. Loading gate uses `&&` instead of `||` — HIGH
`app-detail.tsx:53`: `health.loading.value && listeners.loading.value` — spinner disappears when FIRST request finishes, not last. Same bug in `dashboard.tsx:32`. Content jumps as remaining data arrives. Fix: change to `||`.

### 27. Unguarded JSON.parse in WS handler — HIGH
`use-websocket.ts:36` — no try/catch. Malformed message throws → onerror → socket.close() → reconnect cycle. Schema drift between frontend/backend versions becomes crash vector. Confirmed by 2 critics. Fix: wrap onmessage body in try/catch, log and drop bad messages.

### 28. Stale relative timestamps never update — HIGH
`formatRelativeTime` computes against `Date.now()` at render time. No timer forces re-render. "2m ago" stays "2m ago" forever. Dangerous for monitoring dashboard — can't distinguish idle from dead. Fix: global "tick" signal that increments every 30-60s.

### 29. Handler/job invocations cached forever on expand — MEDIUM
`handler-row.tsx:30` / `job-row.tsx:33` — `loaded` signal prevents refetch after first expand. Re-expanding shows stale data. Comment calls this "THE KEY ARCHITECTURAL WIN" but it's a data freshness bug for a monitoring tool. Fix: always refetch on expand, or add staleness timer.

## Code Quality Challenge (3-critic review, code focus) — 2026-03-21

### 30. Dead CSS ~40% of global.css + 8 missing CSS classes used in TSX — HIGH
~650 lines of htmx-era CSS unreferenced. Simultaneously, `.ht-spinner`, `.ht-text-mono`, `.ht-btn-primary`, `.ht-btn--link`, `.ht-alert-danger`, `.ht-alert-list`, `.ht-sortable`, `.ht-error-entry*` used in TSX but not defined in CSS. Silent visual bugs. Fix: strip dead CSS, fix BEM names.

### 31. Instance switcher uses window.location.href — full page reload in SPA — MEDIUM
`app-detail.tsx:104` — navigates via `window.location.href`, abandoning all client state (WS, logs, expanded rows). Fix: use wouter's `useLocation` for client-side navigation.

### 32. ErrorBoundary traps navigation — user stuck on error screen — MEDIUM
`error-boundary.tsx:19` — error state blocks all children, no route-change detection. Sidebar clicks invisible. Fix: reset error state on route change.

### 33. SVG icons duplicated across 5+ files (~60 lines) — MEDIUM
Same Lucide icons inlined verbatim in `app-detail.tsx`, `logs.tsx`, `apps.tsx`, `sidebar.tsx`, `dashboard.tsx`. Fix: shared `icons.tsx` module.

### 34. Status-to-variant mapping duplicated 3x with different naming — MEDIUM
`status-badge.tsx`, `app-card.tsx`, `health-strip.tsx` each independently map status to CSS variant. Adding a new status requires finding all three. Fix: single `status-variant.ts` utility.

### 35. RingBuffer mutation + version signal is fragile implicit contract — MEDIUM
`create-app-state.ts:25-28` — mutable buffer paired with manual `version++` notification. Forgetting to increment = silent render bug. Fix: encapsulate in a single `push()` that atomically updates both.

### 36. Backend dictates CSS class names via error_rate_class/health_status — LOW
`endpoints.ts:53` — server string used directly as CSS class. Backend rename = silent style breakage. Fix: map server values to typed frontend enum at API boundary.
