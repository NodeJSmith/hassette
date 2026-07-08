# Frontend Visual QA Working Brief

**Date:** 2026-07-08
**Status:** working
**Scope:** Hassette frontend, live demo stack, desktop light screenshots plus serial persona walkthroughs
**Context:** `design/context.md`

## Purpose

Capture the current frontend polish/readability/usability findings before making code changes. This is a working brief, not an implementation plan. Use it to group findings, decide priorities, and define focused follow-up batches.

## Review Inputs

- Live demo stack: `scripts/hassette_demo.py`
- Screenshot capture directory: `/tmp/claude-ui-qa-jf2bSk/shots`
- Generated docs screenshots used as fallback for logs when live screenshot capture timed out
- Personas:
  - Devon: power user debugging `sensor_health_check`
  - Riley: new user confirming health and understanding app behavior
  - Morgan: mobile responder finding what broke and whether they can stop it

## Current Direction

The UI already has a coherent direction: a quiet, compact troubleshooting console for Home Assistant automation operators. The cleanup should refine hierarchy, scanability, and evidence flow without turning Hassette into a consumer smart-home dashboard or a generic SaaS dashboard.

Keep:

- Dense operational tables
- Calm graphite/green visual language
- App Detail as the diagnostic hub
- Code/config/log visibility
- Serif titles as a distinctive accent
- Shared component system as the source of visual consistency

Improve:

- First-read hierarchy
- Evidence links between failures, handlers, executions, logs, code, and config
- Mobile overflow and touch affordances
- New-user explanations for health, zero activity, and core terms
- Table scanability under dense data

## High-Confidence Findings

### 1. Evidence Trail Breaks At Logs

**Pages:** Logs, app logs tab, log detail, handler detail

**Observed:** Handler detail is strong: it shows status, exception, traceback, execution rows, counts, registration, and code link. The weak direction is the reverse path. Starting from a log detail, the app/function/execution fields do not take the user directly back to the relevant handler detail or execution context.

**Persona evidence:** Devon completed the debug story but had to manually return from logs to the handler page. Morgan found the failing app from logs, then had to open app detail and handler detail to get the exact exception.

**Why it matters:** The signature Hassette pattern should be an evidence trail. Logs are evidence, but currently behave too much like a terminal output surface instead of a connected diagnostic surface.

**Potential fixes:**

- Link log detail `FUNCTION` to the corresponding handler/job detail when resolvable.
- Link `EXECUTION` to the corresponding execution row/detail when resolvable.
- Add an explicit `View failing handler` or `View execution` action in log detail for error rows.
- Preserve context when navigating from handler detail to logs: app, function/handler, execution ID, or a narrow time window around the selected execution.

### 2. Health Status Is Ambiguous For Running Apps With Recent Errors

**Pages:** Apps, app detail overview

**Observed:** The Apps summary can show `failed = 0` while a running app has a recent error in the `last error` column. Riley could not tell whether this means healthy, recovered, degraded, or needs action.

**Why it matters:** The UI should lead with the diagnostic answer. `running` plus a recent error is operationally meaningful and should not require interpretation.

**Potential fixes:**

- Distinguish lifecycle status from recent execution health.
- Add a state such as `running with recent errors`, `error recovered`, or `degraded` where appropriate.
- In app rows, make recent error timestamp and action clearer: `last error just now`, `view handler`, `view logs`.
- In stats strips, avoid implying all running apps are equally healthy.

### 3. Zero-Activity States Are Under-Explained

**Pages:** Apps, handlers, app detail overview

**Observed:** Running apps can show `0` and `—` for runs/last fired. New users cannot tell whether this is normal waiting, no matching events, a disabled handler, or broken telemetry.

**Why it matters:** Hassette is diagnostic. Empty or zero states should explain what the absence of activity means.

**Potential fixes:**

- Replace bare `—` with contextual states where possible: `waiting for first trigger`, `no runs in window`, `next run in 23h`, `never fired since restart`.
- Add tooltips or muted explanatory text for zero-run handlers/jobs.
- Show scheduled next-run data more prominently when it explains inactivity.

### 4. Mobile Overflow In Diagnostic Detail Views

**Pages:** App detail overview, handler detail

**Observed:** Morgan found horizontal overflow in recent activity and handler registration/source content at 375px. Long source paths and code snippets clip past the viewport.

