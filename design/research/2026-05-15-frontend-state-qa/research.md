---
topic: "Frontend state QA tooling"
date: 2026-05-15
status: Draft
---

# Prior Art: Frontend State QA Tooling

## The Problem

Monitoring dashboards spend roughly 30% of their time in off-happy-path states — loading, empty, error, reconnecting, partial data. These are exactly the states users see when something is going wrong and they need the dashboard most. Without a way to reproducibly get the UI into these states during development, they only get tested accidentally (if at all).

Hassette's dashboard shows apps, handlers, scheduled jobs, invocations, and logs via REST + WebSocket. Today there's no way to QA the UI against edge cases (many apps with tons of handlers, error states, backend partially down, WebSocket disconnected) without manually orchestrating a real Home Assistant instance into that state.

## How We Do It Today

MSW is set up for test-time mocking only — `frontend/src/test/handlers.ts` provides default responses and `server.use()` overrides per-test. Factory functions in `frontend/src/test/factories.ts` generate typed fixture objects. A `renderWithAppState()` helper injects controlled signal values for tests. None of this is available during interactive development — the dev server proxies to a real backend and has no built-in state simulation.

## Patterns Found

### Pattern 1: MSW Browser Scenarios with Runtime Switching

**Used by**: Teams using MSW for both dev and test; documented in MSW official best practices; implemented by msw-dev-tool and msw-ui packages.

**How it works**: Define named scenario sets as collections of MSW handler overrides. Each scenario represents a different application state — "healthy", "degraded", "empty", "error", "large-dataset". A runtime mechanism (query parameter, dev panel UI, or keyboard shortcut) activates a scenario by calling `worker.use(...scenarioHandlers)` to overlay handlers on top of the base set.

MSW's official docs recommend query-parameter switching for demos: `?scenario=error`. Tools like msw-dev-tool add a browser panel for toggling individual handlers. MSW 2.x now supports WebSocket interception, which covers Hassette's real-time event stream.

For Hassette, this means defining scenario files alongside existing MSW test handlers — `scenarios/empty.ts`, `scenarios/degraded.ts`, `scenarios/large-volume.ts` — and mounting a dev-only scenario selector. Since Hassette already generates TypeScript types from OpenAPI specs, scenario handlers get compile-time type checking for free.

**Strengths**: Reuses existing MSW infrastructure; scenarios are composable (layer error + large-data); network-level interception means no app code changes; WebSocket support covers the real-time pipeline.

**Weaknesses**: Scenarios must be manually authored and maintained alongside API changes; no automatic edge-case discovery; SolidJS lacks a ready-made dev panel (msw-dev-tool is React-specific), so a custom UI component is needed.

