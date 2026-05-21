---
task_id: "T06"
title: "Update cross-references in non-Web-UI docs"
status: "planned"
depends_on: ["T01", "T02", "T03", "T05"]
implements: ["FR#6", "AC#2", "AC#5", "AC#6"]
---

## Summary
Update all references to "dashboard", "sessions page", and related old UI terminology in docs pages outside the Web UI section. This covers ~10 files across getting-started, core-concepts, advanced, and troubleshooting. The most complex update is `database-telemetry.md` which requires both session cleanup and dashboard reference replacement.

After all updates, run `mkdocs build --strict` to verify no broken links or warnings.

## Prompt
Update each file below. For each change, the old text and replacement are specified. Read each file first to confirm the line numbers match (they may have shifted if other tasks edited adjacent content).

### 1. `docs/pages/getting-started/index.md`
- **Line ~114**: "see the dashboard" → "see the web UI" (or "see the apps page" depending on context). Read the surrounding paragraph to determine the best replacement.

### 2. `docs/pages/getting-started/docker/index.md`
- **Line ~142**: "leaving sessions marked as `unknown`" — **DO NOT CHANGE.** This describes real database behavior during Docker shutdown (the telemetry session row's exit status), not the retired UI sessions page. The "sessions" concept being retired is about the user-facing Sessions page, not the internal database session records.
- **Line ~157**: "live dashboard, app management, log streaming, and session history" → update feature list to match current UI: "app monitoring, handler detail, log streaming, and system configuration"

### 3. `docs/pages/core-concepts/database-telemetry.md` (most complex — TWO passes)

**Pass 1 — Session cleanup** (sessions are being retired as a user-facing concept):
- **Line ~3**: "session history in the web UI" → reframe without session language. E.g., "handler invocations, job executions, and app health metrics in the web UI". NOTE: this line ALSO contains "Dashboard KPIs" — update that in the same edit (see Pass 2 line ~3).
- **Line ~11**: `[Sessions](../web-ui/sessions.md)` — this link will 404. Remove the link or replace with descriptive text about what the data represents.
- **Line ~110**: session-concept reference — reframe to describe telemetry scoping without using "session" as a user-facing term. "current session" → "current startup" or "since the last restart"; "prior sessions" → "prior startups".
- **Line ~137**: "Sessions — session history" — reframe as execution history or telemetry data. Remove the `[Sessions](../web-ui/sessions.md)` link (will 404).

**Pass 2 — Dashboard and stale UI term references**:
- **Line ~3**: "Dashboard KPIs" → "Apps page stats strip" (same line as the session history fix in Pass 1)
- **Line ~17**: This paragraph has THREE stale terms — update all:
  - "Dashboard KPI counts" → "Apps page stats strip counts"
  - "**Recent Errors** feed" → "**Error Spotlight**" (now on the App Detail Overview tab)
  - "**App Health** grid" → "**Handler health grid**" (now on the App Detail Overview tab)
- **Lines ~20-21** (the `??? note` block): Also references "App Health grid" and "error feed" — update to match the new names ("Handler health grid" and "Error Spotlight")
- **Line ~110**: "Dashboard shows accurate handler and job counts" → "Apps page stats strip shows accurate handler and job counts"
- **Line ~117**: "Dashboard displays a degraded indicator" → "Status bar shows a degraded indicator" (the telemetry degraded banner is now in the status bar area)

### 4. `docs/pages/core-concepts/configuration/global.md`
- **Line ~71**: "browser dashboard" → "web UI"

### 5. `docs/pages/advanced/log-level-tuning.md`
- **Line ~18**: "dashboard errors" → "web UI errors" or "errors visible in the web UI"
- **Line ~38**: "dashboard" → "web UI"

### 6. `docs/pages/troubleshooting.md`
- **Line ~12**: reference to `app_dir` — this is a legacy config key issue (tracked in #800), but if the surrounding context mentions "dashboard", update that.
- **Line ~94**: "Dashboard shows zeroed-out metrics" → "Apps page shows zeroed-out metrics" or "Stats strip shows zeroed-out metrics"
- **Line ~138**: "Check that `run_web_api` and `run_web_ui` are both `true`" — update to new config format: "Check that `run` and `run_ui` are both `true` under `[hassette.web_api]`"

### 7. `docs/pages/migration/index.md`
- **Line ~27**: "HADashboard" comparison — review context. If it's comparing hassette's monitoring UI to HA's HADashboard, the wording may be fine as-is (it's describing HA's tool, not hassette's). Only update if it references hassette's "dashboard."

### Final verification

After all updates, run:
```bash
cd docs && mkdocs build --strict 2>&1
```

This will catch:
- Broken internal links (especially the `sessions.md` link in `database-telemetry.md`)
- Missing image references
- Any other warnings

Fix any issues found before marking complete.

Also run a final grep to verify no stale references remain:
```bash
grep -rni "dashboard\|sessions page\|session scope\|bottom navigation\|icon sidebar" docs/pages/ --include="*.md" | grep -v "migration/" | grep -v "CHANGELOG"
```

Any remaining hits (excluding migration/ which may legitimately reference HA's dashboard and CHANGELOG which is auto-generated) indicate missed updates.

## Focus
- The `database-telemetry.md` updates are the most delicate — they involve removing session-related links and concepts while preserving the technical accuracy of what the telemetry database stores.
- The sessions table still exists in the database — the concept is being retired from *user-facing documentation*, not from the codebase. Don't remove technical descriptions of what data is stored; just stop sending users to a deleted page.
- **The `??? note` block below line ~17** contains the same stale terms ("App Health grid", "error feed") as the paragraph above it. Easy to miss because it's inside a collapsed admonition — read and update it too.
- **docker/index.md line ~142** describes real database session behavior (exit status on unclean shutdown), NOT the retired UI sessions page. Do not change it.
- Line numbers are approximate — always read the surrounding context before editing.
- The `migration/index.md` reference to "HADashboard" likely refers to Home Assistant's dashboard tool, not hassette's — it's probably correct as-is.
- The troubleshooting.md reference to `run_web_api` / `run_web_ui` is a legacy config key issue — update to the nested format while you're there.

## Verify
- [ ] FR#6: All references to "dashboard" or "sessions page" in non-Web-UI docs are updated (except migration/ HA references and CHANGELOG)
- [ ] AC#2: No docs page references "Dashboard page", "Sessions page", "session scope toggle", "bottom navigation", or "icon sidebar"
- [ ] AC#5: Cross-reference updates cover all files identified in the design doc's cross-reference plan
- [ ] AC#6: `mkdocs build --strict` completes with no warnings and all internal links resolve
