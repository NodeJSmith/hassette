# Gap Root Cause Analysis

## Where things went wrong

The design doc was correct. The mockup was correct. The gaps were introduced at two points in the pipeline: WP authoring and WP execution.

### Was the design doc wrong?

**No.** The design doc correctly specifies:

- FR#4: "a serif display face for page titles and **big numbers**"
- FR#6: "Borders are the primary depth mechanism; **shadows are reserved for floating surfaces**"
- FR#13: "greeting, system metadata (**HA version, app count, run rate**), and a status summary"
- FR#16: "Summary cards show: **top apps with status and run counts**, **activity metrics with trend visualization**, and **system service health**" — this is the three-card layout
- FR#17: "source location (**module.function:line**)" and "**age**" columns in error table
- AC#19: "Page titles render in the **serif display font**"
- AC#20: "**No card, row, or container uses a box-shadow for depth**"

The design doc describes the mockup's layout (three summary cards, not a KPI strip). It specifies serif for big numbers. It specifies no shadows. It specifies greeting + metadata. Everything that's missing in the implementation IS in the design doc.

### So where did things go wrong?

Three failure modes, at two pipeline stages.

### Failure Mode 1: WPs described old patterns instead of the mockup (plan stage)

The WP author (the orchestration agent) wrote subtasks that described **rebuilding existing components** with new styling, rather than building the **new layout from the mockup**. The design doc said "summary cards show top apps, activity metrics with trend visualization, and system service health" (FR#16) — which maps directly to the mockup's three-card layout. But the WP author translated this into existing component names.

**Examples:**

| WP | Subtask | What mockup shows | What WP described |
|----|---------|-------------------|-------------------|
| WP06 #2 | KPI strip | Three-card layout: "your apps" (app list), "activity" (big serif number + sparkline), "system" (service list) | "Render KPI cards. Include error rate, handlers, jobs, uptime. Use `var(--font-mono)` for values." — this is the old KPI strip pattern |
| WP06 #3 | App grid | Part of "your apps" card — compact list with status dots | "Rewrite app-grid.tsx and app-card.tsx: render app cards with status shapes, display name, run count, error rate" — this is the old card grid |
| WP06 #4 | Error feed | Table with TIME, APP, LOCATION, EXCEPTION, AGE columns | "Table with columns" — correctly described but the executor built expandable cards instead |
| WP07 #8 | Health strip | 5 metrics: HANDLERS, INVOCATIONS·1H, SUCCESS RATE, FAILED, TIMED OUT | "4-column grid showing error rate, handler avg duration, job avg duration, last activity" — completely different metrics |

**Root cause:** The WP author didn't cross-reference the mockup JSX files when writing subtasks. It described what _should be rebuilt_ rather than what _should be built_.

### Failure Mode 2: WPs correctly specified something but the executor skipped it

Several items were explicitly called out in WP subtasks and/or visual verification sections but never made it into the code.

| WP | What was specified | Implemented? |
|----|-------------------|--------------|
| WP06 #1 | "Add the greeting text (Newsreader display font)" | **No** — no greeting anywhere |
| WP06 #1 | "Add metadata line (HA version, app count, run rate)" | **No** — no metadata line |
| WP06 visual verification | "Welcome message with onboarding code snippet" (first install) | **No** — text only, no code snippet |
| WP05 #4 | "version + connection status" in sidebar | **Partial** — connection status only, no version |
| WP05 #4 | "app list grouped by status (failing > blocked > slow > running > stopped > disabled)" | **Partial** — sorted by status but no group headers/dividers/counts |
| WP09 #1 | "age (mono, dim)" column in log table | **No** — no age column |
| WP07 #5 | "full registration signature" in handler detail | **No** — shows handler_method only |
| WP07 #3 | "Stats strip above the list" with invocations/success rate/failed/timed-out | **No** — no stats strip above handler list |

**Root cause:** The executor agent processed subtasks but dropped requirements that weren't the "primary" deliverable of each subtask. Greeting text, metadata lines, and stats strips were secondary items within subtasks whose primary focus was a component rewrite.

### Failure Mode 3: Typography spec contradicted itself

WP06 subtask 2 explicitly says `var(--font-mono)` for KPI values, but the design doc and mockup use `var(--font-display)` (Newsreader serif) for big numbers. The WP author got this wrong and the executor faithfully implemented the wrong spec.

---

## Remediation Plan

### Phase 1: CSS Quick Fixes (30 min)

These require zero structural changes — just token/style updates.

1. **Big numbers → serif display font**: Change `.ht-health-card__value` and `.ht-kpi-card__value` from `var(--font-mono)` to `var(--font-display)`
2. **Remove card shadows**: Delete `box-shadow` from `.ht-card`
3. **Fix error card treatment**: Replace solid pink background + `border-left: 3px solid var(--err)` on `.ht-card--urgent` with subtle `color-mix(in oklch, var(--err) 4%, var(--bg-surface))` tint + standard border
4. **Remove left-border accents**: Search for all `border-left:.*var(--err)` and remove

### Phase 2: Overview Page Rebuild (WP-sized — ~4h)

The overview page needs a structural rewrite to match the mockup. The current KPI strip + app card grid must be replaced with the three-card layout.

**Subtasks:**
1. Add greeting headline with time-of-day awareness ("Good morning/afternoon/evening.") in `--font-display`
2. Add system metadata line (app count, run rate; HA version requires new backend endpoint)
3. Replace KPI strip + app card grid with three-card layout:
   - **"your apps"**: compact list of apps with status dots + invocation counts, "see all →" link
   - **"activity"**: big serif number (total runs), sparkline chart, ok/err breakdown (sparkline requires a new lightweight chart — SVG polyline is fine)
   - **"system"**: service list with status dots + metrics
4. Enrich hero card variants:
   - Single failure: inline error details (app name, error type, message, source location) + action buttons
   - Multiple failures: ranked list of failing apps with crash counts
   - First install: two-column layout with code snippet + system status
5. Replace error feed card-based layout with the mockup's table format (TIME, APP, LOCATION, EXCEPTION, AGE)
6. Add recent activity feed at bottom (status dot, time, handler name, duration/error)

**Backend needed:**
- HA version (new field on `SystemStatus` from WS `get_config`)
- Run rate (invocations+executions per hour — can compute from existing telemetry)

### Phase 3: Sidebar Enhancements (~1h)

1. Add version display below wordmark (`v{version} · ● connected`)
2. Add `APPS {count}` header above app list
3. Add collapsible status group headers with counts (FAILING 2, BLOCKED 1, RUNNING 3, etc.)
4. Add invocation counts next to app names

**Backend needed:**
- Hassette version (already available from Python package metadata)

### Phase 4: App Detail Fixes (~2h)

1. Change health strip metrics to match mockup: HANDLERS, INVOCATIONS·1H, SUCCESS RATE, FAILED, TIMED OUT
2. Add stats strip above unified handler list (total handlers+jobs, invocations, success rate)
3. Add handler detail elements: predicate expression (if available), method signature code block, source file location, "view in code →" link
4. Add P50/P95 latency to handler detail stats row
5. Code tab: add line count, "read-only" label, "copy path" button

**Backend needed:**
- P50/P95 percentile computation in handler/job summary queries

### Phase 5: Logs Page (~30 min)

1. Add "age" column showing relative time (e.g., "30s", "4m")

---

## Priority Order

1. **Phase 1** (CSS fixes) — immediate visual improvement, no risk
2. **Phase 2** (Overview rebuild) — this is the landing page and the most visible gap
3. **Phase 3** (Sidebar) — high-visibility, moderate effort
4. **Phase 4** (App detail) — lower priority, mostly additive
5. **Phase 5** (Logs) — minor enhancement
