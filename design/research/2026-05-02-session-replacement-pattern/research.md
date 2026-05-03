---
proposal: "Determine what replaces the session-scoped 'current | all' toggle in the Hassette monitoring UI after the sessions concept is removed."
date: 2026-05-02
status: Draft
flexibility: Decided
motivation: "Sessions are being removed as part of a full UI redesign. Need to decide what the replacement time-scoping pattern looks like."
constraints: "Monitoring UI for a Python automation daemon, not CI/CD. Users care about 'since last deploy' and 'what's happening now.' Daemon restarts periodically. Presentation layer only -- not redesigning the telemetry DB schema."
non-goals: "Redesigning the telemetry database schema."
depth: quick
---

# Research Brief: Time-Scoping Pattern to Replace Sessions

**Initiated by**: Investigation into how monitoring/observability tools handle "current run" vs "historical data" when there's no explicit session concept.

## Context

### What prompted this

Hassette's UI currently has a binary "This Session | All Time" toggle (`SessionScopeToggle` component) that scopes all telemetry queries to either the current daemon run or all historical data. The session concept is being removed because it adds complexity without clear value. The question is what replaces it in the UI.

### Current state

The session system today works as follows:

- **`SessionManager`** (`src/hassette/core/session_manager.py`) creates a new `sessions` row in SQLite each time the daemon starts, with `started_at`, `stopped_at`, `status`, and error fields.
- **`useScopedApi`** hook (`frontend/src/hooks/use-scoped-api.ts`) resolves whether to pass a `sessionId` or `null` to API fetchers based on the toggle state.
- **`SessionScopeToggle`** component (`frontend/src/components/layout/session-scope-toggle.tsx`) is a two-button toggle: "This Session" vs "All Time", persisted to localStorage.
- All telemetry queries (`TelemetryQueryService`) accept an optional `session_id` parameter that filters results to a single daemon run.

The toggle is conceptually clean but limited: users get either "just this run" (which resets on restart) or "everything ever" (which gets noisy over time).

### Key constraints

- The daemon restarts periodically (HA addon restarts, config changes, code deploys).
- Users primarily care about two things: "what's happening right now" and "what happened since I deployed my latest code."
- The telemetry database already has timestamps on all records -- the data supports any time-based query without schema changes.
- This is a small-scale monitoring UI (one daemon, handful of apps), not an enterprise observability platform.

## Prior Art Survey

### 1. Home Assistant

**Pattern: Last N traces + time-filtered history/logbook**

- **Automation traces**: HA stores the last 5 traces per automation by default (configurable). The traces page shows a dropdown of recent trigger times. No session concept -- just "the last N times this ran."
- **History panel**: Defaults to showing the last 24 hours. A date/time picker lets users select a range. Can filter by entity, device, area, or label. The recorder purges data older than 10 days by default (configurable).
- **Logbook**: Same time-based filtering as History. Shows a chronological event stream.
- **No "current uptime" concept**: HA does not prominently display "since last restart" anywhere in its default UI. Uptime is available as a sensor (`sensor.uptime`) but is not a first-class dashboard element.

**Takeaway**: HA avoids the session concept entirely. It uses recency-based defaults (last N traces, last 24h of history) and lets users adjust the time window. This works because HA restarts are infrequent and automations are the unit of focus, not the daemon.

### 2. Grafana

**Pattern: Global time picker with relative presets + per-panel overrides**

- **Default preset**: "Last 6 hours" is the most common default for new dashboards (configurable per dashboard).
- **Quick range presets**: Last 5m, 15m, 30m, 1h, 3h, 6h, 12h, 24h, 2d, 7d, 30d, 90d, 6mo, 1y, 2y, 5y. Also "Today so far", "This week so far", "This month so far".
- **Time picker is global**: All panels on a dashboard share the time range by default, but individual panels can override with their own relative range.
- **Auto-refresh**: Configurable refresh interval (off, 5s, 10s, 30s, 1m, 5m, etc.) separate from the time range.
- **No "since restart" concept**: Grafana has no knowledge of when the monitored service started. It's purely time-window based.

**Takeaway**: Grafana's approach is "pick a time window" with sensible defaults. The preset list is the key UX element -- users click "Last 1h" or "Last 24h" rather than thinking about sessions or deployments. The "Today so far" and "This week so far" presets are notably useful for daemon monitoring.

### 3. Prefect

**Pattern: Preset date range filters on run list + deployment-scoped views**

- **Default range**: The dashboard defaults to the last 24 hours. The flow runs page defaults to 7 days.
- **Preset ranges**: 1 day, 7 days, 30 days, plus custom range picker. Minimum granularity is 1 day (users have complained about this -- high-frequency workflows need hourly filtering).
- **Flow runs page**: Shows a run history bar chart (time vs duration) with state color coding. Filterable by flow name, deployment name, state, and tags.
- **Deployment as the "session" equivalent**: Prefect's closest analog to "current session" is the deployment view -- you look at runs for a specific deployment, which implicitly scopes to "since I deployed this version." But this is per-flow, not global.
- **No "since last restart" concept**: Prefect Cloud is SaaS, so there's no daemon restart concept. The server is always running.

