---
topic: "Home automation dashboard activity view UX"
date: 2026-05-06
status: Draft
---

# Prior Art: Home Automation Dashboard Activity View

## The Problem

When a home automation system is running well, what should the user see? Hassette's current activity feed shows every handler invocation chronologically — timestamp, handler name, duration. On a healthy system with periodic handlers, this produces 12+ identical green rows per hour for a single handler. The feed answers "what fired?" but the user already knows: they wrote the automations. The real questions are "is anything unusual?" and "does anything need my attention?"

This is a universal problem in both home automation and monitoring dashboards. Every platform that starts with a raw event log eventually moves away from it.

## How We Do It Today

The overview page shows a `RecentActivityFeed` of up to 20 `ActivityFeedEntry` records (status, timestamp, app_key, handler_name, duration_ms, error_type, kind). Each entry renders as one row: StatusShape + time + `app_key.handler_name` + duration. The feed sits below three summary cards (Your Apps, Activity, System) and a greeting that adapts to system state. When no activity has occurred in 60 minutes, a "quiet hour" empty state appears.

## Patterns Found

### Pattern 1: Aggregate Status Cards (Traffic-Light Rollup)

**Used by**: Grafana (status panels), PatternFly (aggregate status cards), Datadog (monitor summary widgets), Home Assistant (badge indicators)

**How it works**: Instead of listing individual events, the overview shows one card per logical group (app, service) with an aggregated health status. The status uses a "worst wins" model: if all items in the group are healthy, the card is green; any warning makes it yellow; any critical makes it red. The card shows a count summary ("12 handlers: 11 OK, 1 warning") and the most recent notable event. Clicking drills down to full detail.

**Strengths**: Compresses thousands of events into a scannable view. Immediately answers "is anything wrong?" Zero cognitive load when healthy. Scales well.

**Weaknesses**: Can hide important context when aggregates mask trending problems. Requires defining "warning" and "critical" per group.

**Example**: https://www.patternfly.org/patterns/dashboard/design-guidelines/

### Pattern 2: Exception Queue (Anomaly-First Feed)

**Used by**: DataCult (exception-first dashboards), Datadog (monitor/alert list), PagerDuty

**How it works**: The feed is inverted from chronological to priority-ranked. Only exceptions (failures, anomalies, threshold breaches) appear. Each is scored by impact x urgency. The queue is capped at 5-10 items. Two threshold levels (warning and breach) prevent the binary "everything fine / everything on fire" problem. When no exceptions exist, the queue is explicitly empty with a "last checked" timestamp.

**Strengths**: Directly answers "what needs attention?" with zero noise. Empty queue = positive signal. Prevents alert fatigue through capping and scoring.

**Weaknesses**: Requires defining thresholds and scoring formulas. Empty queue can feel like the system isn't doing anything without a proof-of-life timestamp.

**Example**: https://www.datacult.ai/2026/03/16/resources-exception-first-dashboards-design/

### Pattern 3: Rate-Errors-Duration (RED) Summary

**Used by**: Grafana (RED dashboards), Datadog (APM), monitoring industry standard

**How it works**: Each handler shows three metrics: Rate (invocations/window), Errors (failure count or %), Duration (p50/p95). A handler that fires every 5 minutes becomes "288/day, 0% errors, 12ms p50" — one line instead of 288 rows. Sparklines show trends. Table sorted by "most concerning" (highest error rate or biggest duration increase).

**Strengths**: Extremely information-dense. Makes trends visible that are invisible in chronological logs. Natural for periodic automations. Problems float to top.

**Weaknesses**: Loses the narrative of specific invocations. Requires enough data for meaningful aggregation. Sparklines need care at small sizes.

**Example**: https://medium.com/@zhengweilim/from-noise-to-insight-practical-framework-for-building-effective-monitoring-dashboards-f533bbe2166e

### Pattern 4: Progressive Disclosure (Summary-to-Detail)

**Used by**: Home Assistant (tile cards), Homey (device cards), Grafana (panel drill-down), PatternFly

**How it works**: Default view shows minimum info to assess health. Detail is hidden but immediately accessible. Levels: L0 single-line status ("All apps healthy") -> L1 card grid (per-app status) -> L2 handler table -> L3 individual invocations. Each level answers a progressively more specific question. HA's tile card redesign embodies this: "features" appear only when relevant.

**Strengths**: Satisfies both quick-glance and deep-investigation. Keeps default view clean. Users stop at whatever level answers their question.

**Weaknesses**: Requires careful information architecture. Too many levels feels bureaucratic. Drill-down must be visually obvious.

**Example**: https://www.home-assistant.io/blog/2024/07/26/dashboard-chapter-2/

### Pattern 5: Cascading Failure Grouping

**Used by**: Datadog (related alert grouping), PagerDuty (deduplication), Azure Monitor (smart groups)

**How it works**: When a root-cause failure (WebSocket disconnect, DB timeout) triggers many downstream failures, they're grouped into one incident. Shows root cause, affected count, and timeline. Prevents the feed from being flooded with symptoms when the problem is one line.

**Strengths**: Dramatically reduces noise during incidents (1 line instead of 50). Root cause immediately visible.

**Weaknesses**: Requires knowing/inferring the dependency graph. Misattribution is worse than no grouping.

**Example**: https://learn.microsoft.com/en-us/azure/well-architected/operational-excellence/observability

### Pattern 6: "No News Is Good News" Empty State

**Used by**: Homey, Datadog, Grafana

**How it works**: When healthy, the dashboard communicates "everything is fine" explicitly rather than showing empty lists or walls of green. A single banner ("All 8 apps running normally, last checked 2 min ago") or an empty exception queue with timestamp. Key insight: an empty list feels broken; a deliberately-designed "all clear" feels reassuring.