**Why it matters:** Mobile is for quick checks. Users should be able to identify the failing automation, error, last fired time, and stop/reload actions without horizontal scrolling.

**Potential fixes:**

- Convert recent activity table to stacked mobile rows.
- Wrap or collapse long source paths.
- Make code/registration blocks horizontally scroll within their own containers without widening the page.
- Ensure handler detail metadata uses a mobile-safe stacked layout.

### 5. Logs Page Performance/Responsiveness Needs Investigation

**Pages:** Logs

**Observed:** Live screenshot capture timed out repeatedly on `/logs`. Riley’s walkthrough reported the logs page became effectively unresponsive while filtering for `security_monitor`.

**Why it matters:** Logs are central evidence. If logs are slow or difficult to filter, users lose the evidence trail.

**Potential fixes:**

- Reproduce with performance instrumentation before fixing.
- Check whether full-page screenshots hang because of live updates, font waits, virtual height, sticky elements, or too much DOM.
- Consider throttling live updates during active filtering.
- Consider virtualization or row limits if DOM size is high.
- Make noisy demo sources easier to filter/group so quiet app activity is not buried.

### 6. Handlers Table Is Dense To The Point Of Weak Scanability

**Pages:** Handlers

**Observed:** The table exposes many narrow columns with similar emphasis. Some headers/content feel cramped or clipped. Users get data, but not a strong scan path.

**Why it matters:** Dense is acceptable; crowded is not. The table should prioritize the diagnostic columns.

**Potential fixes:**

- Combine low-frequency failure fields into one compact health/status cell.
- Rebalance column widths around app/name/trigger and status/failure.
- Make primary identity and current health easier to scan per row.
- Preserve full details in row detail or app-scoped handler pages.

### 7. App Detail Overview Has Good Content But Weak Narrative Hierarchy

**Pages:** App detail overview

**Observed:** Failing handlers, handler health, recent activity, and logs are all present. The page works, but sections feel stacked rather than connected into a diagnostic story.

**Why it matters:** App Detail is the center of gravity. When failures exist, the page should make the answer obvious first, then show supporting evidence.

**Potential fixes:**

- Give active failures a stronger diagnostic panel with handler name, exception, count, last occurrence, and direct actions.
- Visually tie failure summary, handler card, recent activity rows, and log rows together through labels or links.
- Consider auto-selecting the highest-priority failing handler on the handlers tab instead of showing an empty detail pane.

### 8. App Detail Handlers Is Strong But Needs Answer-First Restructuring

**Pages:** App detail handlers tab, handler/job detail view

**Observed:** The handlers page is one of the strongest diagnostic surfaces in the app. It puts registration, current health, execution history, traceback, stats, run action, and code link in one place. The issue is not that the detail exists; the issue is that the hierarchy can feel like a dense technical dossier rather than an answer-first investigation flow.

**Why it matters:** A lot of detail is appropriate for Hassette, but the page should guide the user from diagnosis to evidence. The user should not need to visually parse every section to understand the current state of the selected handler/job.

**Likely direction:** Keep the two-pane diagnostic workstation, but restructure the right pane around the question: `What is this handler/job doing, and is it healthy?`

**Potential fixes:**

- Auto-select the highest-priority handler/job by default: failing first, otherwise most recently active.
- Put the answer at the top of the detail pane: kind, name, health, last run, current error if any, and next action.
- Order evidence sections from most diagnostic to most implementation-specific:
  - last failure or last run summary
  - execution history
  - logs for selected execution or handler
  - traceback when relevant
  - registration/source/code
  - config/group/schedule metadata
- Move registration code lower or collapse it by default when it is not the primary answer.
- Make execution rows expand or link to logs/traceback more explicitly.
- Preserve density, but use stronger section hierarchy and labels so users can scan without reading every value.

### 9. App Detail Overview Should Be The Triage Page

**Pages:** App detail overview tab

**Observed:** The overview page has the right ingredients: failure summary, handler health cards, recent activity, and logs. It currently reads as stacked modules rather than a guided app-level diagnosis.

**Why it matters:** The overview should answer `What is going on with this app?` before the user chooses a deeper tab. It should not duplicate the full handlers page, but it should point clearly to the right investigation path.

**Likely direction:** Make Overview the triage page and Handlers the investigation page.

**Potential fixes:**