**Example**: [MSW Dynamic Mock Scenarios](https://mswjs.io/docs/best-practices/dynamic-mock-scenarios/), [msw-dev-tool](https://github.com/nayounsang/msw-dev-tool)

### Pattern 2: Built-in Test Data Source (Grafana Pattern)

**Used by**: Grafana (TestData data source), Amazon Managed Grafana, various monitoring dashboard projects.

**How it works**: The application ships a dedicated "test" data source that generates realistic synthetic data. Users select from predefined scenarios (streaming, random walk, error conditions) and the data source produces responses through the same rendering pipeline as real data. In Grafana this is a first-class production feature, not dev-only.

For Hassette, this would be a CLI command (`hassette seed`) or config flag (`hassette --demo`) that populates the telemetry database with synthetic apps, handlers, invocations, and scheduled jobs with controllable parameters (entity count, error rates, timing patterns).

**Strengths**: Exercises the full stack including DB queries, aggregations, and pagination; useful for demos and documentation screenshots; available without external dependencies.

**Weaknesses**: Significant backend investment to generate realistic synthetic data; maintenance as schema evolves; can't easily simulate transient states (loading, in-flight requests).

**Example**: [Grafana TestData Data Source](https://grafana.com/docs/grafana/latest/datasources/testdata/)

### Pattern 3: Scenario Runner / State Seeder

**Used by**: Rails ecosystem (enterprise seed systems), E2E test frameworks, QA teams using Cypress/Rainforest.

**How it works**: CLI commands put the application into a specific state by seeding the actual database. Scenarios are composable building blocks: `base-apps` + `many-invocations` + `some-errors` = "busy system with failures". Run via `npm run seed:empty`, `npm run seed:large`, etc.

For Hassette, a `hassette seed` command would populate the telemetry DB with synthetic records. Combined with existing Docker system tests, this enables full-stack QA.

**Strengths**: Exercises the entire stack; deterministic and reproducible; usable in CI for visual regression; no frontend code changes.

**Weaknesses**: Slower setup/teardown than mock-based approaches; seed scripts need schema maintenance; can't simulate transient states (loading, reconnecting, partial responses).

**Example**: [no source found for a canonical implementation — pattern is widespread but typically internal]

### Pattern 4: Dev-Mode Feature Flags and State Overrides

**Used by**: GitLab (E2E feature flag testing), LaunchDarkly users, teams with internal admin panels.

**How it works**: A dev-only `<DevPanel>` component (drawer, floating button, keyboard shortcut) exposes QA controls: "force loading state", "inject 500 errors on next N requests", "simulate 10,000 invocations", "disable WebSocket", "add 2s latency". Conditionally rendered via `import.meta.env.DEV`, tree-shaken from production, state stored in localStorage.

For Hassette: controls for connection state (connected/reconnecting/disconnected), data volume (empty/small/large), per-endpoint error toggles, and timing controls (freeze scheduler). Interacts with MSW handlers to dynamically adjust responses.

**Strengths**: Zero production cost; quick state toggling without reloads; persists across sessions; usable by non-developers; combines naturally with MSW scenarios.

**Weaknesses**: Must be excluded from production builds; can become a toggle dumping ground; risk of dev-only code paths diverging from production.

**Example**: [no source found for a canonical dev panel — the pattern is widespread but typically proprietary]

### Pattern 5: Component Catalog (Storybook/Histoire)

**Used by**: Most frontend teams at scale — Storybook, Histoire, Ladle.

**How it works**: Each component gets a "story" file rendering it in isolation with different prop combinations (default, loading, error, empty, overflow, etc.). A separate dev server provides a browsable index with interactive controls. Addons extend with a11y audits, viewport simulation, and MSW integration.

**Strengths**: Comprehensive visual documentation of all component states; interactive exploration; addon ecosystem.

**Weaknesses**: SolidJS support is immature — the community Storybook adapter has known stability issues, Histoire has no SolidJS support. Significant setup overhead. Component-level isolation misses page-level integration issues.

**Example**: [Storybook SolidJS](https://github.com/storybookjs/solidjs) (community adapter, known issues)

## Anti-Patterns

- **Random/Faker data in mocks**: Lorem ipsum doesn't test real edge cases. Deterministic fixtures with deliberately chosen boundaries (long names, Unicode, empty strings) are more valuable. ([Unic blog](https://www.unic.com/en/magazine/frontend-first-api-mocking))
- **Separate mock systems for dev vs test vs demo**: Maintaining different layers for each purpose leads to divergence. One MSW handler set used everywhere avoids this. ([Unic blog](https://www.unic.com/en/magazine/frontend-first-api-mocking))
- **Ignoring transient states**: Only testing happy-path and error while skipping loading, reconnecting, partial-data, and stale-while-revalidate. These are where users experience the most friction. ([Medium: Designing Dashboards Beyond the Happy Path](https://medium.com/design-bootcamp/designing-dashboards-beyond-the-happy-path-d01258344ca2))

## Emerging Trends

- **MSW WebSocket mocking**: Now supported natively, enabling simulation of real-time event streams without custom Service Worker code. Directly relevant to Hassette's WS-based live updates.
- **Type-safe mock handlers**: MSW 2.x generics + OpenAPI-generated types create end-to-end type safety where schema changes automatically surface handler mismatches.
- **MSW dev tool ecosystem**: Growing community of browser dev tools (msw-dev-tool, msw-ui) bridge the gap between "MSW for tests" and "MSW for interactive development."

## Relevance to Us

Hassette is well-positioned for Pattern 1 (MSW Browser Scenarios): MSW is already adopted, factory functions exist, and OpenAPI type generation is in place. The main gap is that none of this runs in the browser during development.

Pattern 2/3 (backend seeder) is complementary, not alternative — it exercises DB queries and aggregations that mock-based approaches skip. A `hassette seed` command would also serve as a demo mode and a foundation for documentation screenshots.

Pattern 5 (Storybook) is a poor fit today given SolidJS support limitations.

The strongest approach is **layered**: MSW browser scenarios (Pattern 1) + a dev panel (Pattern 4) for interactive switching + a backend seed command (Pattern 2/3) for full-stack validation. The MSW layer covers transient states (loading, errors, WebSocket disconnects) that seed data can't simulate. The seed layer covers data volume and DB-level edge cases that mocks can't replicate.

## Recommendation

**Start with MSW browser scenarios + a dev panel.** This is the lowest-friction path given existing infrastructure:

1. Enable MSW's Service Worker in dev mode (conditional on `import.meta.env.DEV`)
2. Reuse and extend existing test handlers/factories into named scenarios
3. Build a small SolidJS `<DevPanel>` component for runtime scenario switching
4. Add WebSocket scenario handlers for connection states

**Follow up with a backend seeder** (`hassette seed`) for full-stack validation, demo mode, and screenshot generation. This is a separate, larger effort that doesn't block the MSW work.

**Skip Storybook** until SolidJS support matures. The MSW + DevPanel approach covers the same QA need without the ecosystem friction.

## Sources

### Reference implementations
- [msw-dev-tool](https://github.com/nayounsang/msw-dev-tool) — Browser-embedded MSW handler control UI
- [msw-ui](https://github.com/fvanwijk/msw-ui) — Lightweight MSW scenario switching overlay
- [Backstage](https://github.com/backstage/backstage) — Dev app wrapper with fixture injection pattern
- [Storybook SolidJS](https://github.com/storybookjs/solidjs) — Community adapter (known stability issues)
- [hass-taste-test](https://github.com/rianadon/hass-taste-test) — E2E testing for HA custom cards

### Blog posts & writeups
- [Frontend First API Mocking (Unic)](https://www.unic.com/en/magazine/frontend-first-api-mocking) — Single mock layer for dev + test + demo
- [Designing Dashboards Beyond the Happy Path](https://medium.com/design-bootcamp/designing-dashboards-beyond-the-happy-path-d01258344ca2) — 30% of dashboard time is off-happy-path
- [Zignuts Mock Server Guide 2026](https://www.zignuts.com/blog/mock-server-frontend-development-guide) — MSW as 2026 gold standard

### Documentation & standards
- [MSW Dynamic Mock Scenarios](https://mswjs.io/docs/best-practices/dynamic-mock-scenarios/) — Official scenario switching pattern
- [MSW Browser Integration](https://mswjs.io/docs/integrations/browser/) — Service Worker setup, WebSocket support
- [Grafana TestData Data Source](https://grafana.com/docs/grafana/latest/datasources/testdata/) — Built-in synthetic data source
- [Carbon Design System Empty States](https://carbondesignsystem.com/patterns/empty-states-pattern/) — Design taxonomy for empty states
- [Histoire](https://histoire.dev/reference/config) — Vite-native component stories (no SolidJS support)