**Strengths**: Replaces 12 identical green rows with one positive signal. Near-zero cognitive load for the healthy state.

**Weaknesses**: Can feel like hiding information if users don't trust the system. Needs clear path to "show me everything."

**Example**: https://www.datacult.ai/2026/03/16/resources-exception-first-dashboards-design/

## Anti-Patterns

- **The Chronological Firehose**: Showing every event chronologically is the default implementation and the worst UX. HA's logbook is the canonical example — users call it "a wall of text." (https://community.home-assistant.io/t/wth-more-filter-options-for-the-logbook/471550)

- **Single-Threshold Binary Alerting**: OK/CRITICAL with nothing in between produces constant noise or dangerous silence. Two thresholds (warning + breach) give advance notice. (https://www.datacult.ai/2026/03/16/resources-exception-first-dashboards-design/)

- **Everything on One Screen**: Technically skilled users cram every entity onto one view. "The issue is no longer technical; it's cognitive." Fix with progressive disclosure. (https://www.xda-developers.com/my-home-assistant-dashboard-got-better-when-i-stopped-trying-to-put-everything-on-one-screen/)

- **Real-Time Priority Reshuffling**: Updating exception priority in real-time makes the queue unstable. Update on a cadence, not continuously. (https://www.datacult.ai/2026/03/16/resources-exception-first-dashboards-design/)

## Emerging Trends

- **Auto-generated dashboards**: HA's Areas dashboard and Homey auto-generate views from the entity/device registry. For Hassette, this could mean auto-generating the activity view from registered apps/handlers without configuration.

- **Control + Monitor convergence**: Homey and HA blur the line between "see what's happening" and "do something about it" in the same view, moving away from separate dashboard vs logbook views.

## Relevance to Us

Hassette already has several pieces in place. The greeting system (state-aware subtitle), the "Your Apps" card (per-app run counts), the sparklines, and the status shapes are all Pattern 1/4 elements. The "quiet hour" empty state is a nascent Pattern 6. What's missing is the connection between these elements and the activity feed.

The current activity feed is textbook Anti-Pattern #1 (chronological firehose). The data model already supports Pattern 3 (RED) since the backend tracks invocation counts, failure counts, and duration per handler — the dashboard's stats strip already shows some of this at the aggregate level.

The constraint is that Hassette is a *framework monitoring tool*, not a *home control dashboard*. Pattern 7 (spatial/room organization) doesn't apply because the user's mental model is apps and handlers, not rooms. But Patterns 1-6 all apply directly.

## Recommendation

The strongest signal across all sources: **the chronological invocation list should be replaced, not just improved**. Two complementary patterns fit Hassette best:

1. **Exception queue (Pattern 2) as the primary activity view**: Show only what needs attention — failures, slow handlers, new errors. When healthy, show the "no news is good news" empty state (Pattern 6) with proof-of-life ("all handlers ran successfully, last invocation 2m ago"). This directly addresses the user's insight that "if everything is green, we already know what's firing."

2. **RED summary (Pattern 3) as a drill-down from "Your Apps"**: Each app card already shows run counts. Adding error rate and duration trend per app would give the user the "is anything degrading?" signal without needing the per-invocation log. This is mostly a frontend reorganization of data the backend already provides.

The cascading failure grouping (Pattern 5) would be a high-value addition for Hassette specifically — a WebSocket disconnect or HA restart causes many handlers to fail simultaneously, and today that would show as N separate failure rows.

Progressive disclosure (Pattern 4) is already partially in place via the app detail page — the gap is that the overview page tries to show individual invocations instead of directing users to the app detail for that level of information.

## Sources

### Reference implementations
- https://www.home-assistant.io/blog/2024/03/04/dashboard-chapter-1/ — HA dashboard redesign (Sections view, Areas dashboard)
- https://www.home-assistant.io/blog/2024/07/26/dashboard-chapter-2/ — HA tile card redesign (progressive disclosure)
- https://www.home-assistant.io/integrations/logbook/ — HA logbook (chronological activity)
- https://homey.app/en-us/blog/about-homey-pros-timeline/ — Homey Timeline and Activity widgets
- https://appdaemon.readthedocs.io/en/latest/CONFIGURE.html — AppDaemon admin interface

### Blog posts and writeups
- https://www.xda-developers.com/my-home-assistant-dashboard-got-better-when-i-stopped-trying-to-put-everything-on-one-screen/ — Less-is-more dashboard design
- https://www.datacult.ai/2026/03/16/resources-exception-first-dashboards-design/ — Exception-first dashboard framework
- https://www.datacult.ai/2026/03/16/resources-executive-vs-operator-dashboard/ — Executive vs operator views
- https://medium.com/@zhengweilim/from-noise-to-insight-practical-framework-for-building-effective-monitoring-dashboards-f533bbe2166e — RED/USE/Golden Signals framework
- https://www.seeedstudio.com/blog/2026/01/09/best-home-assistant-dashboards/ — Popular HA dashboard designs
- https://www.datadoghq.com/blog/dashboards-monitors-at-scale/ — Datadog dashboard practices

### Documentation and standards
- https://grafana.com/docs/grafana/latest/alerting/guides/best-practices/ — Grafana alerting best practices
- https://www.patternfly.org/patterns/dashboard/design-guidelines/ — PatternFly dashboard design
- https://www.patternfly.org/patterns/status-and-severity/ — PatternFly status patterns
- https://learn.microsoft.com/en-us/azure/well-architected/operational-excellence/observability — Azure observability framework

### Community discussions
- https://community.home-assistant.io/t/wth-more-filter-options-for-the-logbook/471550 — HA logbook filtering requests
- https://discourse.nodered.org/t/live-flow-activity-monitoring-with-data-preview-for-node-red/92275 — Node-RED monitoring requests
