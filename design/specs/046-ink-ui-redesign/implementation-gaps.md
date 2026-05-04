# Ink UI Redesign: Implementation Gap Analysis

Systematic comparison of the hi-fi prototype (`unified-hifi/`) against the live implementation.
Screenshots taken 2026-05-03. Mockup source files read directly.

---

## Overview Page

### Layout Structure

| Mockup | Live | Status |
|--------|------|--------|
| Greeting headline ("Good afternoon.") in serif display font | Hero card ("Everything's running smoothly") | **WRONG** — no greeting; hero card replaces the greeting+banner pattern |
| System metadata line: `home assistant 2026.4 · 9 apps · 168 runs / hr` | Not present | **MISSING** |
| Three summary cards in 3-column grid: **your apps**, **activity**, **system** | Five KPI boxes in a row: ERROR RATE, APPS, HANDLERS, JOBS, UPTIME | **WRONG** — completely different layout. KPI strip is the old UI pattern |
| "your apps" card: list of apps with status dots + invocation counts, "see all →" link | App Health grid: cards with handler/job counts, last activity | **WRONG** — card grid instead of compact list |
| "activity" card: big serif number (168), sparkline chart, ok/err breakdown, "open inspector →" | Not present (invocation count is in KPI strip) | **MISSING** — no sparkline, no serif number, no activity card |
| "system" card: service list (bus, scheduler, HA websocket, file watcher) with status dots + metrics | Service Status Panel and Framework Health as separate full-width sections at bottom | **PARTIAL** — data exists but in different format/position |
| `recent errors` table: TIME, APP, LOCATION, EXCEPTION, AGE columns | Error feed with expandable error cards (pink background) | **PARTIAL** — different format. Missing LOCATION and AGE columns |
| `recent activity` feed: status dot, time, handler name, duration/error | Not present | **MISSING** |

### Visual Treatment

| Mockup | Live | Status |
|--------|------|--------|
| Big numbers in serif display font (`var(--font-display)`) | Numbers in monospace font (`var(--font-mono)`) | **WRONG** |
| Cards: flat borders only, no shadows | Cards: `box-shadow: var(--shadow-1)` on every card | **WRONG** |
| Error card: subtle background tint (`color-mix(in oklch, var(--err) 4%, var(--bg-surface))`) | Error cards: solid pink/red background with left red border | **WRONG** — left-border accent is banned pattern |
| No "INACTIVE" group label in app grid | "INACTIVE" label above disabled apps | **EXTRA** — not in mockup |
| Hero card for single failure: shows app name, error details, action buttons inline | Hero card: generic message only | **PARTIAL** — no inline error details or action buttons |
| Hero card for multiple failures: lists each failing app with crash count, error, location | Not implemented (only shows count) | **PARTIAL** |

### State Variants

| Variant | Mockup | Live | Status |
|---------|--------|------|--------|
| healthy | ✓ check icon, "everything's running smoothly", last incident note | ✓ check icon, "Everything's running smoothly" | **PARTIAL** — no last-incident note |
| single failure | ! icon, app name, error message, crash count, action buttons (open app/view traceback/stop) | ! icon, generic "{name} has failed" text | **PARTIAL** — no inline error details or action buttons |
| multiple failures | ! icon, ranked list of failing apps with crash details, "stop all failing" button | ! icon, "{n} apps failed" count only | **PARTIAL** — no ranked failure list |
| quiet | ∅ icon in activity card, "0 runs / hour", "apps are loaded and connected" | Generic hero card, "All quiet" | **PARTIAL** — no empty-state in activity card |
| first install | Two-column: code snippet + system status card, migration guide | Text-only "Welcome to Hassette", "No apps loaded yet" | **WRONG** — no code snippet, no system card, no migration guide |

---

## Sidebar

| Mockup | Live | Status |
|--------|------|--------|
| `v0.4.2 · ● connected` — version + connection | `● connected` only | **MISSING** version |
| `jump to… ⌘K` search trigger | `Search Ctrl+K` button | **OK** — functionally equivalent |
| Nav items: overview, events, logs, config | Nav items: Overview, Logs, Config | **MISSING** "events" nav item (events page deferred — OK) |
| `APPS 9` header with count | No header above app list | **MISSING** app count header |
| Status group headers: `▼ ■ FAILING 2`, `▼ ■ BLOCKED 1`, `▼ ▲ SLOW 1`, `▶ ● RUNNING 3`, etc. | Flat sorted list, no group headers or dividers | **MISSING** — status groups with counts and collapsible sections |
| Invocation counts next to each app name | No counts in sidebar | **MISSING** |
| Group collapse/expand (▼/▶) | No groups to collapse | **MISSING** |

---

## App Detail Page

### Header

| Mockup | Live | Status |
|--------|------|--------|
| `Garage Alerts` in serif display (h1) | `GarageProximityApp` with status dot | **PARTIAL** — display name shown but the overall layout differs |
| Subtitle line: `app_key: garage_alerts · class: GarageAlerts · apps/garage_alerts.py · last error 30s ago` | Breadcrumb + app_key on separate line + instance metadata | **PARTIAL** — information spread across multiple lines vs one subtitle |
| Status badge (e.g., `■ crashed`) top-right | Status dot inline with title | **DIFFERENT** — dot instead of badge, different position |
| Action buttons: `↻ reload` and `■ stop` top-right | `Reload` and `Stop` buttons top-right | **OK** — functionally equivalent |
| Error banner: "LAST ERROR" with message + "view full traceback in logs →" | ErrorDisplay component with traceback expand | **OK** — functionally equivalent |

