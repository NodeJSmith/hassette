---
task_id: "T03"
title: "Migrate TelemetryDegradedBanner to layout and update tests"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#1", "AC#1", "AC#4"]
---

## Summary
Move the TelemetryDegradedBanner from the deleted dashboard page into the layout shell so it renders on all pages. Update e2e tests to reflect the route change (redirect from / to /apps), delete the broken dashboard e2e test file, and update navigation/title assertions. Migrate TelemetryDegradedBanner test coverage from the deleted dashboard tests.

## Prompt
### TelemetryDegradedBanner migration

1. In `frontend/src/app.tsx`, import `TelemetryDegradedBanner` from `../components/layout/alert-banner` and render it inside the main content area (after the status bar, before the page content). It should appear on all pages, not just apps.

2. The component is defined in `frontend/src/components/layout/alert-banner.tsx` (line ~43, exported as `TelemetryDegradedBanner`). It reads from `useAppState()` signals — no props needed. No code changes to the component itself.

3. `TelemetryDegradedBanner` already has full test coverage in `frontend/src/components/layout/alert-banner.test.tsx` — no migration needed for component-level tests. Write one new test in `app.test.tsx` (or equivalent layout test file) confirming the banner renders in the layout shell when `telemetryDegraded` signal is true.

### E2E test updates

4. **Delete** `tests/e2e/test_dashboard.py` entirely — it references deleted components (`hero-card-*`, `kpi-strip`, `#dashboard-app-grid`) and is already broken.

5. **Update** `tests/e2e/test_navigation.py`:
   - Remove the `("/", "Dashboard - Hassette")` entry from `TITLE_MAP` (or update to expect redirect to `/apps` → `"Apps - Hassette"`)
   - Update brand-link assertion: if it expects URL ending in `/$`, change to expect `/apps`
   - Update any other assertions that navigate to `/` and expect overview content

6. **Update** `tests/e2e/test_hot_reload.py` — lines 26 and 44 reference `#dashboard-app-grid` and `[data-testid='nav-overview']` which are deleted by T01. Update these assertions to use apps page testids.

7. **Check** `tests/e2e/test_theme.py`, `test_websocket.py`, `test_apps_list.py` for references to the overview/dashboard route. Update any that navigate to `/` to use `/apps` instead.

7. **Update design/context.md**: Remove the "Overview (Dashboard)" section. Add a note in the Layout section or at the top that `/apps` is the default landing page. Remove "overview" from the sidebar nav links description. Note TelemetryDegradedBanner's new location in the layout.

### Frontend test updates

8. **Run e2e tests** to verify: `uv run nox -s e2e` (or `uv run pytest -m e2e -v -n auto`).

## Focus
- `TelemetryDegradedBanner` is a standalone component with no props — it reads `useAppState().telemetryDegraded`. Placing it in the layout shell is a one-line render addition.
- The e2e test files are in `tests/e2e/`. The mock fixtures in `tests/e2e/mock_fixtures.py` define `ListenerSummary` objects with `cancelled=0` — these are invocation-level counts on ListenerSummary, NOT job cancellation. Leave them alone.
- `test_navigation.py` has a `TITLE_MAP` dict mapping routes to expected document titles. The `/` entry must be removed or redirected.
- `design/context.md` is the canonical design spec at `design/context.md`. The "Overview (Dashboard)" section starts around line 235 with the heading `### Overview (Dashboard)`.

## Verify
- [ ] FR#1: Navigating to `/` redirects to `/apps` in e2e tests
- [ ] AC#1: E2e tests confirm the apps page loads when visiting `/`
- [ ] AC#4: TelemetryDegradedBanner renders on all pages (apps, handlers, logs, diagnostics, config) when telemetry is degraded
