# Context: Remove overview page and default to /apps

## Problem & Motivation
The overview page adds a navigation step between opening the UI and reaching the information the user needs. The user's primary visit pattern is app-specific ("did X happen? why didn't Y fire?"), so landing on a dashboard that summarizes all apps delays the answer. The sidebar already provides at-a-glance health status via status-grouped app entries, making the overview redundant. The decision is to make `/apps` the default landing page and remove all overview-only code.

## Visual Artifacts
None.

## Key Decisions
1. `/` redirects to `/apps` via wouter's `<Redirect>` component — not a dual-render at both paths.
2. `AlertsBar` is dropped (diagnostics page + status bar cover its signals).
3. `TelemetryDegradedBanner` migrates to the layout shell (`app.tsx`) — it's a system-level signal.
4. `getDashboardAppGrid` and `getSystemStatus` are preserved — consumed by apps.tsx and diagnostics.tsx respectively.
5. `getDashboardKpis`, `getDashboardErrors`, `getFrameworkSummary`, and the activity endpoint are overview-only and removed.

## Constraints & Anti-Patterns
- Do NOT add overview-only data to the apps page — this is a removal, not a migration of content.
- Do NOT remove `getDashboardAppGrid` or `getSystemStatus` — they have other consumers.
- Do NOT relocate the greeting concept — that's explicitly a non-goal.
- Do NOT modify the sidebar's app registry behavior.
- Preserve the apps page's existing layout and functionality exactly.

## Design Doc References
- "## Architecture" — route change details, removals table, preservations table, AlertsBar/TelemetryDegradedBanner decisions
- "## Test Strategy" — specific test files to delete, update, and migrate
- "## Non-Goals" — explicit exclusions to avoid scope creep
