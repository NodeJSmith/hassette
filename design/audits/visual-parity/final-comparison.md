# Final Visual Parity Comparison

Generated 2026-03-21. Comparing old Jinja2 UI against new Preact SPA (post gap-fix screenshots).

---

## 1. Per-Gap Verification (GAP-001 through GAP-020)

### GAP-001: Session info bar missing from dashboard — FIXED
- **Old:** Footer bar "Hassette v0.23.0 Started 3/21/2026, 9:07:12 AM"
- **New (final):** Footer bar shows "Hassette" (visible in D1, D4, D5 final screenshots). The version number and start time are no longer displayed — only the brand name.
- **Assessment:** PARTIALLY_FIXED. The bar is present but the version and start timestamp content is missing. Only "Hassette" is shown.

### GAP-002: APP KEY column removed from apps table — FIXED
- **Old:** First column "APP KEY" with linked code-styled app keys (e.g., `otf`, `monarch_updater`)
- **New (final):** APP KEY column is restored. Visible in A1, A5, A6 final screenshots with app keys displayed as linked text.
- **Assessment:** FIXED

### GAP-003: ERROR column removed from apps table — FIXED
- **Old:** ERROR column showing error messages or "—"
- **New (final):** ERROR column is restored. Visible in A1, A5, A6 final screenshots showing "—" for healthy apps.
- **Assessment:** FIXED

### GAP-004: Multi-instance app expand/collapse missing — FIXED
- **Old:** Chevron toggle to expand multi-instance apps showing indented sub-rows
- **New (final):** A4 final screenshot shows expanded multi-instance app with sub-rows visible (e.g., `remote_app` expanded with instance rows indented below).
- **Assessment:** FIXED

### GAP-005: App filter dropdown missing from logs page — FIXED
- **Old:** "All Apps" dropdown to filter logs by app
- **New (final):** L1 and L2 final screenshots show "All Apps" dropdown present alongside the level filter.
- **Assessment:** FIXED

### GAP-006: "All Levels" option missing from log level filter — FIXED
- **Old:** Level dropdown starts with "All Levels"
- **New (final):** L1 final screenshot shows "All Levels" in the level dropdown. The app detail log sections (AD14) also show "All Levels" dropdown.
- **Assessment:** FIXED

### GAP-007: Log table app column not linked — FIXED
- **Old:** App names in log table are links to `/ui/apps/{key}`
- **New (final):** L2 final screenshot shows app name `laundry_room_lights` displayed as a green link (matching old behavior). L7 final also shows linked app names.
- **Assessment:** FIXED

### GAP-008: Sidebar brand logo replaced with pulse dot — STILL_OPEN
- **Old:** Hassette logo image (24px) with teal background block in the sidebar brand area at top-left
- **New (final):** The top-left corner shows a broken image icon or very small element. No proper logo is displayed. In dark mode screenshots (D1, X1, X6 final), the brand area shows what appears to be a broken/missing image rather than the old logo or a proper replacement.
- **Assessment:** STILL_OPEN. The logo image appears broken/not loading.

### GAP-009: "Job Avg" KPI card replaced with "Last Activity" — FIXED
- **Old:** Health strip: Status, Error Rate, Handler Avg, Job Avg
- **New (final):** AD3 final screenshot shows: STATUS, ERROR RATE, HANDLER AVG, JOB AVG. The "Last Activity" card has been reverted back to "Job Avg".
- **Assessment:** FIXED

### GAP-010: Status value not capitalized in health strip — FIXED
- **Old:** "Running" (title case)
- **New (final):** AD3, AD7, AD14 final screenshots all show "Running" and "Disabled" in title case.
- **Assessment:** FIXED

### GAP-011: Recent Errors empty state text shortened — FIXED
- **Old:** "No recent errors. All systems healthy."
- **New (final):** D1 final screenshot shows "No recent errors. All systems healthy." — full text restored.
- **Assessment:** FIXED

### GAP-012: Handler row subtitle missing topic — FIXED
- **Old:** Subtitle shows "handler_method - topic"
- **New (final):** AD5 final screenshot shows handler subtitles with both the handler method and the topic/event pattern (e.g., the full event subscription path is visible under each handler name).
- **Assessment:** FIXED

### GAP-013: Job row subtitle missing trigger_value — FIXED
- **Old:** Subtitle shows "trigger_type: trigger_value" (e.g., "cron: 0 0 * * * 0")
- **New (final):** AD7 final screenshot shows job subtitles with trigger expressions (e.g., "cron: 0 0 * * * 0" visible under `andys_tracker_job`).
- **Assessment:** FIXED

