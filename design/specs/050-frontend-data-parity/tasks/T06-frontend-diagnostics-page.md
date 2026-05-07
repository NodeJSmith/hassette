---
task_id: "T06"
title: "Add system diagnostics page with services, boot issues, and drop counters"
status: "planned"
depends_on: ["T03"]
implements: ["FR#12", "FR#13", "FR#14", "FR#15", "FR#16", "AC#8", "AC#9", "AC#10", "AC#11", "AC#12"]
---

## Summary
Create the `/diagnostics` page with three sections: a services panel showing all internal services with live status via two-phase init (HTTP seed + WebSocket updates), a boot issues panel with severity/label/detail, and a telemetry health panel with per-category drop counter breakdown. Register the page in sidebar nav, routing, and command palette.

## Prompt
**1. Create `frontend/src/pages/diagnostics.tsx`** — new page component with three sections:

**Services panel:**
- Two-phase initialization:
  1. On mount, fetch `GET /api/health` via `getSystemStatus()` (existing in `endpoints.ts:117`) — this returns `SystemStatusResponse` which includes `services: list[ServiceInfoResponse]` (now extended with `role`, `ready_phase`, `retry_at` per T03)
  2. Subscribe to `serviceStatus` signal from `useAppState()` for live WebSocket updates
- Merge strategy: seed initial state from HTTP response, overlay with WS updates keyed by `resource_name`
- Render each service as a row with: StatusShape (derive kind from status), humanized name, role, status, readiness phase
- Services in cooling state (status contains "cooling" or "exhausted_cooling"): show relative retry timestamp using `formatRelativeTime(retry_at)` — this refreshes when WS updates the signal
- Services with exceptions: show exception type and message inline (collapsed, expandable like the handler traceback)
- Handle empty state: "No services registered." (shouldn't happen in practice)
- Handle WS disconnection: show stale indicator on the panel (check `wsConnected` signal from app state)

**Boot issues panel:**
- Read from the same `GET /api/health` response (share the fetch with services panel)
- Boot issues are in `SystemStatusResponse.boot_issues` — each has `severity`, `label`, `detail`
- Render as a list: severity badge (use StatusShape — error severity → err kind, warning → warn kind), label in bold, detail text below
- Handle clean startup: show "Clean startup — no issues." in muted text
- Sort by severity (errors first, then warnings)

**Telemetry health panel:**
- Read from `useAppState()` signals: `droppedOverflow`, `droppedExhausted`, `droppedNoSession`, `droppedShutdown`, `errorHandlerFailures`, `telemetryDegraded`
- No fetch — the global 30s poller in `useTelemetryHealth` already populates these
- Display each counter as a labeled row: "Buffer overflow: N", "Write failed: N", "No session: N", "During shutdown: N", "Error handler failures: N"
- If all counters are zero: show "No telemetry drops." in muted text
- If `telemetryDegraded` is true: show a degraded banner at the top of the section

**2. Update routing** — `frontend/src/app.tsx`:
- Add `<Route path="/diagnostics" component={DiagnosticsPage} />` before the catch-all

**3. Update sidebar** — `frontend/src/components/layout/sidebar.tsx`:
- Add `{ path: "/diagnostics", label: "diagnostics", testId: "nav-diagnostics" }` to `NAV_ITEMS` between "logs" and "config"

**4. Update command palette** — `frontend/src/components/layout/command-palette.tsx`:
- Add a "diagnostics" entry to the static pages list

**5. Styles** in `frontend/src/global.css`:
- Section card styling: use `--bg-surface` with `--line-1` border
- Section headings: Newsreader h2 per design context
- Service rows: compact density, StatusShape + mono text
- Boot issue rows: severity badge + label + detail
- Drop counter rows: label + count in mono

**Tests:**
- Component test: diagnostics page renders all three sections
- Component test: services panel shows services from HTTP seed
- Component test: services panel updates on WS serviceStatus signal change
- Component test: cooling service shows relative retry timestamp
- Component test: boot issues sorted by severity, clean startup shows positive message
- Component test: drop counters show per-category values from app state signals
- Component test: all-zero drop counters show "No telemetry drops."
- E2E: navigate to /diagnostics via sidebar, verify sections render

After implementing, update `design/context.md` Component Inventory section to document the new "diagnostics" page (layout, sections, data sources). Also document the "handlers" page added in T05.

## Focus
- `getSystemStatus()` in `endpoints.ts:117` already exists — it returns `SystemStatus` type alias for `SystemStatusResponse`
- The `serviceStatus` signal in `create-app-state.ts:94` is a `Record<string, ServiceStatusEntry>` — key is `resource_name`
- `ServiceStatusEntry` interface (create-app-state.ts:26-36) has `role`, `ready`, `ready_phase`, `retry_at`, `exception`, `exception_type`, `exception_traceback`
- The existing `ServiceStatusPanel` in `service-status-panel.tsx` filters to show only degraded services — the diagnostics page shows ALL services, so it should not reuse the filtering logic
- The `ServiceRow` component at `service-status-panel.tsx:84` can potentially be extracted and reused, but the diagnostics version shows more fields (role, ready_phase) — decide whether to extend `ServiceRow` or create a new component
- `formatRelativeTime()` from `utils/format.ts` handles both future and past timestamps
- The `wsConnected` signal exists in app state for WS connection status
- `boot_issues` on `SystemStatusResponse` — verify this field exists in the generated types after T03 regenerates schemas. It should already be there from the existing health endpoint.
- The status bar already shows drop counters and telemetry degraded indicators — the diagnostics page is a detailed breakdown of the same data

## Verify
- [ ] FR#12: The diagnostics page displays each internal service with current status, readiness phase, and role
- [ ] FR#13: Services in cooling state show a relative retry timestamp that refreshes on WebSocket updates
- [ ] FR#14: Boot issues are listed with severity, label, and full detail text; "clean startup" shown when none exist
- [ ] FR#15: Drop counters are broken down by category: overflow, exhausted, no session, shutdown
- [ ] FR#16: Telemetry health status (degraded/healthy) and error handler failure count are displayed
- [ ] AC#8: The services panel shows all services with status, role, and readiness phase, updating in real time via WebSocket
- [ ] AC#9: A cooling service shows a relative retry timestamp (e.g., "retry in 3m") that refreshes on WS updates
- [ ] AC#10: Boot issues render with severity badge and detail, or "Clean startup" when empty
- [ ] AC#11: Each drop counter category has a labeled row with its count
- [ ] AC#12: Telemetry degraded state and error handler failure count are visible
