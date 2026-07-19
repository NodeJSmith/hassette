# Frontend Quality & Facelift Issue Map

Milestone: [Frontend Quality & Facelift](https://github.com/NodeJSmith/hassette/milestone/9)

This audit did not require a full new backlog. Most findings mapped to existing `area:ui` issues. The new issues below cover gaps that were either concrete bugs without a ticket or design-system coordination work that existing issues did not capture.

Post-audit follow-up in this branch resolves #1378, #1379, #1385, and #765.

## Newly Filed

- [#1378 Reject invalid negative app instance query params](https://github.com/NodeJSmith/hassette/issues/1378) — resolved in this branch
- [#1379 Make the closed mobile drawer inert](https://github.com/NodeJSmith/hassette/issues/1379) — resolved in this branch
- [#1380 Correct command palette ARIA and keyboard semantics](https://github.com/NodeJSmith/hassette/issues/1380)
- [#1382 Replace clickable log table rows with explicit detail controls](https://github.com/NodeJSmith/hassette/issues/1382)
- [#1383 Reconcile frontend design rules before the facelift](https://github.com/NodeJSmith/hassette/issues/1383)
- [#1384 Explore a more expressive frontend color direction](https://github.com/NodeJSmith/hassette/issues/1384)
- [#1385 Handle storage failures when resetting log columns](https://github.com/NodeJSmith/hassette/issues/1385) — resolved in this branch
- [#1386 Centralize frontend route metadata and path builders](https://github.com/NodeJSmith/hassette/issues/1386)
- [#1387 Fix log time-window filtering and live-log merge](https://github.com/NodeJSmith/hassette/issues/1387)

## Existing Issues Reused

### Correctness And Live Data

- [#754 Key appStatus WS state per instance, not just per app_key](https://github.com/NodeJSmith/hassette/issues/754)
- [#958 Fix app page logs not updating after reload](https://github.com/NodeJSmith/hassette/issues/958)
- [#1153 Stats strip on Apps page does not update in realtime when apps are started or stopped](https://github.com/NodeJSmith/hassette/issues/1153)
- [#1253 Handle high-volume live logs without freezing the UI](https://github.com/NodeJSmith/hassette/issues/1253)
- [#1373 Eliminate dual-path log assembly by switching WS log broadcast to notify-and-batch](https://github.com/NodeJSmith/hassette/issues/1373)

### Accessibility And Browser Guardrails

- [#599 Add E2E tests for user workflows, error states, and empty states](https://github.com/NodeJSmith/hassette/issues/599)
- [#851 Add focus-visible styles to all interactive elements](https://github.com/NodeJSmith/hassette/issues/851)
- [#1010 Make diagnostics ready_phase accessible on touch devices](https://github.com/NodeJSmith/hassette/issues/1010)
- [#1118 Add automated accessibility enforcement (jsx-a11y lint + axe tests)](https://github.com/NodeJSmith/hassette/issues/1118)
- [#1187 Add :focus-visible style to execution table rows](https://github.com/NodeJSmith/hassette/issues/1187)

### Responsive And Diagnostic Evidence UX

- [#384 Add resizable columns to log table](https://github.com/NodeJSmith/hassette/issues/384)
- [#652 Add structured error summaries to error display](https://github.com/NodeJSmith/hassette/issues/652)
- [#752 Fix over-stretched table columns on apps overview page](https://github.com/NodeJSmith/hassette/issues/752)
- [#762 Fix mobile display of per-execution logs on app detail pages](https://github.com/NodeJSmith/hassette/issues/762)
- [#764 Collapse app detail tabs on mobile to avoid horizontal scrollbar](https://github.com/NodeJSmith/hassette/issues/764)
- [#765 Reorder log detail drawer to show message first](https://github.com/NodeJSmith/hassette/issues/765) — resolved in this branch
- [#900 Hide low-priority table columns at narrow viewports](https://github.com/NodeJSmith/hassette/issues/900)
- [#902 Collapsible metadata on detail pages](https://github.com/NodeJSmith/hassette/issues/902)
- [#903 Mobile detail page density improvements](https://github.com/NodeJSmith/hassette/issues/903)
- [#1009 Fix truncated relative timestamps in logs table on mobile](https://github.com/NodeJSmith/hassette/issues/1009)
- [#1246 Restructure app detail around triage and investigation](https://github.com/NodeJSmith/hassette/issues/1246)
- [#1249 Fix mobile overflow in diagnostic views](https://github.com/NodeJSmith/hassette/issues/1249)
- [#1250 Connect logs to handler and execution evidence](https://github.com/NodeJSmith/hassette/issues/1250)

### Tooling, Hygiene, And Architecture

- [#457 Add CI guard for ws-types.ts against ws-schema.json drift](https://github.com/NodeJSmith/hassette/issues/457)
- [#760 Add frontend state QA tooling for dev-mode scenario testing](https://github.com/NodeJSmith/hassette/issues/760)
- [#769 Split use-websocket.ts into connection manager and message handler](https://github.com/NodeJSmith/hassette/issues/769)
- [#821 Add list virtualization for log and handler tables](https://github.com/NodeJSmith/hassette/issues/821)
- [#1086 Add frontend hygiene guards for section dividers and leaked spec tokens](https://github.com/NodeJSmith/hassette/issues/1086)
- [#1282 Audit frontend test infrastructure for factory duplication and dead code](https://github.com/NodeJSmith/hassette/issues/1282)
- [#1303 Enable exhaustive-deps and enforce @/ import alias in frontend ESLint config](https://github.com/NodeJSmith/hassette/issues/1303)
- [#1371 Add lint rule catching native <a> tags for internal routes instead of wouter Link](https://github.com/NodeJSmith/hassette/issues/1371)
- [#1376 Simplify HandlersTab render branching](https://github.com/NodeJSmith/hassette/issues/1376)
- [#1377 Add stylelint to frontend lint pipeline](https://github.com/NodeJSmith/hassette/issues/1377)

### Theme, Color, And Facelift

- [#843 Expand status color scales to 4-5 stops each](https://github.com/NodeJSmith/hassette/issues/843)
- [#844 Add inset shadow token for sunken regions](https://github.com/NodeJSmith/hassette/issues/844)
- [#845 Add bottom shadow to sticky headers on scroll](https://github.com/NodeJSmith/hassette/issues/845)
- [#846 Whitespace density tuning pass](https://github.com/NodeJSmith/hassette/issues/846)
- [#847 Audit align-items: center for baseline alignment opportunities](https://github.com/NodeJSmith/hassette/issues/847)
- [#848 Improve sidebar visual separation between sections](https://github.com/NodeJSmith/hassette/issues/848)
- [#849 Ground page titles with visual weight](https://github.com/NodeJSmith/hassette/issues/849)
- [#852 Derive dark mode surfaces from accent hue via oklch](https://github.com/NodeJSmith/hassette/issues/852)
- [#901 Add skeleton loading states for pages](https://github.com/NodeJSmith/hassette/issues/901)
- [#904 Evaluate removing stats strip from apps list page](https://github.com/NodeJSmith/hassette/issues/904)
- [#1007 Fix instance count wrapping under status badge in apps table](https://github.com/NodeJSmith/hassette/issues/1007)
- [#1148 Polish app detail overview tab and header layout](https://github.com/NodeJSmith/hassette/issues/1148)
- [#1247 Redesign diagnostics as system health](https://github.com/NodeJSmith/hassette/issues/1247)
- [#1251 Audit and tune badge and chip visual semantics](https://github.com/NodeJSmith/hassette/issues/1251)

### Config UX

- [#1149 Render or strip RST markup in config field description popovers](https://github.com/NodeJSmith/hassette/issues/1149)
- [#1150 Add search/filter to the config pages](https://github.com/NodeJSmith/hassette/issues/1150)
- [#1156 Add collapse/expand toggle to config section headers](https://github.com/NodeJSmith/hassette/issues/1156)
- [#1374 Config page shows 'not set' for fields configured via env vars or .env files](https://github.com/NodeJSmith/hassette/issues/1374)

## Not Filed Separately

- Fetch-error dead ends are covered by #599, #901, and #652 unless a specific section failure is found during implementation.
- Per-row media-query listener churn is covered by #1253 and #821 unless profiling proves a separate lightweight fix is warranted.
- App Detail eager telemetry coupling is covered by #1246 unless it blocks an unrelated tab after that restructure.
- Broader route-link hygiene is covered by #1371 plus new #1386.
