# Hassette Frontend Audit

Date: 2026-07-19
Scope: `frontend/`, `tests/e2e/`, frontend CI/tooling, and the live demo at 320/375/768/900/1280px in light and dark themes.

Post-audit follow-up in this branch resolves H4, H5, M1, and #765; the remaining findings below preserve the original audit snapshot and roadmap context.

## Anti-Patterns Verdict

**Partial fail: the product does not look wholly AI-generated, but several surfaces still look like a polished generic admin UI.**

The domain-specific density, evidence views, status language, graphite dark theme, and restrained motion give Hassette a real identity. The strongest view, App Detail, clearly serves an operational workflow rather than a template.

The main AI/admin tells are:

- Too many similarly weighted bordered, rounded containers.
- Repetitive card stacks on mobile.
- A pale, low-tension light theme with a generic blue-violet accent.
- Newsreader + Geist, now a common AI-generated pairing, although the repository explicitly treats it as intentional product identity.
- Flat page rhythm in which title, stats, search, and table often receive similar visual weight.

Do not start by replacing the fonts. The higher-value facelift is to reduce boxed chrome, strengthen hierarchy, make exception-first scanning more obvious, and deliberately choose how much color the product should carry. The current “almost no color unless status/interactive” posture may be too timid; the next design pass should explore a richer but still operational palette instead of assuming restraint means grayscale.

## Executive Summary

- **Actionable themes:** 24
- **Critical:** 0
- **High:** 9
- **Medium:** 11
- **Low:** 4
- **Overall:** Strong foundations, meaningful tests, and good design intent; the remaining risk is concentrated in boundary correctness, composite accessibility, live-data coherence, and mobile diagnostic presentation.

### Objective Quality Baseline

- 88 Vitest files, 1,372 tests, all passing.
- 91.26% statements, 84.47% branches, 86.36% functions, 93.33% lines.
- 159 E2E tests across 11 files; two targeted browser tests passed during this audit.
- Strict TypeScript, ESLint, Prettier, generated REST/WS contracts, schema validation, CSS hygiene guards, breakpoint drift checks, dead-token checks, bundle limits, and E2E CI are already present.
- Local lint, typecheck, formatting, and all seven CSS/token/breakpoint guard scripts passed.
- No automated accessibility engine is installed.
- 49 fixed waits/sleeps occur in E2E tests.
- 39 of 88 unit-test files use `vi.mock` (84 mock declarations).
- 89 open issues currently carry `area:ui`, so backlog consolidation is part of the solution.

### Top Risks

1. Logs ignore the selected time window and can drop distinct records at the REST/WS merge boundary.
2. Multi-instance app status is keyed only by app key, so one instance overwrites another.
3. The mobile drawer, command palette, and clickable log rows contain verified keyboard/ARIA defects.
4. Key diagnostic tables crop identifiers, headers, and timestamps at supported viewports.
5. The browser suite bypasses the production-default WS-gated path and lacks automatic accessibility, page-error, and reconnect enforcement.

## High Findings

### H1. Logs ignore the selected time window

- **Location:** `frontend/src/components/shared/log-table/use-log-data.ts:59-63`, `frontend/src/lib/query-keys.ts:7-8`
- **Category:** Correctness
- **Impact:** Narrow windows show out-of-window records; wide windows omit older records. A core evidence surface silently disagrees with the global selector.
- **Recommendation:** Thread effective `since` into the request and query key; add a test that changes the preset and verifies refetch/request parameters.

### H2. Multi-instance live status loses instance identity

- **Location:** `frontend/src/state/create-app-state.ts:21-28,94-103`, `frontend/src/hooks/use-websocket.ts:110-121`, `frontend/src/pages/app-detail.tsx:117-122`
- **Category:** Correctness / state architecture
- **Impact:** Status for one instance overwrites another, so table and detail views can display the wrong state.
- **Recommendation:** Key live status by app key plus instance identity. Already tracked by #754.

### H3. Log merge can silently drop records

- **Location:** `frontend/src/components/shared/log-table/use-log-data.ts:73-87`
- **Category:** Correctness
- **Impact:** Distinct records sharing the newest REST timestamp are discarded, undermining trust in live logs.
- **Recommendation:** Deduplicate by stable identity such as `seq`/row key, not timestamp. The broader dual-path problem is tracked by #1373.

### H4. Negative instance indices reach the backend

**Status:** resolved in this branch.

- **Location:** `frontend/src/pages/app-detail.tsx:73-76,127-132`
- **Category:** Correctness / routing
- **Impact:** `?instance=-1` is accepted and produces invalid listener/job requests rather than canonicalizing the URL.
- **Recommendation:** Require a non-negative integer before use and test the malformed URL path.