- Add or strengthen an app health verdict at the top: `Healthy`, `Running with recent failures`, `Stopped`, `Blocked`, `Telemetry degraded`.
- Show a `Needs attention` panel only when relevant, with failing handler, exception, last occurrence, failure count, and direct links.
- Add an activity summary: last fired, runs in selected window, success rate, next scheduled job.
- Keep handler/job health cards, but let failures dominate visually.
- Treat recent activity and logs as supporting evidence, not equal-weight modules.
- Make the page's next actions obvious: view failing handler, view logs around failure, view code, stop/reload app.

### 10. App Detail Page Roles Should Be Explicit

**Pages:** App detail overview, handlers, logs, code, config

**Proposed mental model:**

- Overview answers: `What is going on with this app?`
- Handlers answers: `What exactly happened inside this handler/job?`
- Logs answers: `What was happening around that time?`
- Code answers: `Where is this behavior implemented?`
- Config answers: `Why is it configured this way?`

**Why it matters:** This separation lets the UI keep detail without making every tab compete to be the primary diagnostic surface. It also gives future visual cleanup a rubric: each tab should emphasize the evidence appropriate to its role.

### 11. Config Page Reads Like A Raw Dump

**Pages:** Config, app config tab

**Observed:** The config page is structured but visually exhausting. Rows have similar weight, and the page lacks a summary of what matters.

**Why it matters:** Config should be an evidence surface, not a raw dump.

**Potential fixes:**

- Add a compact page summary: config file, env file, data dir, prod/dev mode, warnings/non-defaults.
- Add sticky search or section navigation.
- Emphasize overridden, secret, empty, not-set, and non-default values differently.
- Strengthen section hierarchy.

### 12. Diagnostics Page Is Underpowered Compared To The Rest Of The UI

**Pages:** Diagnostics

**Observed:** The diagnostics page currently shows a stats strip and a grid/list of internal services with green dots. It is calm and technically correct, but it feels thin compared to Apps, Handlers, Logs, and App Detail. It does not explain what framework health means, what each service is responsible for, what could go wrong, or what evidence would appear if something were degraded.

**Why it matters:** Diagnostics should be the framework-level equivalent of App Detail: the place users go when Hassette itself feels wrong. Right now it mostly answers “are service objects running?” but not “is the framework healthy?” or “what subsystem should I investigate?”

**Likely direction:** Reframe Diagnostics as a system health command center, not a service inventory.

**Potential fixes:**

- Add a clear top-level verdict: `Framework healthy`, `Telemetry degraded`, `Service failed`, `Boot issues detected`, or similar.
- Group services by subsystem instead of showing one flat list: runtime, event bus, scheduler, telemetry/database, web/API, Home Assistant connection, file watching.
- For each group, show the useful operational signal: running count, recent restarts, queue/backpressure status, last error, dropped events, database/write health, websocket state.
- Make the current all-green state more meaningful with copy like `All 22 framework services are running; no boot issues or dropped telemetry detected since restart.`
- Add an “If something is wrong” evidence area that appears only when degraded: failed service, error message, last restart, log links, affected apps if known.
- Keep the raw service list, but demote it below grouped health summaries or put it in an expandable/details section.
- Add tooltips for `boot issues`, `drops`, and each subsystem group.
- Consider making Diagnostics the place where framework-level logs and telemetry health connect, analogous to app detail for app-level evidence.

### 13. New-User Terminology Needs Lightweight Support

**Pages:** Handlers, diagnostics, app detail

**Observed:** Riley encountered terms like handlers, jobs, invocations, cancelled, drops, and services without a plain-language model.

**Why it matters:** The UI can stay technical, but day-one users need enough orientation to know whether values are good or bad.

**Potential fixes:**

- Add short page intro text where it helps, not everywhere.
- Add glossary tooltips for core terms.
- Add healthy-state banners like `Framework healthy` on Diagnostics.
- Explain expected zero/empty states instead of leaving bare symbols.

### 14. Chips And Badges Need A Visual Cleanup Pass

**Pages:** Apps, handlers, app detail, config, sidebar

**Observed:** Chips and badges carry important state and metadata: `running`, `stopped`, `auto`, `no autostart`, trigger types, groups, status kinds, booleans, not-set values, and failure labels. They are structurally componentized, but visually they can still feel inconsistent in weight, tone, and priority. Some badges read as primary status, some as quiet metadata, and some as implementation details, but the visual language does not always make that distinction obvious.