**Takeaway**: Prefect's model is interesting because deployments serve as a natural boundary for "what's recent." For Hassette, the equivalent would be "since last daemon start" -- but Prefect implements this through per-entity scoping (deployment -> flow runs), not a global toggle.

### 4. Datadog

**Pattern: Time picker + version/deployment overlays**

- **Default range**: APM service pages default to "Last 15 minutes" for live monitoring views, configurable per dashboard.
- **Deployment tracking**: Datadog's APM has a dedicated deployment tracking feature. When services are tagged with a `version`, the service page shows a version timeline overlay. You can compare any two versions from the last 30 days: request/error graphs highlight the selected version while graying out others, error types unique to each version are surfaced, and endpoint-level performance is compared.
- **"Live" mode**: Datadog dashboards have a "Live" toggle that streams data in near-real-time with auto-refresh. The time picker applies to historical view.
- **The key insight**: Datadog does not replace time windows with deployment boundaries -- it layers deployment awareness *on top of* time windows. You pick "Last 1h" and then optionally overlay version annotations.

**Takeaway**: The deployment tracking model is the most sophisticated approach here. For Hassette, this maps to: show time-windowed data by default, but surface "daemon started at X" as an annotation/marker rather than a filter boundary. Users can see what happened in the last hour *and* see where the restart occurred.

### 5. Sentry

**Pattern: Release-scoped views with time-windowed comparison**

- **Default scope**: The issues list defaults to "Last 24 hours" but can be filtered to a specific release.
- **Release details page**: Shows metrics for a single release, compared against the average of all releases. The default time range is "the entire release period" (from deploy to now for the latest release).
- **"This release" vs "all releases"**: Sentry compares per-release metrics (crash rate, session health) against the aggregate. This is the closest analog to Hassette's "current | all" toggle -- but Sentry's version is richer because it shows *comparison*, not just filtering.
- **Adoption graph**: Shows what percentage of sessions are on the current release vs previous releases. This is deployment-health focused.

**Takeaway**: Sentry's model combines time windows with release/deployment boundaries. The "entire release period" default for release details is conceptually equivalent to "since last restart" but framed as "since this version was deployed." The comparison against the aggregate is a smart pattern -- it answers "is this run better or worse than usual."

## Synthesis: Common Patterns Across Tools

| Pattern | Used by | Concept |
|---------|---------|---------|
| **Relative time presets** | Grafana, Datadog, Sentry, Prefect | "Last 1h / 24h / 7d" as the primary scoping mechanism |
| **Recency defaults** | All five | Default to a recent window (15m to 24h), not all-time |
| **Deployment/version markers** | Datadog, Sentry | Overlay restart/deploy events on time-based views |
| **Per-entity scoping** | Prefect, Sentry | Filter to a specific flow/release, not a global session |
| **Comparison to baseline** | Sentry, Datadog | "This deploy vs average" or "this version vs previous" |
| **No global session concept** | All five | None of these tools have a "current session" toggle |

The overwhelming consensus is: **time windows, not sessions**. Every tool uses relative time ranges as the primary mechanism. The more sophisticated tools (Datadog, Sentry) layer deployment/version awareness on top of time windows rather than replacing them.

## Options Evaluated

### Option A: Time-window presets with uptime context (Recommended)

**How it works**: Replace the "This Session | All Time" toggle with a time-range selector offering 3-5 presets. Display the daemon's current uptime prominently in the header/status area so users always know when the last restart was. The presets would be something like:

