# Design: Visual Parity Verification for Preact SPA Migration

**Date:** 2026-03-21
**Status:** archived
**Spec:** N/A (process design, not feature spec)

## Problem

The Preact SPA migration has gone through 3 rounds of "screenshot, eyeball, patch" without achieving visual parity with the old Jinja2 UI. Each round finds new gaps because:

1. There's no complete inventory of what needs to match
2. Screenshots are taken ad-hoc without covering all states
3. Gap analysis is done by a single agent without verification
4. No one checks whether the gap analysis itself is complete

The old UI had 25 templates, 6 macros, 42 distinct visual states across 5 pages. The new UI has 35 component files. A prior code-reading analysis found 30+ gaps, but code reading misses visual-only differences (spacing, colors, font rendering, scroll behavior, hover states).

## Non-Goals

- **Permanent visual regression tool** — this is a one-time migration verification, not an ongoing CI process
- **Functional testing** — e2e behavioral tests are a separate concern (WP07)
- **Mobile/responsive parity** — the old UI wasn't responsive either; desktop viewport only
- **Performance comparison** — rendering speed, bundle size, etc. are separate

## Architecture

### Phase 1: Capture Old UI (Screenshotter Agent)

Stop the current hassette container. Start the old Docker image against live HA:

```bash
docker stop hassette
TOKEN=$(grep HOME_ASSISTANT_TOKEN /home/jessica/homelab/hautomate/.env | sed 's/HOME_ASSISTANT_TOKEN=//' | tr -d '"')
docker run -d --name hassette-old \
  -p 127.0.0.1:8126:8126 \
  --volumes-from hassette \
  -e HASSETTE__APP_DIR=/apps/src/hautomate \
  -e TZ=America/Chicago \
  -e HOME_ASSISTANT_TOKEN="$TOKEN" \
  --network proxy \
  ghcr.io/nodejsmith/hassette:sha-7d8c541-py3.13
```

A **screenshotter agent** navigates the old UI at `http://127.0.0.1:8126/ui/` and captures every scenario from the 42-scenario inventory. Screenshots are saved to `design/audits/visual-parity/old/` with structured naming:

```
old/
  D1-dashboard-default.png
  D1-dashboard-default-full.png    # full-page scroll
  A1-apps-all-tab.png
  A4-apps-multi-instance-expanded.png
  AD1-app-detail-header.png
  AD5-app-detail-handler-expanded.png
  ...
```

The screenshotter is given the complete 42-scenario list with explicit instructions for what to navigate to, what to click/expand, and what to verify is visible before capturing.

After capture, a **verification agent** reads every screenshot and confirms:
- Each scenario was actually captured (file exists and shows the right content)
- No scenarios were missed or duplicated
- Interactive states (expanded rows, filtered tabs) actually show the expanded/filtered state

Stop the old container, restart the current one.

### Phase 2: Capture New UI (Screenshotter Agent)