### GAP-014: Instance switcher dropdown missing on multi-instance app detail — PARTIALLY_FIXED
- **Old:** Select dropdown with instance names and statuses for switching between instances
- **New (final):** AD14 (disabled app) shows "Instance 0" text but no dropdown switcher visible. AD15 (multi-instance) shows a dropdown with instance names.
- **Assessment:** PARTIALLY_FIXED. The switcher appears present on AD15 but AD14 shows only "Instance 0" text without a dropdown. This may be correct for single-instance disabled apps, but needs verification.

### GAP-015: AlertBanner not wired into render tree — CANNOT_VERIFY
- **Old:** Alert banner between status bar and page content when apps fail
- **New (final):** No failed apps in the test data, so cannot visually verify. The gap was confirmed by code reading, not screenshots.
- **Assessment:** CANNOT_VERIFY (no failed-app scenario in screenshots)

### GAP-016: Error display card missing on failed app detail — CANNOT_VERIFY
- **Old:** Red error card with "Show traceback" expand button on failed app detail
- **New (final):** No failed app in test data. Cannot verify.
- **Assessment:** CANNOT_VERIFY (no failed-app scenario in screenshots)

### GAP-017: Log table column order changed — FIXED
- **Old:** LEVEL, TIMESTAMP, APP, MESSAGE
- **New (final):** L1 final screenshot shows columns: LEVEL, TIMESTAMP, APP, MESSAGE (matching old order). The AD5/AD10 app-detail log sections also show LEVEL, TIMESTAMP, MESSAGE (no APP column needed in app-scoped logs).
- **Assessment:** FIXED

### GAP-018: Apps list table not wrapped in card — FIXED
- **Old:** Filter tabs + table wrapped in a card with border
- **New (final):** A1 final screenshot shows the filter tabs and table wrapped in a card container with visible border/background distinction.
- **Assessment:** FIXED

### GAP-019: Tab labels not title-cased with parentheses — FIXED
- **Old:** "All (7)", "Running (6)", "Failed (0)", "Stopped (0)", "Disabled (1)"
- **New (final):** A1 final screenshot shows "All (7)", "Running (6)", "Failed (0)", "Stopped (0)", "Disabled (1)", "Blocked (0)" — title-cased with parenthesized counts.
- **Assessment:** FIXED

### GAP-020: Logs page not wrapped in card — FIXED
- **Old:** Log viewer wrapped in a card
- **New (final):** L1 final screenshot shows the log viewer content area wrapped in a card container.
- **Assessment:** FIXED

---

## 2. Per-Screenshot Pair Comparison

### D1 — Dashboard Default
| Difference | Classification |
|---|---|
| Session bar shows only "Hassette" vs old "Hassette v0.23.0 Started 3/21/2026, 9:07:12 AM" | **GAP** (see GAP-001 partial) |
| Old sidebar has filled dashboard icon; new has outline-style icons | DIFFERENT |
| Old shows absolute timestamps on app cards ("Last: 9:07:14 AM"); new shows relative ("Last: 2m ago") | DIFFERENT |
| Old sidebar brand area has logo image; new shows broken/missing image | **GAP** (GAP-008) |
| New UI has gear/settings icon in top-right corner | IMPROVEMENT |

### D4 — Dashboard Session Bar
| Difference | Classification |
|---|---|
| Same session bar content gap as D1 | **GAP** (GAP-001 partial) |
| Same sidebar logo gap | **GAP** (GAP-008) |

### D5 — Dashboard Light Mode
| Difference | Classification |
|---|---|
| Same session bar content gap | **GAP** (GAP-001 partial) |
| Same sidebar logo gap | **GAP** (GAP-008) |
| Old has refresh icon top-right; new has gear icon | DIFFERENT |
| Light mode styling consistent between old and new | -- |

### X1 — Layout Sidebar
| Difference | Classification |
|---|---|
| Same sidebar logo gap | **GAP** (GAP-008) |
| Old sidebar icons are filled; new are outline style | DIFFERENT |
| Same session bar content gap | **GAP** (GAP-001 partial) |

### X4 — Layout Status Bar
| Difference | Classification |
|---|---|
| Same as X1 differences | -- |

### X6 — Layout Dark Mode
| Difference | Classification |
|---|---|
| Same sidebar logo gap | **GAP** (GAP-008) |
| Same session bar content gap | **GAP** (GAP-001 partial) |

### X7 — Layout Light Mode
| Difference | Classification |
|---|---|
| Same as D5 differences | -- |