### Health Strip / KPI

| Mockup | Live | Status |
|--------|------|--------|
| 5 KPI boxes: HANDLERS, INVOCATIONS·1H, SUCCESS RATE, FAILED, TIMED OUT | 4 KPI boxes: ERROR RATE, HANDLER AVG, JOB AVG, LAST ACTIVITY | **WRONG** — different metrics entirely. Mockup shows handler count + invocation stats; live shows averages + error rate |
| Numbers in serif display font | Numbers in monospace | **WRONG** |

### Handlers Tab

| Mockup | Live | Status |
|--------|------|--------|
| Master/detail layout with handler list + detail pane | Master/detail layout with handler list + detail pane | **OK** |
| Handler row: kind chip (state change), name in mono, "failing" pill, error preview, invocation count | Handler row: kind chip, name, human description, invocation count, error count | **PARTIAL** — no "failing" pill badge on the row |
| Detail pane: kind badge + name + "failing" badge, human description, `FIRES WHEN` predicate expression, `decorator` chip, method signature code block, source file location, LAST ERROR banner, stats row (CALLS·1H, LAST, FAILED, TIMED OUT, P50, P95), "view in code →" button | Detail pane: handler method label, modifier chips, invocation table | **PARTIAL** — missing: predicate display, method signature, source location, P50/P95 latency, "view in code" link |
| Invocations table: TIME, TRIGGER (entity transition), DUR, NOTE columns | Invocations table: status, timestamp, duration, error, trigger info | **PARTIAL** — has the data but trigger shows context ID instead of human-readable entity transition |

### Code Tab

| Mockup | Live | Status |
|--------|------|--------|
| Header: `SOURCE apps/garage_alerts.py · 39 lines · read-only` + `copy path` button | Header: filename in mono | **PARTIAL** — no line count, no "read-only" label, no "copy path" button |
| Syntax-highlighted Python with line numbers | Syntax-highlighted Python with line numbers + gutter annotations | **OK** — live actually adds gutter annotations (better than mockup) |

### Config Tab

Not shown in mockup screenshots but mockup JSX exists (`logs-config.jsx`). Live implementation looks reasonable.

---

## Typography

| Element | Mockup | Live | Status |
|---------|--------|------|--------|
| Page greeting / hero title | Serif display (`--font-display` / Newsreader) | Sans (`--font-body` / Geist) on hero card title | **WRONG** |
| Big numbers (KPI values, activity count) | Serif display | Monospace | **WRONG** |
| Body text | Sans (Geist) | Sans (Geist) | **OK** |
| Code/app keys | Monospace (Geist Mono) | Monospace (Geist Mono) | **OK** |
| Nav items, labels | Sans | Sans | **OK** |

---

## Color / Visual Treatment

| Element | Mockup | Live | Status |
|---------|--------|------|--------|
| Card depth | Border only, no shadows | `box-shadow: var(--shadow-1)` on `.ht-card` | **WRONG** |
| Error emphasis | Subtle background tint via `color-mix()` | Solid pink/red background + left red border | **WRONG** |
| Left-border accents | Not present anywhere | `.ht-card--urgent` has `border-left: 3px solid var(--err)` | **WRONG** — explicitly banned |
| Status shapes | Circle (ok), triangle (warn), square (err), ring (mute) | Same shapes | **OK** |
| Light theme ink colors | Monochrome grays | Appears similar but with a warm tint | **CHECK** — may need token comparison |

---

## Summary: What Needs to Change

### Structural (layout/component changes)

1. **Overview page**: Replace KPI strip + app card grid with the three-card layout (your apps / activity / system)
2. **Overview page**: Add greeting headline in serif display font
3. **Overview page**: Add system metadata line (HA version, app count, run rate)
4. **Overview page**: Add recent activity feed
5. **Overview page**: Enrich hero card variants (single failure: inline error + action buttons; multiple failures: ranked list; first install: code snippet + system card)
6. **Sidebar**: Add version display, app count header, status group headers with counts and collapse
7. **Sidebar**: Add invocation counts next to app names
8. **App detail health strip**: Change metrics to match mockup (HANDLERS, INVOCATIONS·1H, SUCCESS RATE, FAILED, TIMED OUT)
9. **Handler detail pane**: Add predicate expression display, method signature, source location, P50/P95 stats, "view in code" link

### Visual (CSS-only changes)

10. **Typography**: Use `--font-display` (Newsreader serif) for hero titles and big KPI numbers
11. **Cards**: Remove `box-shadow` from `.ht-card` — borders only
12. **Error cards**: Replace solid pink background + left border with subtle `color-mix()` tint
13. **Remove** left-border accent from `.ht-card--urgent`

### Missing Data

14. **HA version**: Backend needs to expose HA version (from WS API `get_config`)
15. **Run rate**: Backend needs to compute runs/hour metric
16. **P50/P95 latency**: Backend needs percentile computation in handler summary