**Why it matters:** Chips and badges are one of the main ways users scan Hassette. If every small pill has similar visual weight, the UI becomes harder to read even when the layout is tidy.

**Potential fixes:**

- Audit every `Badge` and `Chip` variant in real screenshots, not just component code.
- Define clear roles: lifecycle status, execution health, trigger kind, source/origin, config boolean, optional metadata, and warning/failure annotation.
- Make lifecycle/health badges visually stronger than metadata chips.
- Make low-priority metadata chips quieter and more compact.
- Ensure error/failure chips are visually distinct from ordinary red text.
- Confirm `auto`, `no autostart`, `not set`, boolean `true`/`false`, and trigger-kind chips have consistent tone and meaning.
- Check light/dark contrast and whether chip borders/backgrounds are too subtle or too noisy.

### 15. Explanatory Tooltips Are Missing From Metrics And Terms

**Pages:** Apps, handlers, app detail, diagnostics, config

**Observed:** Several metrics and labels require domain knowledge: success rate, error rate, runs, invocations/calls, timed out, cancelled, next run, drops, boot issues, source tier, and not-set config values. Some config rows have info icons, but the metric-heavy pages often do not explain how values are calculated or what time window they use.

**Why it matters:** Hassette can stay dense if users can ask the UI what a value means. Tooltips let expert users keep density while giving new or tired users a recovery path.

**Potential fixes:**

- Add tooltips to stat-strip metrics such as `Success Rate`, `Failed`, `Runs`, `Runs / hr`, `Boot Issues`, and `Drops`.
- Explain calculation windows: since restart vs 1h/24h/7d.
- Explain formulas, e.g. `Success rate = successful executions / total executions in the selected time window`.
- Explain zero/empty states in tooltip copy when inline text would be too verbose.
- Prefer a shared `InfoPopover` or tooltip component instead of one-off title attributes.
- Make tooltip triggers keyboard-accessible and usable on mobile, likely via tap-to-open info buttons for important metrics.
- Keep tooltip copy short and operational: what it means, how it is calculated, and what to do if it looks wrong.

## Potential Work Batches

### Batch A: Evidence Trail

Goal: Make failures navigable from any evidence surface.

Candidate tasks:

- Link log detail function/execution fields to handler/execution context.
- Add explicit log-detail actions for error rows.
- Preserve handler/execution context when navigating to logs.
- Improve failing handler summary actions.

### Batch A2: App Detail Information Architecture

Goal: Clarify overview as triage and handlers as investigation without removing useful detail.

Candidate tasks:

- Strengthen app overview health verdict and needs-attention panel.
- Reorder handler detail sections around answer-first flow.
- Auto-select failing/most relevant handler on the handlers tab.
- Make selected execution/log/traceback relationships explicit.
- Define tab roles in code/design docs so future additions do not blur them.

### Batch B: Mobile Diagnostic Safety

Goal: Make the core failure-debug path work at 375px without overflow.

Candidate tasks:

- Stack recent activity rows on mobile.
- Contain registration/code/path overflow.
- Improve mobile logs filter affordance.
- Verify stop/reload remains reachable.

### Batch C: Health Semantics

Goal: Clarify healthy vs running vs recently errored vs inactive.

Candidate tasks:

- Separate lifecycle and execution health in app rows.
- Add `running with recent errors` or similar state language.
- Replace bare zero/empty symbols with explanatory states.
- Tune stats strip emphasis rules.

### Batch D: Dense Table Readability

Goal: Improve scanability without reducing useful density.

Candidate tasks:

- Rework handlers table column priority.
- Improve logs grouping/filtering responsiveness.
- Tune row/link emphasis in dense tables.

### Batch E: Config/Diagnostics Orientation

Goal: Make config and diagnostics self-explanatory without becoming verbose.

Candidate tasks:

- Add config summary/search/section anchors.
- Redesign Diagnostics around grouped system health rather than a flat service inventory.
- Add diagnostics healthy/degraded verdicts and subsystem summaries.
- Add lightweight term explanations.

### Batch F: Chip/Badge Visual System

Goal: Make small status and metadata markers easier to scan and semantically consistent.

Candidate tasks:

- Inventory current Badge/Chip usages across screenshots and TSX.
- Define role-based visual levels for status, health, metadata, and warning annotations.
- Tune chip/badge variants in shared component CSS.
- Verify light/dark and dense-table readability.

### Batch G: Metric Tooltips And Explanations