### H5. Closed mobile drawer remains keyboard-focusable

**Status:** resolved in this branch.

- **Location:** `frontend/src/app.tsx:31-37,97-99`
- **Category:** Accessibility
- **Standard:** WCAG 2.1.1, 2.4.3, 4.1.2
- **Impact:** Keyboard focus can enter an off-screen subtree marked `aria-hidden`.
- **Recommendation:** Unmount after close animation or apply `inert` while closed.

### H6. Command palette uses an invalid composite pattern

- **Location:** `frontend/src/components/layout/command-palette.tsx:119-169,183-208`
- **Category:** Accessibility
- **Standard:** WCAG 4.1.2 / ARIA APG combobox-listbox pattern
- **Impact:** `aria-activedescendant`, `listbox`, button-options, and focus sentinels conflict, producing unreliable screen-reader behavior.
- **Recommendation:** Implement the APG combobox pattern fully or simplify to a dialog with a normal search field and button list.

### H7. Clickable log rows conflict with table/link semantics

- **Location:** `frontend/src/components/shared/log-table/log-table-row.tsx:32-42,56-77`
- **Category:** Accessibility / interaction
- **Standard:** WCAG 2.1.1, 4.1.2
- **Impact:** A focusable `tr[role=button]` contains nested links and relies on event propagation workarounds.
- **Recommendation:** Make the row non-interactive and add an explicit detail control, or use a list/card interaction model.

### H8. Diagnostic tables are unreadable at supported viewports

- **Location:** Live screenshots for global Handlers, Logs, Apps, and App Detail at 320-1280px.
- **Category:** Responsive / information hierarchy
- **Impact:** Headers collide, identifiers are ellipsized despite being primary keys, recent timestamps become `just ...`, and recent-activity columns crop.
- **Recommendation:** Reapply column priority: preserve identifiers, merge or hide lower-value metrics, and use purpose-built mobile row layouts where necessary. Related issues: #900, #1009, #1249, #752.

### H9. Browser gates miss important production behavior

- **Location:** `tests/e2e/conftest.py:290-333`, `tests/e2e/test_websocket.py`, `frontend/src/app.test.tsx:8-60`
- **Category:** Testing / accessibility
- **Impact:** Most E2E tests force the `1h` preset and bypass default `since-restart` WS gating. There is no connected-reconnecting-connected browser proof, no global console/pageerror/network guard, and no axe/pa11y equivalent.
- **Recommendation:** Add default-path, reconnect, and browser-error fixtures; add axe checks to representative pages and interactive composites. Related issues: #599 and #1118.

## Medium Findings

### M1. Resetting log columns can throw when storage is unavailable

**Status:** resolved in this branch.

- **Location:** `frontend/src/components/shared/log-table/use-column-visibility.ts:104-107`
- **Impact:** The module tolerates storage errors elsewhere, but Reset can crash synchronously.
- **Recommendation:** Guard `removeItem` and test restricted storage.

### M2. Fetch-error states are dead ends

- **Location:** `frontend/src/pages/apps.tsx:203-208`, `frontend/src/pages/handlers.tsx:81-86`, `frontend/src/pages/app-detail.tsx:142-147`
- **Impact:** Raw messages provide no retry or diagnostic next step.
- **Recommendation:** Standardize section-scoped retryable error states.

### M3. Touch targets are inconsistently enforced

- **Location:** `frontend/src/components/shared/info-popover.module.css:8-20`, log drawer controls, Apps search, traceback controls.
- **Impact:** Several controls render at 18-30px despite `--sz-touch: 44px`.
- **Recommendation:** Enforce responsive hit-area sizing on icon, copy, search, and disclosure controls.

### M4. Every log row creates a media-query listener

- **Location:** `frontend/src/components/shared/log-table/log-table-row.tsx:24-27`, `frontend/src/hooks/use-media-query.ts:19-35`
- **Impact:** Large log tables create avoidable listener churn.
- **Recommendation:** Resolve viewport state once in the parent and pass it down.

### M5. App Detail eagerly couples every tab to telemetry

- **Location:** `frontend/src/pages/app-detail.tsx:79-147`
- **Impact:** Config/log/code tabs wait on listener/job queries and WS uptime; unrelated query failure can block the whole page.
- **Recommendation:** Move tab-specific queries into tab boundaries and keep partial failures local.

### M6. REST cache and live-signal coherence is distributed manually

- **Location:** `frontend/src/state/create-app-state.ts`, `frontend/src/hooks/use-query-invalidator.ts`, `frontend/src/hooks/use-manifests.ts`, `frontend/src/components/shared/action-buttons.tsx`
- **Impact:** Sidebar, alerts, rows, and mutation feedback can disagree until a normal refetch. #1153 is one visible symptom.
- **Recommendation:** Define one status ownership/reconciliation policy rather than per-view overlays and eventual WS updates.