Start the current hassette container (it's the Preact SPA). A second screenshotter agent navigates the new UI at `http://127.0.0.1:8126/` and captures the **same 42 scenarios** with matching filenames in `design/audits/visual-parity/new/`.

Same verification agent confirms completeness.

### Phase 3: Gap Discovery (Comparison Agent)

A **comparison agent** receives BOTH screenshot sets and the old Jinja2 template source (from git history). For each of the 42 scenarios, it:

1. Reads the old screenshot
2. Reads the new screenshot
3. Reads the relevant old template source for structural context
4. Produces a structured comparison noting every difference

Each difference is classified as:
- **GAP** — something in the old UI is missing or broken in the new UI (must fix)
- **REGRESSION** — something that was correct in an earlier Preact version but got lost (must fix)
- **DIFFERENT** — intentional change in approach (e.g., relative vs absolute timestamps)
- **IMPROVEMENT** — new UI is better (e.g., "Reconnecting..." state)

The comparison agent writes findings to `design/audits/visual-parity/comparison.md`.

### Phase 4: Gap Verification (Adversarial Verifier Agent)

A **verifier agent** reviews the comparison document adversarially. It:

1. Re-reads every old screenshot independently
2. Checks whether each visual element visible in the screenshot appears in the comparison findings
3. Specifically looks for things the comparison agent might have NORMALIZED (accepted as "fine" when it's actually different)
4. Reads the old template macros to check for features that might not be visible in the current data (e.g., error tracebacks only show when there ARE errors)

The verifier appends missed findings to the comparison doc and flags any false negatives.

### Phase 5: Canonical Gap Checklist

After both agents complete, the findings are merged into a single canonical checklist at `design/audits/visual-parity/gap-checklist.md`:

```markdown
## Gap Checklist

### GAP-001: [title]
- **Scenario:** D3 (dashboard with failed app)
- **Old UI:** Shows error rate percentage on app card in red
- **New UI:** No error rate on card
- **File to fix:** frontend/src/components/dashboard/app-card.tsx
- **Old template:** partials/dashboard_app_grid.html
- **Status:** [ ] Open
```

This is the implementation input — every gap gets a checkbox.

### Phase 6: Implementation + Visual Verification Loop

For each gap (or batch of related gaps):

1. Implement the fix in the Preact component
2. Rebuild and redeploy (`npm run build && docker build && docker compose up -d`)
3. Take a screenshot of the fixed scenario
4. Compare against the old screenshot
5. Mark the gap as `[x] Fixed` in the checklist

After all gaps are fixed, run the full 42-scenario capture one final time and do a final comparison pass to confirm nothing was missed or regressed.

### Scenario Inventory (42 scenarios)

| ID | Page | State | Interactions Required |
|----|------|-------|----------------------|
| D1 | Dashboard | Default (all running) | None |
| D2 | Dashboard | With errors present | Need failed app |
| D3 | Dashboard | With failed app card | Need failed app |
| D4 | Dashboard | Session info bar (scroll to bottom) | Scroll |
| D5 | Dashboard | Light mode | Toggle theme |
| A1 | Apps | All tab active | None |
| A2 | Apps | Running tab active | Click tab |
| A3 | Apps | Failed tab active | Click tab (need failed app) |
| A4 | Apps | Multi-instance expanded | Click chevron on multi-instance app |
| A5 | Apps | Disabled tab active | Click tab |
| A6 | Apps | Table columns + action buttons | None (verify structure) |
| AD1 | App Detail (running) | Header + breadcrumb | Navigate to app |
| AD2 | App Detail (running) | Instance metadata | None |
| AD3 | App Detail (running) | Health strip | None |
| AD4 | App Detail (running) | Handler section collapsed | None |
| AD5 | App Detail (running) | Handler row expanded | Click handler row |
| AD6 | App Detail (running) | Handler invocation table | Click handler row (scroll) |
| AD7 | App Detail (running) | Job section collapsed | Navigate to app with jobs |
| AD8 | App Detail (running) | Job row expanded | Click job row |
| AD9 | App Detail (running) | Job execution table | Click job row (scroll) |
| AD10 | App Detail (running) | Logs section | Scroll to bottom |
| AD11 | App Detail (failed) | Error display card | Navigate to failed app |
| AD12 | App Detail (failed) | Error traceback expanded | Click "Show traceback" |
| AD13 | App Detail (failed) | Health strip (failed state) | None |
| AD14 | App Detail (disabled) | Full page | Navigate to disabled app |
| AD15 | App Detail (multi) | Instance switcher | Navigate to multi-instance app |
| AD16 | App Detail (multi) | Different instance selected | Select instance from dropdown |
| L1 | Logs | Default state | None |
| L2 | Logs | Level filter (ERROR) | Select ERROR from dropdown |
| L3 | Logs | App filter | Select app from dropdown |
| L4 | Logs | Search active | Type in search box |
| L5 | Logs | Column sorting | Click column header |
| L6 | Logs | Sticky header (scrolled) | Scroll log table |
| L7 | Logs | App column links | None (verify structure) |
| E1 | Error | 404 page | Navigate to /nonexistent |
| X1 | Layout | Sidebar brand (logo) | None |
| X2 | Layout | Alert banner (HA disconnected) | Disconnect HA (may not be testable) |
| X3 | Layout | Alert banner (failed apps) | Need failed app |
| X4 | Layout | Status bar connected | None |
| X5 | Layout | Status bar disconnected | Stop WS (may not be testable) |
| X6 | Layout | Dark mode (full page) | Default state |
| X7 | Layout | Light mode (full page) | Toggle theme |

### Agent Pipeline Summary

```
Phase 1: Screenshotter Agent → captures 42 old UI screenshots
          Verifier Agent → confirms all 42 captured correctly
Phase 2: Screenshotter Agent → captures 42 new UI screenshots
          Verifier Agent → confirms all 42 captured correctly
Phase 3: Comparison Agent → reads old+new pairs, finds all differences
Phase 4: Adversarial Verifier → re-reads old screenshots, finds missed gaps
Phase 5: Merge → canonical gap checklist with files-to-fix
Phase 6: Implementation loop → fix, rebuild, verify, check off
```

## Alternatives Considered

### Ad-hoc screenshot and patch (current approach)

Take some screenshots, eyeball them, fix what we notice, repeat.

**Rejected because:** We've done 3 rounds of this and keep finding gaps. The process has no completeness guarantee.

### Code-reading-only gap analysis

Read old templates and new components, compare features.

**Rejected because:** This was the prior analysis (30 gaps found). It misses visual-only differences like spacing, color rendering, font loading, scroll behavior, and interactive states that depend on CSS, not markup.

### Single-agent comparison

One agent reads all screenshots and produces the gap list.

**Rejected because:** Single-agent analysis is what we've been doing. The verifier agent exists specifically to catch things the first agent normalized or missed.

## Open Questions

None — all decisions made.

## Impact

- **Files created:** `design/audits/visual-parity/` directory with ~90 screenshots + comparison doc + gap checklist
- **Files modified:** ~15 frontend component files (the actual gap fixes)
- **Process:** Sequential — capture old, capture new, compare, verify, fix, verify again
- **Duration:** The capture and analysis phases are agent-driven. The fix implementation is the main work.