Goal: Let users understand dense metrics without adding heavy prose to every page.

Candidate tasks:

- Add or standardize tooltip/popover affordances for key metrics.
- Write calculation copy for success rate, error rate, runs/hr, drops, boot issues, cancelled, timed out, and next run.
- Ensure tooltips include the selected time-window context when relevant.
- Verify keyboard and mobile behavior.

## Questions To Resolve Before Implementation

- Should log rows link to handler detail by function name, execution ID, or both?
- Do execution IDs map reliably enough to route directly to a specific handler execution?
- Should `running with recent errors` be a visible app state, a secondary health badge, or just row copy?
- How much “new user” explanation belongs inline versus tooltips?
- Should mobile app detail preserve the same sections or introduce a condensed failure-first layout?
- Which chip/badge roles deserve stronger visual emphasis, and which should become quieter metadata?
- Should metric explanations use hover tooltips, click/tap popovers, inline info icons, or a mix depending on importance?

## Not Yet Decided

No implementation order is final. The likely first batch is Evidence Trail, because it is high-confidence, aligns with the product signature, and helps both power users and mobile responders.

## Code Feasibility Notes

### Summary

The frontend is structurally capable of supporting most of the visual/UX cleanup. The shared component system is real, the app-detail tabs are already decomposed, execution-scoped logs already exist, and Diagnostics already has hidden/degraded panels that only appear when problems exist.

The main implementation risk is not CSS. It is identity and routing: connecting logs back to handler/job detail requires reliable mapping from `execution_id` to `listener_id` or `job_id`. The execution telemetry model has that mapping, but `LogEntryResponse` does not currently expose it.

### Evidence Trail Feasibility

Relevant code:

- `frontend/src/components/shared/log-table/log-detail-drawer.tsx`
- `frontend/src/components/shared/log-table/log-table-row.tsx`
- `frontend/src/components/shared/log-table/use-log-table.tsx`
- `frontend/src/components/shared/detail-panel.tsx`
- `frontend/src/components/shared/execution-logs.tsx`
- `frontend/src/components/shared/execution-table.tsx`
- `frontend/src/api/endpoints.ts`
- `src/hassette/web/models.py`
- `src/hassette/schemas/telemetry_models.py`

What already works:

- Handler/job detail already has the inside-out evidence path.
- `ExecutionTable` rows expand into `DetailPanel`.
- `DetailPanel` shows traceback and embeds `ExecutionLogs` when an `execution_id` exists.
- `ExecutionLogs` uses `useLogTable({ context: "execution", executionId })` and links to `/logs?execution_id=...`.
- `getRecentLogs()` already supports `execution_id` filtering.
- `getLogsByExecution()` already exists.

Current gap:

- `LogEntryResponse` exposes `app_key`, `func_name`, `logger_name`, `lineno`, and `execution_id`, but not `listener_id`, `job_id`, or execution `kind`.
- `LogDetailDrawer` can link to `/apps/{app_key}`, but it cannot construct `/apps/{app_key}/handlers/listener/{id}` or `/apps/{app_key}/handlers/job/{id}` from the log entry alone.
- Function-name matching would be a fragile frontend heuristic because job functions, listener methods, wrappers, and duplicate names can collide.

Likely implementation shape:

- Backend/API option A: enrich `LogEntryResponse` with nullable `execution_kind`, `listener_id`, and `job_id` by joining `log_records.execution_id` to unified execution telemetry.
- Backend/API option B: add an endpoint such as `/api/executions/{execution_id}/context` returning app key, kind, listener/job ID, source location, and summary.
- Frontend option after A/B: update `LogDetailDrawer` to render `View handler`, `View job`, or `View execution` actions.
- Frontend option after A/B: make execution IDs in `LogTableRow`/`LogDetailDrawer` navigable rather than copy-only.

Classification: likely needs backend/API support for robust links. Execution-scoped log viewing is frontend-ready once the ID mapping exists.

### App Detail Information Architecture Feasibility

Relevant code:

- `frontend/src/pages/app-detail.tsx`
- `frontend/src/components/app-detail/overview-tab.tsx`
- `frontend/src/components/app-detail/handlers-tab.tsx`
- `frontend/src/components/app-detail/handler-detail-layout.tsx`
- `frontend/src/components/app-detail/listener-detail.tsx`
- `frontend/src/components/app-detail/job-detail.tsx`
- `frontend/src/components/app-detail/error-spotlight.tsx`
- `frontend/src/components/app-detail/recent-activity-section.tsx`
- `frontend/src/components/app-detail/handler-list.tsx`