- **Since restart** (dynamic -- equivalent to today's "This Session" but computed from `started_at` timestamp, not a session ID)
- **Last 1 hour**
- **Last 24 hours**
- **Last 7 days**

The "Since restart" preset is the default. It maps to users' primary mental model ("what happened since I deployed my latest code") without requiring a session ID in the database. It is just a time filter: `WHERE timestamp >= <daemon_start_time>`. The daemon's start time is already available via the system status endpoint (`uptime_seconds`).

The other presets cover the historical drill-down case. "All Time" is intentionally absent as a preset -- if data goes back months, showing it all is never useful. "Last 7 days" is the practical upper bound for a daemon monitoring UI.

**Pros**:
- "Since restart" maps directly to what users care about and what the old "This Session" provided
- No session concept needed in the database or query layer -- pure time filtering
- Familiar pattern from Grafana/Datadog that users already understand
- The preset list is extensible later without schema changes
- Uptime display in the header gives constant awareness of daemon health

**Cons**:
- "Since restart" duration varies wildly (minutes if the daemon just crashed and restarted, weeks if stable) -- the data density will vary
- Need to decide where the time picker lives in the new UI layout (header? per-page? sidebar?)
- Adding a time picker is slightly more complex than a binary toggle

**Effort estimate**: Small -- the backend already supports timestamp-based filtering. The frontend needs a preset selector component to replace the toggle, and the start time is already available from the status endpoint.

**Dependencies**: None. All data is already timestamped. The `uptime_seconds` field in `SystemStatusResponse` provides the anchor point.

### Option B: Always "since restart" with historical drill-down on demand

**How it works**: Remove the toggle entirely. The default view always shows data since the last restart (equivalent to the old "This Session" default). A "View history" link or expandable section on each page opens a time-range picker for historical exploration. This is closer to how HA handles automation traces -- recent data is front and center, history is available but not the default.

**Pros**:
- Simplest UI -- no picker, no toggle, just "what's happening now"
- Matches HA users' mental model (HA itself does not surface historical data prominently)
- Historical view is available when needed but does not clutter the default experience

**Cons**:
- If the daemon has been running for weeks, "since restart" becomes equivalent to "all time" -- the problem the sessions were trying to solve
- The "drill down" interaction needs careful design to avoid feeling like a hidden feature
- Less flexible than explicit time presets for users who want "last 24 hours" regardless of restart timing

**Effort estimate**: Small -- simpler than Option A on the frontend (no picker component needed for the default case).

## Concerns

### Technical risks
- The `uptime_seconds` field in `SystemStatusResponse` is a float computed from `time.time() - start_time`. For the "Since restart" preset, the frontend needs to compute `now - uptime_seconds` to get an absolute timestamp for the query. Clock drift between backend and frontend is negligible for this use case.

### Complexity risks
- A time picker with presets is a well-understood UI pattern but adds one more control to the interface. The old binary toggle was simpler to understand (if less useful). For Option A, keeping the preset list short (4-5 options max) is important.

### Maintenance risks
- Minimal. Time-based filtering is simpler to maintain than session-based filtering. No SessionManager, no session IDs in query parameters, no orphan cleanup.

## Open Questions

- [ ] Should "Since restart" be the default preset, or should "Last 24 hours" be the default (more predictable data density)?
- [ ] Does the time picker live in the global header (like Grafana) or per-page? A global picker is simpler but may not make sense for all pages.
- [ ] Should the daemon start time be shown as a visual marker/annotation on time-series charts (like Datadog's deployment markers), or just as text in the header?
- [ ] Is there value in showing a comparison ("this uptime vs previous uptimes") like Sentry does, or is that over-engineering for a single-daemon monitoring UI?

## Recommendation

**Option A (time-window presets with uptime context)** is the clear choice. It is the dominant pattern across every tool surveyed, it maps directly to users' mental models, and it is simpler to implement than the session system it replaces.

The key design decision is making "Since restart" the default preset rather than a fixed time window. This preserves the value of the old "This Session" view without any of the session infrastructure. Users who want historical context can switch to "Last 24h" or "Last 7d" with one click.

The uptime display in the header serves double duty: it tells users how long the daemon has been stable *and* it contextualizes the "Since restart" data scope.

### Suggested next steps
1. Include the time-preset selector in the UI redesign spec -- it replaces the `SessionScopeToggle` component and `useScopedApi` hook
2. Decide on default preset ("Since restart" vs "Last 24h") as part of the UI redesign discussion
3. When implementing, compute the "Since restart" timestamp from `SystemStatusResponse.uptime_seconds` rather than storing a start timestamp -- this avoids adding new backend state

## Sources

- [Home Assistant History Integration](https://www.home-assistant.io/integrations/history/)
- [Home Assistant History Stats](https://www.home-assistant.io/integrations/history_stats/)
- [Home Assistant Automation Troubleshooting (Traces)](https://www.home-assistant.io/docs/automation/troubleshooting/)
- [HA Community: Make traces persist longer](https://community.home-assistant.io/t/make-traces-persist-longer-or-make-how-long-they-last-configurable/302348)
- [Grafana Time Range Controls (AWS Managed Grafana docs)](https://docs.aws.amazon.com/grafana/latest/userguide/dashboard-time-range-controls.html)
- [Grafana Community: Default Time Range for Dashboards](https://community.grafana.com/t/default-time-range-for-dashboards/13937)
- [Grafana: Server-configurable quick time ranges](https://grafana.com/whats-new/2025-06-17-server-configurable-quick-time-ranges-for-dashboards/)
- [Prefect Flow Runs UI](https://prefect-284-docs.netlify.app/ui/flow-runs/)
- [Prefect Issue #8749: Flow-runs date range defaults](https://github.com/PrefectHQ/prefect/issues/8749)
- [Datadog APM Service Page](https://docs.datadoghq.com/tracing/services/service_page/)
- [Datadog Deployment Tracking](https://docs.datadoghq.com/tracing/services/deployment_tracking/)
- [Sentry Release Details](https://docs.sentry.io/product/releases/release-details/)
- [Sentry Release Health](https://docs.sentry.io/product/releases/health/)