### M7. Route and contract vocabularies are duplicated

- **Location:** `frontend/src/app.tsx`, `frontend/src/components/layout/sidebar.tsx`, `frontend/src/components/layout/palette-items.ts`, `frontend/src/api/endpoints.ts`, `frontend/src/api/generated-types.ts`
- **Impact:** `/design` already appears in routing but not nav/palette; hand-written route strings can drift from generated contracts.
- **Recommendation:** Centralize route builders/page metadata and derive endpoint types/paths from generated contracts where practical.

### M8. Several orchestration modules are too broad

- **Location:** `frontend/src/state/create-app-state.ts:74-218`, `frontend/src/hooks/use-websocket.ts:30-196`, `frontend/src/components/shared/log-table/use-log-filters.ts:131-305`, `frontend/src/pages/app-detail.tsx:64-259`
- **Impact:** Unrelated concerns and hidden mode switches raise change risk.
- **Recommendation:** Split by state domain and explicit adapters, starting with WebSocket connection vs message handling (#769), not arbitrary component extraction.

### M9. Aggregate coverage masks weak critical entrypoints

- **Location:** `frontend/vitest.config.ts:10-21`
- **Evidence:** `main.tsx` 0% lines, `app.tsx` 74.2% lines, `use-websocket.ts` 65.2% branches.
- **Impact:** Global 80% thresholds stay green while startup and reconnection regressions remain possible.
- **Recommendation:** Add targeted tests and per-file/diff expectations for critical entrypoints rather than simply raising the global percentage.

### M10. E2E reliability and adversarial coverage are uneven

- **Location:** `tests/e2e/`
- **Evidence:** 49 fixed waits; session-scoped mutable backend fixtures; limited non-log API failures; no hostile payload/XSS cases.
- **Recommendation:** Replace sleeps with state/event gates, add section-failure and hostile-payload cases, and reset mutable test state explicitly.

### M11. The visual system needs a focused theme exploration and facelift

- **Location:** Cross-page live matrix.
- **Category:** Theming / hierarchy
- **Impact:** Dark mode feels intentional; light mode and mobile read more like a generic boxed admin product. Repeated healthy green, error row tints, faint `--ink-4` operational text, and equal-weight containers flatten scan priority. The current “low color” stance may be overcorrecting; a richer palette could make the UI more memorable and easier to scan if color remains semantic and disciplined.
- **Recommendation:** Explore color-forward operational themes alongside the muted baseline. Reduce table/list chrome, strengthen hierarchy, introduce a more distinctive accent/status/surface palette, tighten page identity groups, and make mobile exception-first.

## Low Findings

### L1. Tutorial-style comments and tiny wrappers add reading noise

- **Location:** `frontend/src/state/create-app-state.ts`, `frontend/src/components/shared/config-schema-view.tsx`, `frontend/src/app.tsx`
- **Recommendation:** Remove comments that restate code and single-use wrappers only when touching those areas; do not run a broad churn-only cleanup.

### L2. Import, inline-style, and raw-value hygiene has residual drift

- **Evidence:** Approximately 193 deep `../../` imports in component folders, eight production inline-style sites, and about 20 raw layout values outside tokens.
- **Recommendation:** Enforce the existing `@/` alias (#1303) and clean shared primitives opportunistically.

### L3. Tests are structurally brittle in places

- **Evidence:** Roughly 305 `querySelector`/`closest` uses, about 180 production `data-testid` attributes, and at least seven test files over 400 lines.
- **Recommendation:** Prefer role/name behavior assertions in new tests and address fixture/test duplication under #1282.

### L4. Design references conflict

- **Location:** `frontend/DESIGN_RULES.md:104-121` says tables are not cards and should have no border/shadow; `design/context.md:87,698-705` describes a contained `TableCard` pattern. `DESIGN_RULES.md:5` also points to the stale path `src/styles/tokens.css` rather than `src/tokens.css`.
- **Impact:** Agents can follow either source and both appear authoritative, causing recurring visual drift.
- **Recommendation:** Reconcile these documents before the facelift.

## Live Visual QA

| Page | Broken | Degraded | Polish |
|---|---:|---:|---:|
| Apps | 1 | 4 | 0 |
| App Detail | 2 | 6 | 0 |
| App Handlers | 0 | 2 | 1 |
| Handlers | 2 | 3 | 0 |
| Logs | 1 | 5 | 0 |
| Config | 0 | 4 | 0 |
| Diagnostics | 0 | 3 | 1 |

| Persona | Verdict | Findings |
|---|---|---:|
| Morgan, 2am phone responder | Completed with friction | 4 |
| Riley, first-day user | Completed with friction | 10 |
| Devon, power-user debugger | Completed with friction | 7 |

The workflows were completable. The recurring friction was not basic navigation failure; it was weak evidence connection: registration name vs callable name, hidden execution filters, no “surrounding logs” transition, no handler-level log link, ambiguous zero-activity states, and multi-instance context leakage. This aligns directly with the design context's intended “evidence trail.” Related issue: #1250.

## Systemic Patterns

1. **The frontend is not under-tested by volume.** Its weakness is that high aggregate coverage and broad E2E happy paths do not target the most failure-prone boundaries.
2. **Live state has multiple owners.** Signals, query cache, URL state, local storage, and direct DOM updates are synchronized manually.
3. **Accessibility defects cluster in custom composites.** Native controls and simple shared primitives are generally sound; drawer/palette/clickable-row patterns are not.
4. **Visual drift comes from conflicting hierarchy rules, not missing tokens.** The token system is strong; application and source-of-truth consistency need work.
5. **The issue backlog is already rich but fragmented.** Several audit findings map to existing issues, so another large batch of issues would increase rather than reduce uncertainty.

## Positive Findings Worth Keeping

- Strict TypeScript and type-aware ESLint.
- Runtime WebSocket schema validation and generated API contracts.
- Query defaults that avoid retrying 4xx responses.
- Strict MSW handling of unexpected requests.
- Co-located test organization and meaningful hook/component coverage.
- Existing CSS/token/dead-class/breakpoint guard scripts.
- Bundle-size enforcement in CI.
- Token-driven light/dark theming.
- Shared semantic variants for buttons, badges, chips, and status shapes.
- Skip link, focus baseline, reduced-motion handling, lazy Shiki loading, and conditional command-palette fetching.
- The App Detail concept and evidence-oriented design direction.

## Priority Plan

### Phase 0: Triage the backlog

Create one short frontend quality milestone/epic and group existing issues into correctness, accessibility, test gates, architecture, and facelift. Close duplicates and mark superseded visual issues. Do not add 24 new issues.

### Phase 1: Fix verified correctness and accessibility defects

1. Log time-window propagation and identity-based merge.
2. Multi-instance status ownership (#754).
3. Negative instance validation and storage reset safety.
4. Drawer inertness, command-palette semantics, and log-row interaction model.
5. Supported-viewport identifier/timestamp/header clipping (#900, #1009, #1249).

### Phase 2: Add guardrails before more AI-authored UI work

1. `eslint-plugin-jsx-a11y` plus axe browser/component checks (#1118).
2. `react-hooks/exhaustive-deps` and enforced `@/` imports (#1303).
3. Stylelint only if configured around the existing token/module conventions (#1377); avoid duplicating custom guards.
4. Add Testing Library/Vitest lint rules for new tests.
5. Add global E2E `pageerror`, unexpected console error, and failed-request capture.
6. Add default WS-gated, reconnect, deep execution route, and error-state browser tests (#599).

### Phase 3: Simplify the riskiest seams

1. Split WebSocket connection management from message projection (#769).
2. Consolidate log assembly (#1373).
3. Establish one route/page registry and typed builders.
4. Decompose app state by domain only where it reduces cross-owner synchronization.
5. Refactor tests toward behavior while touching each subsystem (#1282).

### Phase 4: Explore and apply a more distinctive frontend theme

Pilot Apps and App Detail first, capture before/after at all supported breakpoints, then propagate shared changes.

1. Reconcile `DESIGN_RULES.md` and `design/context.md` first.
2. Explore at least two color directions: a restrained graphite baseline and a richer operational palette. Do not assume “no color” is a virtue by itself.
3. Reduce generic table/list chrome and reserve elevation for true summary/evidence blocks.
4. Strengthen light-mode surface, border, and metadata contrast.
5. Tighten title/metadata/tab identity groups and section hierarchy.
6. Mute repeated healthy status only when it improves exception scanning; allow color elsewhere when it clarifies structure, ownership, or navigation.
7. Make mobile a quick-check view rather than a stack of desktop cards.
8. Reassess the blue-violet accent as part of the palette exploration, not as an isolated token tweak.

## Recommended First Slice

One bounded first PR should:

1. Fix drawer focus, command-palette semantics, and log-row semantics.
2. Add jsx-a11y plus one axe smoke test for the shell/palette.
3. Add E2E page-error/console-error capture.

This creates immediate user value and makes future AI-authored frontend changes safer. Follow it with the log correctness slice, then the visual pilot.