What already works:

- Tabs are already explicit routes: `/overview`, `/handlers`, `/code`, `/logs`, `/config`.
- Handler detail is centralized through `HandlerDetailLayout`, shared by listener and job detail.
- Overview already has `ErrorSpotlight`, `HandlerHealthGrid`, `RecentActivitySection`, and app-scoped logs.
- Handler list already has computed health via `listenerHealthKind()` and `jobHealthKind()`.

Frontend-only opportunities:

- Auto-select the highest-priority handler/job when no handler is selected. `HandlersTab` already has `listeners`, `jobs`, `navigate`, and `buildItems()`; the logic can live near current selected-handler validation.
- Reorder `HandlerDetailLayout` sections without API changes.
- Move or collapse `RegistrationSource` lower in the detail flow.
- Add a stronger answer header to `HandlerDetailLayout` using existing props and stats.
- Strengthen `ErrorSpotlight` copy/actions using existing `UnifiedItem` data.
- Convert `RecentActivitySection` to mobile stacked rows with existing activity data.

Potential backend-dependent opportunities:

- If overview needs richer app-level verdicts (`running with recent failures`, `degraded`, `healthy`), existing listener/job data may be enough for app-detail pages, but app list/global cards may need a shared health summary from the backend to avoid duplicating logic.
- If recent activity rows should link to exact handler detail, `ActivityFeedEntryData` needs enough identity data. It currently renders handler names and status; verify whether it carries listener/job IDs before planning links.

Classification: app-detail restructuring is mostly frontend-only. Shared health semantics may need a backend/API contract if used across pages.

### Diagnostics Feasibility

Relevant code:

- `frontend/src/pages/diagnostics.tsx`
- `frontend/src/pages/diagnostics.module.css`
- `src/hassette/web/models.py` (`SystemStatusResponse`, `ServiceInfoResponse`, `BootIssueResponse`)
- `src/hassette/core/runtime_query_service.py`

What already works:

- Diagnostics fetches `/api/health` via `getSystemStatus()`.
- It merges HTTP service seed data with WebSocket service status.
- It already sorts anomalies before healthy services.
- It already has `BootIssuesPanel`, `TelemetryPanel`, drop counters, and exception expansion.
- The reason the healthy screenshot looks weak is that boot/telemetry panels only render when issues exist, leaving a stats strip plus flat service grid.

Frontend-only opportunities:

- Add a top-level healthy/degraded verdict using existing data: service count, non-running services, boot issues, telemetry degradation, drop counters, websocket connection.
- Render healthy-state summaries for boot and telemetry instead of hiding those panels entirely.
- Group services by known names or role strings where possible.
- Demote the raw service list below subsystem cards or behind details.
- Add copy explaining what `boot issues` and `drops` mean.

Potential backend-dependent opportunities:

- Robust subsystem grouping would be cleaner if `ServiceInfoResponse` included a subsystem/category field.
- Rich operational signals per subsystem may need additional API data: scheduler queue health, bus backpressure, DB write latency, HA websocket state, file watcher status, recent service restarts.

Classification: meaningful diagnostics improvement is possible frontend-only for healthy/degraded presentation. A full command-center version likely needs backend/API enrichment.

### Chips, Badges, And Status Semantics Feasibility

Relevant code:

- `frontend/src/components/shared/badge.tsx` + `.module.css`
- `frontend/src/components/shared/chip.tsx` + `.module.css`
- `frontend/src/components/shared/status-shape.tsx`
- `frontend/src/utils/status.ts`
- `frontend/src/components/app-detail/handler-chips.module.css`

What already works:

- `Badge` and `Chip` are already shared components.
- `StatusVariant` and `StatusKind` are intentionally separate in `utils/status.ts`.
- Component APIs are small and prop-driven.

Current gap:

- The code models variants by component shape (`Badge`, `Chip`) and broad variant names (`modifier`, `schedule`, `kind`, `origin`, `muted`), not by visual priority/role.
- Different semantic roles can end up with similar visual weight.

Frontend-only opportunities:

- Add role-oriented variants or props without changing backend data.
- Tune shared CSS once and propagate improvements broadly.
- Audit call sites and standardize usage around roles: lifecycle, execution health, trigger kind, source/origin, config value, metadata, warning annotation.

