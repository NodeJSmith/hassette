# Design Critique: UI Rebuild (008-ui-rebuild)

**Date:** 2026-03-19
**Scope:** Full branch diff (71 files, 5708 insertions)
**Method:** Three parallel critics (Senior Engineer, Systems Architect, Adversarial Reviewer)

## Findings

### 1. N+1 Sequential Dashboard Queries — CRITICAL

**What's wrong**: `compute_app_grid_health()` runs 2 SQL queries per app in a sequential loop. With 10 apps, that's 20 round-trips on every dashboard load and every WS event.
**Why it matters**: On Raspberry Pi with slow SD card, this blocks the event loop for 2-4 seconds per refresh. The dashboard freezes during app reload bursts.
**Evidence (code)**:
- `context.py:122-134` — sequential `for manifest in manifests:` with two awaits per iteration
- `partials.py:50` — called on every `app_status_changed` WS event
- `telemetry_query_service.py:50-106` — each call is a full SQL query with JOINs
**Raised by**: Senior + Architect + Adversarial (all three)
**Better approach**: Single `GROUP BY app_key` query returning all apps' health in one round-trip.
**Design challenge**: At what app count does this become user-visible latency?

### 2. Alpine.js State Destroyed by WS-Triggered Morph — CRITICAL

**What's wrong**: When `app_status_changed` fires, `live-updates.js` morphs the entire handler list. Idiomorph (htmx extension) does NOT coordinate with Alpine's reactive system. Expanded rows collapse and lose loaded invocation data.
**Why it matters**: Users debugging an incident can't keep a handler expanded while other apps change status.
**Evidence (code)**:
- `base.html:23` — loads htmx idiomorph extension, NOT Alpine's `@alpinejs/morph` plugin
- `live-updates.js:91` — swap strategy is `morph:innerHTML`
- `ui.html:62` — `x-data="{ open: false, loaded: false }"` resets on morph
- `app_detail.html:110-114` — handler list is a `data-live-on-app` target
**Raised by**: Senior + Architect + Adversarial (all three)
**Better approach**: Stop morphing full handler/job lists. Update only stats via targeted swaps, or use Alpine's `@alpinejs/morph` plugin.

### 3. Dead 5s Polling + Competing Update Strategies — HIGH

**What's wrong**: App detail has THREE update mechanisms: WS morph, 5s polling of hidden stats div, and on-demand htmx.ajax. The polling renders data attributes that nothing reads — pure dead code wasting DB queries every 5 seconds.
**Why it matters**: Unnecessary DB load, confusing architecture, competing mechanisms.
**Evidence (code)**:
- `app_detail.html:116-122` — the 5s polling div
- `app_handler_stats.html` — renders `data-*` attributes, no consuming JS
- `live-updates.js:108-114` — WS event already triggers full handler list refresh
**Raised by**: Senior + Adversarial

### 4. Typed Models Defined But Unused — HIGH

**What's wrong**: `GlobalSummary` and `SessionSummary` Pydantic models exist but are never used. Dashboard uses `.get()` dict access that silently defaults on schema drift.
**Evidence (code)**:
- `telemetry_models.py:83-119` — models defined, never imported
- `telemetry_query_service.py:150` — returns `dict | None`
- `dashboard.html:19` — `.get("total_invocations", 0)`
**Raised by**: Senior + Architect

### 5. Health Thresholds Scattered Across 4 Files — HIGH

**What's wrong**: Five different interpretations of "what error rate is good/warn/bad" across 4 files. 4.9% is "good" on dashboard but "warn" on app detail.
**Evidence (code)**:
- `dashboard.html:22`, `app_health_strip.html:10`, `dashboard_app_grid.html:19,26`
**Raised by**: Architect
**Better approach**: Centralized `classify_error_rate()` function in `context.py`.

### 6. CDN Dependencies on a Local-Network Dashboard — MEDIUM

**What's wrong**: htmx, Alpine, idiomorph, Google Fonts load from external CDNs. When internet is down, the page hangs.
**Evidence (code)**:
- `base.html:9-12, 22-23, 27-28`
**Raised by**: Adversarial
**Better approach**: Vendor all JS/CSS/fonts as static files.

### 7. Page/Partial Template Divergence for Apps List — MEDIUM

**What's wrong**: `apps.html` has Alpine `x-show` filtering; `manifest_list.html` (WS refresh) does not. Live-update swap breaks the active tab filter.
**Evidence (code)**:
- `apps.html:49-113` vs `manifest_list.html:1-52`
**Raised by**: Architect

## Appendix: Individual Critic Reports

These files contain each critic's unfiltered findings:

- Senior Engineer: `/tmp/claude-mine-challenge-UQqk4B/senior.md`
- Systems Architect: `/tmp/claude-mine-challenge-UQqk4B/architect.md`
- Adversarial Reviewer: `/tmp/claude-mine-challenge-UQqk4B/adversarial.md`
