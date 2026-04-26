# Design: Improve Web Frontend and Backend Tests

**Date:** 2026-04-25
**Status:** approved
**Research:** /tmp/claude-mine-define-research-8NoP7E/brief.md

## Problem

The web layer — both the monitoring dashboard and its supporting API — has significantly weaker test coverage and infrastructure than the core framework. The frontend uses manual fetch replacement for API mocking, which creates per-file boilerplate, drift between mock and real API shapes, and makes scenario-based testing awkward. Only a third of frontend components have any tests at all, and the ones that exist are shallow. Format utilities used across every data table have zero tests. End-to-end tests assert exact values from seed data, breaking whenever fixture data changes even though the UI behavior is correct. On the backend, input validation and edge cases for the API are undertested.

This matters now because recent infrastructure improvements (#585, #586, #593) raised the bar for the core test suite — deterministic polling, clean fixtures, elimination of over-mocking. The web layer should meet the same standard.

## Goals

- Establish a network-level API mocking foundation for frontend tests that eliminates manual fetch replacement
- Achieve thorough test coverage for every frontend component, not just high-priority ones
- Cover all frontend data formatting utilities with unit tests
- Make end-to-end test assertions resilient to seed data changes without weakening semantic verification
- Close the remaining backend API test gaps: input validation, parameter edge cases, and protocol error handling

## Non-Goals

- Accessibility testing, visual regression testing, or snapshot testing (separate concerns)
- Frontend coverage threshold enforcement in CI (may follow naturally but not a deliverable)
- Rewriting the E2E test server infrastructure beyond what's needed for WebSocket enablement

## User Scenarios

### Contributor: Framework developer

- **Goal:** Ship changes to the web layer with confidence that tests catch regressions
- **Context:** After modifying a component, API route, or response model

#### Adding a new API endpoint

1. **Implements the route handler**
   - Sees: existing route patterns in `web/routes/`
   - Decides: response model shape, query parameters, error handling
   - Then: writes integration tests using established mock patterns

2. **Adds a frontend component to display the data**
   - Sees: existing component test patterns, shared mock handlers, factory functions
   - Decides: component props, data transformations, conditional rendering
   - Then: writes component tests that exercise rendering, prop variations, loading states, and error states using network-level mocks

3. **Runs the full test suite**
   - Sees: all tests pass, including E2E tests that don't break from unrelated seed data changes
   - Then: ships with confidence

#### Modifying seed data for E2E tests

1. **Changes a fixture value**
   - Sees: E2E tests still pass because assertions are structural or derived from the seed data, not hardcoded
   - Then: no cascade of broken assertions to chase down

## Functional Requirements

1. Frontend tests must mock API responses at the network level, intercepting actual HTTP requests rather than replacing the fetch function
2. A centralized set of default mock handlers must exist for all API endpoints, returning realistic response shapes
3. Individual tests must be able to override specific handlers for scenario testing (error responses, empty states, edge cases) without affecting other tests
4. Shared factory functions must exist for creating test data objects, replacing per-file duplication
5. Every frontend component that renders UI or contains logic must have tests covering: basic rendering, prop variations, conditional display logic, and edge cases (empty data, zero counts, error states). Entry points, context definitions, type-only modules, theme configuration, and pure re-exports are excluded.
6. Components that fetch data must have tests for loading and error states
7. All data formatting functions (timestamps, durations, relative times, trigger details) must have unit tests covering boundary conditions
8. End-to-end test assertions must not use hardcoded values derived from seed data (counts, rates, entity names, computed strings); assertions must either derive expected values from the seed data source or use structural matchers that verify format without coupling to magnitude. Static UI text (page titles, labels, CSS classes) may remain hardcoded.
9. Tests verifying specific computations (error rates, aggregated counts) must use derived constants rather than structural matchers, to preserve semantic verification
10. Backend API tests must cover input validation: invalid format parameters, out-of-range numeric parameters, and non-existent resource references
11. Backend API tests must cover endpoint-specific parameter behavior: pagination limits, result ordering, and empty result sets
12. Backend tests must cover protocol-level error handling for the real-time connection: malformed messages, unknown message types, and invalid subscription parameters

## Edge Cases

- Components that use lazy-loaded data (invocation/execution detail rows that fetch on expand) need tests for both the collapsed and expanded states
- Format utilities must handle boundary inputs: epoch zero, sub-millisecond durations, "just now" vs "1 minute ago" boundary, and locale-dependent formatting
- E2E derived constants must handle the computation chain correctly (e.g., error rate denominator combines handler invocations and job executions)
- Network-level mocking starts with `onUnhandledRequest: 'warn'` during development to avoid cascading failures from incomplete handler coverage; switches to `'error'` once all handlers are in place. During the `'warn'` phase, uncovered endpoints log warnings but don't fail tests
- Components using reactive state (signals) that update independently of props need tests verifying that signal changes trigger re-renders correctly

## Acceptance Criteria

1. Network-level API mocking is installed and configured as the default frontend test mocking approach
2. Existing tests that mock fetch to simulate API responses are migrated to the network-level approach; tests that intentionally test client-level fetch error parsing (e.g., how the API client handles different error response formats) retain direct fetch mocking since they are testing the client itself, not the API
3. A shared factory module exists with functions for all major data objects, eliminating per-file duplication
4. Every frontend component has a corresponding test file with thorough coverage (render, props, conditionals, edge cases)
5. All data formatting functions have unit tests with boundary condition coverage
6. No end-to-end test assertion contains a hardcoded seed-data-derived value (counts, rates, entity names, computed strings) that would break if seed data changes
7. Computation-verifying E2E tests use derived constants from the seed data source
8. Backend input validation tests exist for all parameter constraints documented in the route handlers
9. Backend tests exist for thin endpoints (invocations, executions, sessions) covering limit, ordering, and empty results
10. Backend protocol error handling tests exist for malformed, unknown, and invalid messages
11. All existing tests continue to pass with no regressions
12. Test documentation (TESTING.md) updated to reflect new patterns: mocking layer rule (MSW vs vi.mock(hook) vs direct fetch mock), factory `satisfies` convention, and E2E computed constant convention
13. At least one E2E test exercises the WebSocket session path (scope='current' + session ID) end-to-end
14. Computation-verifying E2E tests import a shared formula helper from the backend rather than re-deriving the formula

## Dependencies and Assumptions

- MSW (`msw` npm package) as the network-level mocking library — well-established, framework-agnostic, works with jsdom/Vitest
- Assumes existing `@testing-library/preact` patterns remain the standard for component testing
- Backend test infrastructure (`create_hassette_stub()`, `web_helpers.py` factories, httpx.AsyncClient) is stable and sufficient — no changes needed
- E2E infrastructure (Playwright, session-scoped uvicorn server, mock_fixtures.py builders) is stable — only assertion patterns change

## Architecture

### Frontend: MSW setup

Add `msw` to `devDependencies` in `frontend/package.json` (it exists in `package-lock.json` from a prior manual install but is absent from `package.json` — `npm ci` in CI would silently drop it). Then configure `msw/node` in the existing test setup (`frontend/src/test-setup.ts`). The server lifecycle hooks (`beforeAll`/`afterEach`/`afterAll`) go in the setup file so they apply to all tests automatically. Verify that the global MSW Node interceptor co-exists safely with `client.test.ts`'s direct `globalThis.fetch = vi.fn()` replacement — if they conflict, have `client.test.ts` call `server.close()` in its `beforeAll`/`afterAll` to disable MSW interception for that file.

Create `frontend/src/test/handlers.ts` with default handlers for every endpoint defined in `frontend/src/api/endpoints.ts`. Each handler returns a realistic response shape matching the OpenAPI-generated types. Start with `onUnhandledRequest: 'warn'` during initial development to avoid cascading failures from incomplete handler coverage; switch to `'error'` in a final commit once all component tests pass and handlers are comprehensive.

Create `frontend/src/test/factories.ts` to consolidate the factory functions currently duplicated across test files (`createApp()` in `app-card.test.tsx`, `createError()` in `error-feed.test.tsx`, etc.). Each factory accepts `Partial<T>` overrides for flexible test data creation. Factory default objects use TypeScript `satisfies` to ensure new required fields from `generated-types.ts` produce compile errors rather than silently defaulting to `undefined`.

Handlers in `handlers.ts` use `HttpResponse.json<T>()` from MSW v2 with explicit type parameters referencing the generated types. This ensures handler response shapes are TypeScript-enforced — missing required fields are compile errors caught by `tsc`, not silent test drift.

Migrate existing fetch-mock tests in component tests that mock fetch. The following test files are explicitly excluded from MSW migration because they test at different abstraction layers:

- `api/client.test.ts` — tests client-level error parsing (422 detail extraction, 500 message fallback, non-JSON statusText fallback). Retains direct fetch mocking because it's testing the fetch-adjacent layer, not the API.
- `hooks/use-api.test.ts` and `hooks/use-scoped-api.test.ts` — inject a `vi.fn()` fetcher directly into the hook via the `fetcher` parameter. They never call `fetch` and there is nothing for MSW to intercept. These test hook contract behavior (signal stability, race-condition guards, enabled/lazy lifecycle).

**Mocking layer rule:** Components testing rendering given known data use `vi.mock(hook)`. Components testing data-fetching behavior (loading states, error responses, API shape validation) use MSW. Tests verifying hook internals (signal identity, reconnect lifecycle, dependency tracking) use direct fetcher injection. This rule is documented in TESTING.md.

### Frontend: Component tests

Follow the established pattern from `app-card.test.tsx` and `error-feed.test.tsx`: render with `@testing-library/preact`, assert on DOM content, use factories for test data. For components that fetch data (like `handler-row.tsx` which lazy-loads invocations on expand), use MSW `server.use()` to set up per-test responses and test both success and error paths.

Components using `@preact/signals` (expand/collapse state, reactive values) need `act()` wrapping for signal updates. The pattern is proven in existing tests like `framework-health.test.tsx`.

Target: every `.tsx` component file under `frontend/src/components/` and `frontend/src/pages/` gets a corresponding `.test.tsx`. Excluded: `main.tsx` (entry point), `context.ts` (context definition), `theme.ts` (config), `endpoints.ts` (URL constants), type-only modules. Trivial wrapper components (`spinner.tsx`, `icons.tsx`) and simple page shells (`not-found.tsx`) get smoke tests; components and pages with logic get thorough coverage. `dashboard.tsx` in particular contains debounced refetch, multi-path conditional rendering, and tier filter interaction — it requires thorough coverage.

### Frontend: Format utility tests

Create `frontend/src/utils/format.test.ts` covering `formatTimestamp`, `formatDuration`, `formatRelativeTime`, `formatTriggerDetail`, and `pluralize` from `frontend/src/utils/format.ts`. Pure function tests — no mocking needed. Use `vi.useFakeTimers()` for time-dependent functions.

### E2E: Seed data resilience

Extract seed data values as module-level constants in `tests/e2e/mock_fixtures.py`, computed from builder output (not hand-written literals). For example, `APP_TIER_TOTAL_INVOCATIONS = default_global_summary.listeners.total_invocations` rather than `TOTAL_INVOCATIONS = 33`. Use tier-qualified names (`APP_TIER_`, `FRAMEWORK_TIER_`) to prevent cross-tier misattribution. Constants derived from builder output cannot drift — they are a single source of truth. Replace hardcoded seed-data-derived strings in `test_dashboard.py`, `test_app_detail.py`, and other E2E test files with references to these computed constants or with regex/structural matchers where the exact value doesn't matter semantically.

For computation-verifying tests (like `test_dashboard_error_rate_includes_jobs`), extract the computation formula into a pure helper function in `telemetry_helpers.py` (e.g., `compute_error_rate(invocations, executions, errors)`) that both the route handler and the E2E test import. This ensures the test verifies the actual formula, not a re-derivation that can silently drift from the production code.

### E2E: WebSocket session path coverage

The current E2E suite disables WebSocket (`ws='none'`) and uses an autouse fixture that forces `sessionScope='all'`. This means the default user flow — WebSocket connects, session ID received, `useScopedApi` fetches with `session_id` — has no E2E coverage. Add at least one E2E test that enables WebSocket and exercises the `scope='current'` path end-to-end, verifying that session-scoped data fetching works correctly when a WebSocket connection is active.

### Backend: Input validation and edge case tests

Add tests to `tests/integration/test_web_api.py` (or a new `test_web_api_validation.py` if the file becomes unwieldy) covering:
- Invalid `app_key` format on start/stop/reload routes (the regex `^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$` is enforced via FastAPI path validation)
- Out-of-range `limit` parameters across events, logs, sessions, invocations, and executions endpoints
- Non-existent `app_key` behavior on management endpoints
- `handler_invocations` and `job_executions` limit param, ordering, and empty result tests
- `sessions` endpoint ordering verification

Add WebSocket edge case tests to `tests/integration/test_ws_endpoint.py` covering malformed JSON, unknown message types, and subscribe with invalid/missing fields.

## Alternatives Considered

**Jest instead of Vitest for frontend**: Rejected — the project already uses Vitest with Preact-specific configuration. Migration would be churn with no benefit.

**Continue manual fetch mocking instead of MSW**: Rejected — per-file `globalThis.fetch = vi.fn()` creates boilerplate, doesn't validate request shapes, and makes scenario testing verbose. MSW intercepts at the network level and is the standard approach for modern frontend testing.

**Snapshot testing for components**: Not adopted — snapshot tests are brittle and don't verify behavior. The project already has the right approach with explicit DOM assertions. Snapshot testing could be considered separately but is outside this scope.

**Page Object Model for E2E tests**: Not adopted for this effort — the current direct-locator approach works and the E2E tests are not the primary testing layer. POM could be a future improvement but is unnecessary for the seed data resilience fix.

## Test Strategy

This entire spec is about testing, so the test strategy is the implementation itself. Key verification approaches:

- **MSW integration**: Verify that the test setup correctly intercepts requests and that `onUnhandledRequest: 'error'` catches missing handlers
- **Component tests**: Verify via `npm test` that all new tests pass and exercise the intended behavior
- **Format utilities**: Pure function tests with boundary inputs — straightforward verification
- **E2E resilience**: Modify seed data values and verify that all E2E tests still pass (the acid test for resilience)
- **Backend validation**: Run `uv run nox -s dev -- -n 2` to verify all new and existing tests pass

## Documentation Updates

- Update `tests/TESTING.md` with: mocking layer rule (when to use MSW vs `vi.mock(hook)` vs direct fetch mock), factory `satisfies` convention, E2E computed constant convention, and MSW usage patterns
- No CLAUDE.md changes needed — existing test commands remain the same

## Impact

**Frontend files affected:**
- `frontend/package.json` — add `msw` dependency
- `frontend/src/test-setup.ts` — add MSW server lifecycle
- `frontend/src/test/handlers.ts` — new: default API handlers
- `frontend/src/test/factories.ts` — new: shared factory functions
- `frontend/src/test/render-helpers.ts` — new: `renderWithAppState()` test helper
- `frontend/src/utils/format.test.ts` — new: format utility tests
- ~20 new component test files under `frontend/src/components/` and `frontend/src/pages/`
- ~5 existing component test files updated for MSW + shared factories

**Backend files affected:**
- `src/hassette/web/telemetry_helpers.py` — extract `compute_error_rate()` pure helper
- `tests/integration/test_web_api.py` — add validation/edge case tests (or new file)
- `tests/integration/test_ws_endpoint.py` — add WebSocket edge case tests

**E2E files affected:**
- `tests/e2e/mock_fixtures.py` — extract constants
- `tests/e2e/test_dashboard.py` — replace hardcoded assertions
- `tests/e2e/test_app_detail.py` — replace hardcoded assertions
- Other E2E test files with hardcoded seed data values
- `tests/e2e/conftest.py` — enable WebSocket for scope='current' test
- `tests/e2e/test_websocket.py` — add scope='current' session path test

## Open Questions

None — all decisions resolved during discovery.