Classification: frontend-only, but should be done with a usage inventory to avoid accidental visual regressions.

### Tooltip/Explanation Feasibility

Relevant code:

- `frontend/src/components/shared/info-popover.tsx`
- `frontend/src/components/shared/tooltip.tsx`
- `frontend/src/components/shared/stats-strip.tsx`
- `frontend/src/components/shared/detail-stats.tsx`
- `frontend/src/components/shared/config-schema-view.tsx`

What already works:

- `InfoPopover` is click-triggered, keyboard/touch reachable, positioned with floating-ui, dismisses on Escape/outside click, and is already used for config help.
- `Tooltip` exists but is CSS/data-attribute based and lighter weight.
- `StatsStrip` and `DetailStats` centralize many metric presentations.

Frontend-only opportunities:

- Extend `StatsStripCell` and `DetailStatsCell` with optional `help` or `description` fields and render `InfoPopover` next to labels.
- Keep formulas/copy near cell construction initially, then centralize if duplication grows.
- Add explanations for success rate, failure counts, drops, boot issues, cancelled, timed out, runs/hr, and selected time-window behavior.

Risks:

- Hover-only `Tooltip` is not enough for mobile or important formulas.
- Adding many info icons can create visual noise; prioritize metrics that users genuinely need to interpret.

Classification: frontend-only. Prefer `InfoPopover` for important metric explanations.

### Health Model Feasibility

Relevant code:

- `frontend/src/utils/status.ts`
- `frontend/src/pages/apps.tsx`
- `frontend/src/pages/apps-table-row.tsx`
- `frontend/src/components/app-detail/handler-list.tsx`
- `frontend/src/components/layout/alert-banner.tsx`
- `frontend/src/api/endpoints.ts`

What already works:

- Lifecycle status mapping exists in `statusToVariant()`/`statusToKind()`.
- Handler/job execution health can be derived from failed/timed-out/total counts.
- App detail has listener/job data available and can derive app-local health.

Current gap:

- Lifecycle status and execution health are presented close together but not modeled as separate display concepts.
- The global apps table combines manifest status and dashboard telemetry data, but there is not yet an explicit UI state like `running with recent errors`.

Frontend-only opportunities:

- For app detail, derive a local app health verdict from listeners/jobs without API changes.
- For apps list, derive a secondary health badge from `DashboardAppGridEntry` data if the fields are sufficient.

Potential backend-dependent opportunities:

- If the same health verdict appears across apps list, sidebar, command palette, and app detail, a backend-provided normalized app health summary may prevent duplicated threshold logic.

Classification: frontend-only for local/app-detail improvements; consider API normalization before broad cross-page rollout.

### Logs Performance/Responsiveness Feasibility

Relevant code:

- `frontend/src/components/shared/log-table/use-log-table.tsx`
- `frontend/src/components/shared/log-table/use-log-data.ts`
- `frontend/src/components/shared/log-table/use-log-filters.ts`
- `frontend/src/components/shared/log-table/log-table-view.tsx`
- `frontend/src/components/shared/log-table/log-table-row.tsx`

Known issue from QA:

- `/logs` screenshot capture timed out repeatedly.
- Persona filtering on noisy logs became sluggish/unresponsive.

Preliminary read:

- `useLogTable` caps rendered entries with `RENDER_CAP`, so there is already some protection.
- Need targeted reproduction/profiling before prescribing a fix.

Likely investigation points:

- Live WebSocket updates while filtering/screenshotting.
- Full-page screenshot interaction with table/drawer/sticky layout.
- Filtering cost over `allEntries`/`restEntries` before render cap.
- Row count and DOM size in the live demo.
- Whether search input updates synchronously over a large array on every keystroke.

Classification: needs performance investigation before design/code changes.

### Suggested Implementation Order From Code Risk

1. Frontend-only quick wins: app detail hierarchy, auto-select failing handler, diagnostics healthy-state verdict, tooltip support in stat components.
2. Mobile overflow fixes: recent activity stacked rows and contained code/path overflow.
3. API-backed evidence trail: enrich execution/log context, then link log detail to handler/execution.
4. Chip/badge visual system: after the main information hierarchy is clearer, tune visual semantics across shared components.
5. Logs performance: profile separately; do not mix with visual polish unless a root cause is obvious.