### A1 — Apps All Tab
| Difference | Classification |
|---|---|
| APP KEY and ERROR columns restored | -- (GAP-002, GAP-003 FIXED) |
| Tab labels now title-cased with parens | -- (GAP-019 FIXED) |
| Table wrapped in card | -- (GAP-018 FIXED) |
| New UI adds "Blocked (0)" tab (old didn't have it) | IMPROVEMENT |
| Old has INSTANCES column not present in old; new has INSTANCES column | IMPROVEMENT |
| Old table is smaller/more compact due to lower resolution capture | DIFFERENT |

### A2 — Apps Running Tab
| Difference | Classification |
|---|---|
| Same structural improvements as A1 | -- |
| No new differences beyond A1 | -- |

### A4 — Apps Multi-Instance Expanded
| Difference | Classification |
|---|---|
| Expand/collapse restored | -- (GAP-004 FIXED) |
| Old shows chevron toggles with indented sub-rows; new shows similar expand pattern | -- |
| New has "Blocked (0)" tab | IMPROVEMENT |

### A5 — Apps Disabled Tab
| Difference | Classification |
|---|---|
| APP KEY and ERROR columns present | -- (FIXED) |
| Tab formatting matches old | -- (FIXED) |
| New adds "Blocked (0)" tab | IMPROVEMENT |
| Old sidebar brand has logo; new has broken image | **GAP** (GAP-008) |

### A6 — Apps Table Structure
| Difference | Classification |
|---|---|
| Same as A1 | -- |

### AD1 — App Detail Header
| Difference | Classification |
|---|---|
| Old header: breadcrumb "Apps / OfficeButtonApp", gear icon, app name with status, instance line, Stop/Reload buttons | -- |
| New header: same breadcrumb, app name with status, Stop/Reload buttons, instance line | -- |
| Old shows "Instance 0 - PID: OfficeButtonApp.office_button"; new shows "Instance 0 - PID office_button" | DIFFERENT (minor formatting) |
| Health strip cards match: STATUS Running, ERROR RATE 0.0%, HANDLER AVG 50.2ms / <1ms, JOB AVG -- | -- |

### AD3 — App Detail Health Strip
| Difference | Classification |
|---|---|
| Health strip now shows HANDLER AVG with "<1ms" value and JOB AVG with "--" | -- (GAP-009 FIXED) |
| Status capitalized "Running" | -- (GAP-010 FIXED) |
| Old shows "50.2 ms"; new shows "<1ms" for handler avg | DIFFERENT (live data difference) |

### AD4 — App Detail Handlers Collapsed
| Difference | Classification |
|---|---|
| Handler rows show similar structure in both | -- |
| Old has slightly different handler subtitle format | -- (GAP-012 FIXED) |

### AD5 — App Detail Handler Expanded
| Difference | Classification |
|---|---|
| Old invocation table columns: STATUS, TIMESTAMP, DURATION, ERROR | -- |
| New invocation table columns: TIME, DURATION, STATUS, ERROR | DIFFERENT (column order, TIME vs TIMESTAMP label) |
| Old shows absolute dates "03/21 09:09:24 AM"; new shows "8:43:24 AM" (time only) | DIFFERENT |
| Handler subtitles include topic in both old and new | -- (GAP-012 FIXED) |
| New has colored status badges ("success" in green) matching old green badges | -- |

### AD6 — App Detail Invocation Table
| Difference | Classification |
|---|---|
| Same differences as AD5 (same content) | -- |

### AD7 — App Detail Jobs Collapsed
| Difference | Classification |
|---|---|
| Old shows "1 runs 228.7ms avg" and "24 runs 439.7ms avg" with chevron | -- |
| New shows "6 runs" and "1 runs 291ms avg 1m ago" | DIFFERENT (data difference, relative timestamp addition) |
| Job subtitles show trigger values in both | -- (GAP-013 FIXED) |
| Old has "All Levels" dropdown in logs section; new also has "All Levels" | -- (GAP-006 FIXED) |

### AD8 — App Detail Job Expanded
| Difference | Classification |
|---|---|
| Old execution table columns: STATUS, TIMESTAMP, DURATION, GPS(?), ERROR | -- |
| New execution table columns: TIME, DURATION, STATUS, ERROR | DIFFERENT (column order) |
| Old shows date+time "03/21 09:09:24 PM"; new shows time only "9:41:27 AM" | DIFFERENT |

### AD9 — App Detail Execution Table
| Difference | Classification |
|---|---|
| Same as AD8 | -- |

### AD10 — App Detail Logs Section
| Difference | Classification |
|---|---|
| Old shows OfficeButtonApp with handler-focused view; new shows AndysTrackerApp with job-focused view | DIFFERENT (different app shown) |
| Log section in new has "All Levels" dropdown and "0 entries" | -- |
| Column order in app-detail logs: old LEVEL, TIMESTAMP, MESSAGE; new LEVEL, TIMESTAMP, MESSAGE | -- (matches, GAP-017 FIXED for this context) |

### AD14 — App Detail Disabled
| Difference | Classification |
|---|---|
| Health strip: old "Disabled" in STATUS, all others "—"; new same pattern but HANDLER AVG shows "<1ms" | DIFFERENT (minor data) |
| Old has no instance text; new shows "Instance 0" | DIFFERENT |
| Old shows "No event handlers registered." vs new "No handlers registered." | DIFFERENT (slightly shortened) |
| Both show "All Levels" dropdown in logs section | -- (GAP-006 FIXED) |
| No Stop/Reload buttons shown for disabled app in either version | -- |

### AD15 — App Detail Multi-Instance
| Difference | Classification |
|---|---|
| Old shows instance selector dropdown with instance names/statuses | -- |
| New shows instance selector with "jessica_remote (running)" dropdown | -- (GAP-014 FIXED) |
| Overall layout matches between old and new | -- |

### L1 — Logs Default
| Difference | Classification |
|---|---|
| Old columns: LEVEL, TIMESTAMP, APP, MESSAGE (with "All Levels" and "All Apps" dropdowns) | -- |
| New columns: LEVEL, TIMESTAMP, APP, MESSAGE (matching old order) | -- (GAP-017 FIXED) |
| App filter dropdown present | -- (GAP-005 FIXED) |
| "All Levels" dropdown present | -- (GAP-006 FIXED) |
| Card wrapper present | -- (GAP-020 FIXED) |
| Old shows level badges as colored text (ERROR in red, WARNING in yellow); new shows colored pill badges | DIFFERENT |
| App names linked in both | -- (GAP-007 FIXED) |

### L2 — Logs Error Filter
| Difference | Classification |
|---|---|
| Both show ERROR filter active with "All Apps" dropdown and 1 entry | -- |
| Old shows "ERROR" as red badge + timestamp + linked app + message in a table row | -- |
| New shows entire error row highlighted with pink/red background, timestamp, linked app, message | IMPROVEMENT (more visible error highlighting) |
| Old columns: LEVEL, TIMESTAMP, APP, MESSAGE; new same | -- |
| Column order matches old | -- (GAP-017 FIXED) |

### L7 — Logs App Column
| Difference | Classification |
|---|---|
| Same content as L1 with focus on app column linking | -- |
| App names are linked in green in both old and new | -- (GAP-007 FIXED) |

### E1 — Error 404
| Difference | Classification |
|---|---|
| Old: raw JSON `{"detail":"Not Found"}` on white background, no sidebar | -- |
| New: styled 404 page with "404", "Page not found.", "Back to Dashboard" button, sidebar present | IMPROVEMENT |

---

## 3. Summary

| Category | Count |
|---|---|
| GAPs remaining (must fix) | **2** |
| CANNOT_VERIFY (no test data) | 2 |
| DIFFERENTs (intentional) | 12 |
| IMPROVEMENTs | 6 |
| GAPs FIXED | 16 |

### Remaining GAPs

1. **GAP-001 (PARTIAL):** Session info bar is present but only shows "Hassette" — missing version number and start timestamp that the old UI showed ("Hassette v0.23.0 Started 3/21/2026, 9:07:12 AM").

2. **GAP-008 (STILL OPEN):** Sidebar brand logo is broken/not loading. The top-left corner shows what appears to be a broken image icon instead of the Hassette logo. This is visible across all screenshots (D1, D4, D5, X1, X4, X6, X7, A5 final).

### Cannot Verify (need failed-app test data)

- **GAP-015:** AlertBanner wired into render tree — no failed apps to trigger it
- **GAP-016:** Error display card on failed app detail — no failed apps to trigger it

### Intentional Differences (accepted)

1. Relative timestamps ("2m ago") vs absolute ("9:07:14 AM") on dashboard app cards
2. Sidebar icon style (outline vs filled)
3. Settings gear icon in top-right vs refresh icon
4. Invocation/execution table column order (TIME first in new)
5. Time-only display in invocation/execution tables vs date+time
6. "No handlers registered." vs "No event handlers registered." text
7. Instance text shown on single-instance disabled apps
8. Level badges as colored pills vs colored text
9. Overall spacing more generous in new UI
10. Handler invocation row styling (cards vs table rows)
11. Minor PID format differences in instance lines
12. "Blocked" filter tab added to apps list

### Improvements (new UI is better)

1. Styled 404 page with navigation (old was raw JSON)
2. "Blocked (0)" filter tab in apps list
3. Error row highlighting with full-row pink background in log table
4. Settings/gear icon for theme toggle
5. "Reconnecting..." WebSocket state
6. Last invoked/executed timestamps on handler/job rows

---

## 4. VERDICT: FAIL

**2 remaining GAPs must be fixed before sign-off:**

| GAP | Issue | Severity |
|---|---|---|
| GAP-001 (partial) | Session bar missing version + start time | Medium — content is truncated |
| GAP-008 | Sidebar brand logo broken/not loading | High — broken image visible on every page |

**2 items cannot be verified** (GAP-015, GAP-016) due to lack of failed-app test data. These should be verified separately with a failed-app scenario before final sign-off.
