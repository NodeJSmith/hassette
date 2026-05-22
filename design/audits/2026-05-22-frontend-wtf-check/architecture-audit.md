# Frontend Architecture Audit — 2026-05-22

**Scope:** `frontend/` — 259 files, ~33.8K lines (including CSS, tests, config)
**Goal:** Evaluate whether this frontend is structured and tooled like a top-tier project

## Summary Ratings

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Project structure | GREEN | Clean, conventional, scalable |
| State management | GREEN | Signal architecture well-executed |
| Data fetching | YELLOW | Custom hook works but lacks cache, retry, abort |
| Type safety | GREEN | Zero `any`, strict config, generated types, `satisfies` factories |
| Testing infrastructure | GREEN | MSW + factories + helpers + E2E; 70% file coverage |
| Build & tooling | GREEN | Vite + ESLint + Prettier + 4 CSS lint scripts in CI |
| Error handling | GREEN | Comprehensive: boundary, API errors, reconnection, localStorage |
| Accessibility | GREEN | Systematic: skip link, focus traps, ARIA, inert |
| Performance patterns | YELLOW | Signals are good; missing virtualization and memoization |
| Design system | GREEN | Complete token system, 20+ shared components, CSS CI guards |
| Developer experience | GREEN | Fast dev loop, good test helpers, typed CSS modules |
| Missing infrastructure | YELLOW | Cache, virtualization, bundle budget are the notable gaps |

## Dimension Details

### 1. Project Structure — GREEN

Clean, conventional layout with feature-based organization:

```
src/
  api/           — client, endpoints, generated types, WS types
  state/         — centralized signal store + context
  hooks/         — custom hooks (data fetching, subscriptions, utilities)
  pages/         — route-level components with co-located CSS modules + tests
  components/
    shared/      — reusable component library (30+ components)
    layout/      — shell components (sidebar, status bar, command palette)
    app-detail/  — feature-specific components
  styles/        — shared global CSS (6 domain-organized files)
  utils/         — pure functions (formatting, sorting, status mapping)
  test/          — shared test infrastructure (factories, handlers, helpers)
```

No file exceeds 342 lines of production code. A new developer would find things quickly.

### 2. State Management — GREEN

`create-app-state.ts` (247 lines) — single factory function returning a flat object of Preact signals. No class hierarchy, no reducers, no action types.

- Clean server/UI state boundary
- Well-documented invariants (reconnectVersion vs appStatus independence)
- Proper scoping — all global state in AppState, component-local via useSignal()
- LogStore wraps RingBuffer with version signal for efficient rendering
- Context safety — useAppState() throws outside provider

### 3. Data Fetching — YELLOW

Custom `useApi` (139 lines) and `useScopedApi` (81 lines) cover ~40% of what TanStack Query provides.

**Has:** Request deduplication (requestIdRef), auto-refetch on WS reconnect, enabled/lazy options, debounced refetch with maxWait.

**Missing:**
- No response caching — every navigation re-fetches
- No retry on transient failure — one network blip leaves page in error state
- No AbortController on unmount — in-flight requests complete after navigation
- No prefetching for likely-next navigations

### 4. Type Safety — GREEN

- `strict: true`, `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`
- Zero `any` casts in production code
- OpenAPI types generated via `openapi-typescript` (2,018 lines)
- Test factories use `satisfies` for compile-time completeness
- WS types as discriminated union with CI conformance test
- ESLint `no-floating-promises: "error"`

### 5. Testing Infrastructure — GREEN

- Vitest with jsdom, v8 coverage
- MSW 2 for network-level mocking — every endpoint has a default handler
- 81 test files for 115 source files (70% file-level coverage)
- 15 factory functions with `satisfies` for schema-drift detection
- `renderWithAppState` helper with context overrides
- `onUnhandledRequest: "error"` — tests fail on unhandled API calls
- E2E via Playwright (Python-side), 14 files

**Gap:** 35 production files lack tests. Most are legitimate exemptions (types, constants, barrel exports). But `app-data.ts`, `handler-stats.ts`, `overview-tab-helpers.ts` contain untested business logic.

### 6. Build & Tooling — GREEN

- Vite 8 with Preact preset and CSS Modules source types
- ESLint 10 with TypeScript-ESLint, Prettier, import sorting
- 4 custom CSS lint scripts in CI (allowlist, dead CSS, module globals, undefined refs)
- Schema freshness checks prevent frontend/backend type drift
- Path filter skips frontend jobs when only Python changed

**Gap:** No code splitting (all pages eagerly imported), no bundle size budget, no bundle analysis tool.

### 7. Error Handling — GREEN

- Error boundary at route level with auto-reset on navigation
- `ApiError` class with structured parsing
- Per-component error state via `useApi` error signal
- WebSocket reconnection with exponential backoff (1s → 30s cap)
- Handshake timeout (10s), backoff resets only on successful handshake
- localStorage operations wrapped in try/catch with graceful fallback

### 8. Accessibility — GREEN

- Skip link to main content
- Focus management — hamburger drawer focuses first link, restores on close
- Full focus traps in ConfirmDialog and command palette
- `aria-current="page"` on active navigation
- `aria-expanded` on toggle buttons, `aria-hidden` on decorative SVGs
- `inert` attribute on layout during drawer open
- Dynamic `aria-label` on theme toggle

**Gap:** No `aria-live` regions for dynamic status updates (connection changes, telemetry alerts).

### 9. Performance Patterns — YELLOW

**Has:** Signal-based fine-grained reactivity, debounced refetch, RingBuffer for logs, lazy import for shiki, conditional drawer rendering.

**Missing:**
- No list virtualization — log table renders up to 1,000 rows, handlers table unbounded
- Minimal memoization (6 `useMemo`, 6 `useCallback`) — signals reduce the need but sort/filter/merge operations run every render
- No `memo()` on list item components

### 10. Design System — GREEN

- `tokens.css` (191 lines): surfaces, ink, lines, accent, status colors, 3 font families, 10 size steps, 13-step spacing grid, 5 border radii, 3 shadows, 10 z-index layers, 2 motion curves. Full dark theme.
- 20+ shared components with variant props
- 6 domain-organized global CSS files (718 lines)
- 4 CI scripts enforcing CSS hygiene
- No raw hex/pixel values leaking into components

### 11. Developer Experience — GREEN

- Vite HMR with backend proxy
- CSS module type generation for autocomplete
- MSW default handlers — component tests work without per-test API setup
- Factory functions with `satisfies` for instant test data
- CI mirrors local commands

**Gap:** No dev-only tools (component playground, state inspector), no `@preact/devtools`.

### 12. Missing Infrastructure — YELLOW

| Missing | Impact | Urgency |
|---------|--------|---------|
| Response caching (useApi) | Redundant API calls on navigation | Medium |
| List virtualization | DOM performance ceiling for large lists | Medium |
| Bundle size monitoring | No regression visibility | Low |
| Request abort on unmount (useApi) | Wasted network requests | Low |
| API retry with backoff (useApi) | Single-point-of-failure on network blip | Low |
| Storybook / component playground | No isolated component dev/review | Low |
| Visual regression testing | No automated screenshot diffing | Low |
| `aria-live` regions | Status changes not announced to screen readers | Low |

## Top 7 Improvements by Impact

1. **Add response caching to `useApi`** — Lightweight cache with stale-while-revalidate. WebSocket already triggers invalidation. A Map with TTL in the existing hook, not TanStack Query.

2. **Add `AbortController` to `useApi`** — ~10 lines. Pattern already exists in `useTelemetryHealth`.

3. **Add retry with backoff to `useApi`** — 2-3 retries with exponential backoff for non-4xx errors. Pattern already exists in `useTelemetryHealth`.

4. **Add list virtualization for the log table** — `@tanstack/virtual` (~8KB, works with Preact) would cap DOM nodes regardless of data volume.

5. **Add bundle size CI check** — `size-limit` with a budget. `shiki` is heavy enough to warrant monitoring.

6. **Add tests for untested utility modules** — `app-data.ts`, `handler-stats.ts`, `overview-tab-helpers.ts` contain business logic exercised only indirectly.

7. **Add `aria-live` region for connection status** — One-line fix with real accessibility value.
