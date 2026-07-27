# Design: Frontend Foundation Migration (Preact → React 19)

**Date:** 2026-07-26
**Status:** draft
**Scope-mode:** hold
**Research:** /tmp/claude-mine-define-research-8Ne89Z/brief.md

## Problem

Every frontend session is a fight. Preact's ecosystem is thin enough that every interactive primitive — popovers, dialogs, tooltips, command palette — must be hand-built with bespoke CSS, focus management, and keyboard handling. The `ConfirmDialog` is 110 lines of manual focus trap. The `InfoPopover` is 120 lines of floating-ui wiring. These are solved problems in the React ecosystem.

AI agents produce inconsistent frontend output because there is no shared component vocabulary — `design/context.md` must over-specify every visual decision to prevent invention. React + shadcn/ui eliminates this: shadcn is heavily represented in training data, so agents produce consistent, correct UI with minimal specification.

The flat signal-based state architecture (`create-app-state.ts` — a bag of ~18 signals) compounds the maintenance burden. Converting to Zustand during the migration is an opportunity to organize state by concern instead of porting the flat structure 1:1.

## Goals

- The app renders identically on React 19 + Zustand + Tailwind CSS v4 — same pages, same behavior, same visual appearance.
- All 104 existing vitest frontend tests pass (74 `.test.tsx` + 30 `.test.ts`). Test infrastructure and imports change; test assertions stay where possible. Tests that directly construct `createAppState()` need structural rewrites to seed the Zustand store instead.
- The existing E2E suite (`nox -s e2e`) passes.
- shadcn/ui is initialized and ready for component-by-component replacement in spec 2.
- State is organized by concern (connection, telemetry, preferences, time-window, logs) via comment sections in a single-file Zustand store — not a 1:1 port of the flat signal bag, and not formal multi-file slices (unnecessary for ~17 fields and one developer).

## Non-Goals

- Replacing hand-rolled components with shadcn equivalents (spec 2).
- Converting CSS Module files to Tailwind utility classes (spec 2).
- Removing CSS lint tooling (spec 2).
- Rewriting `design/context.md` (spec 2).
- Regenerating doc screenshots (spec 2).
- Changing the routing library (wouter works with React).
- Changing the data fetching layer (TanStack Query — import swap only).
- Rewriting the WebSocket protocol or API client.
- Performance optimization — bundle size increase is accepted.

## User Scenarios

### Jessica: Solo developer + AI agents

- **Goal:** Ship frontend changes without fighting the stack
- **Context:** Working on the `shadcn` branch, PRing to `frontend-migration`, main's frontend frozen

#### Foundation migration

1. **Execute the migration in phases**
   - Sees: each phase produces a green test suite
   - Decides: nothing — the phases are prescribed
   - Then: app renders identically on the new stack

2. **Verify visual parity**
   - Sees: demo stack running with the migrated frontend
   - Decides: whether each page looks correct
   - Then: merge to `frontend-migration` branch

3. **Begin spec 2 work**
   - Sees: shadcn initialized, Tailwind active alongside CSS Modules
   - Decides: which component to replace first
   - Then: spec 2 picks up from here

## Functional Requirements

- **FR#1** The frontend builds and serves on React 19 + ReactDOM via `@vitejs/plugin-react`.
- **FR#2** All JSX uses `className=` instead of `class=` (React requirement).
- **FR#3** Global state is managed by a single-file Zustand store organized by concern (connection, telemetry, preferences, time-window, logs).
- **FR#4** All code that mutates global store state outside a render body — the WebSocket handler, the telemetry health poller, the tick interval, the sidebar keydown handler — uses Zustand actions via `useAppStore.getState()`, not direct signal writes or stale selector values.
- **FR#5** The `AppStateContext` and `useAppState()` hook are removed — components use `useAppStore()` selectors.
- **FR#6** Tailwind CSS v4 is active via `@tailwindcss/vite` plugin, coexisting with CSS Modules.
- **FR#7** shadcn/ui is initialized with New York style and theme CSS variables mapped to the existing design token values.
- **FR#8** TanStack Query uses `@tanstack/react-query` (API-identical import swap).
- **FR#9** Tests use `@testing-library/react` and the `renderWithAppState` helper is rewritten for Zustand.
- **FR#10** The error boundary uses `react-error-boundary` (replacing Preact's `useErrorBoundary` hook).
- **FR#11** The log ring buffer and log-subscription callback live inside the store as plain (non-serialized) fields in the logs section. Zustand does not require serializability (no `persist`/`devtools` middleware in use). Per-test isolation requires explicit `RingBuffer` reconstruction in the `afterEach` hook — `setState(initialState)` alone reuses the same mutable buffer instance.

## Edge Cases

- **CSS Modules + Tailwind coexistence:** Existing CSS Modules use `var(--token)` references, not `@apply`. Tailwind's Vite plugin skips files that don't use Tailwind utilities, so the 66 module files add zero build overhead. No `@reference` directive needed.
- **`class=` → `className=` in dynamic expressions:** Template literals (`class={\`ht-layout${...}\`}`) and `clsx()` calls (`class={clsx(styles.foo, ...)}`) need the same attribute rename. A codemod handles all forms; manual review catches any edge cases in string interpolation.
- **Signal `.value` read misses:** If a signal `.value` read is missed during the Zustand conversion, it silently renders `undefined` instead of crashing. Mitigation: grep for remaining `.value` references after conversion; the demo stack smoke test catches visual regressions.
- **React 18+ StrictMode double-rendering:** Development mode double-invokes effects. Tests that assert "called exactly once" for effects may fail. Mitigation: don't enable StrictMode in tests (vitest config); address StrictMode compatibility in spec 2 if desired.
- **`useSubscribe()` removal:** This hook forces signal re-reads by calling `.value` on passed signals. With Zustand, components re-render automatically via selectors — every `useSubscribe()` call is deleted outright.
- **`computed()` signals:** `effectiveTimePreset` uses `computed()` to derive from `timePreset` and `urlWindowParam`. With Zustand, this becomes a derived selector or inline `useMemo` in the consuming component.

## Acceptance Criteria

- **AC#1** `cd frontend && npm run build` exits 0 (FR#1, FR#2).
- **AC#2** `cd frontend && npm run test` reports 0 failures across all 104 test files (FR#3–FR#11).
- **AC#3** `grep -rn ' class=' frontend/src/ --include='*.tsx' | grep -v className | grep -v test` returns no results (FR#2).
- **AC#4** `grep -rn 'from.*preact' frontend/src/ --include='*.ts' --include='*.tsx'` returns no results (FR#1).
- **AC#5** `grep -rn '@preact/signals\|from.*preact' frontend/src/ --include='*.ts' --include='*.tsx' | grep -v node_modules` returns no results — no Preact signal imports remain (FR#3, FR#5).
- **AC#6** `cd frontend && npx shadcn@latest add button --dry-run` succeeds (FR#7 — shadcn init is complete and functional).
- **AC#7** The demo stack (`mise run demo`) renders all 7 pages (apps, handlers, logs, config, diagnostics, app-detail, design) without visual regression (FR#1–FR#11). The `/design` page exercises design token rendering and is the most exposed to Tailwind/CSS-Modules coexistence issues.
- **AC#8** `uv run nox -s e2e` passes (behavioral parity with pre-migration state).

## Key Constraints

- **Do not port the flat signal bag 1:1.** The Zustand store must organize state by concern using comment sections. A flat store with 18+ undifferentiated top-level fields is the architecture being replaced, not preserved. Use a single-file store — formal multi-file slices with `StateCreator` generics are unnecessary at this scale.
- **Do not enable React StrictMode** in this spec. StrictMode compatibility (double-effect handling) is addressed in spec 2 alongside component cleanup.
- **Do not modify CSS Module files.** They must continue working as-is for the transition period. Spec 2 handles their replacement.
- **Do not remove `tokens.css`.** shadcn's theme variables alias the existing token values. The token file stays until spec 2 completes the visual migration.

## Dependencies and Assumptions

- **npm packages:** `react`, `react-dom`, `@vitejs/plugin-react`, `zustand`, `@tailwindcss/vite`, `tailwindcss`, `@tanstack/react-query`, `@testing-library/react`, `react-error-boundary`. All confirmed React 19 compatible.
- **Removed packages:** `@preact/signals` (end of Phase 1, after all ~31 signal consumer files are converted to Zustand); `preact`, `@preact/preset-vite`, `@tanstack/preact-query`, `@testing-library/preact`, `vite-css-modules` (Phase 2, the React framework swap).
- **`wouter` stays:** peerDependency `react: ">=16.8.0"` — confirmed React 19 compatible.
- **`sonner` stays:** peerDependency `react: "^18.0.0 || ^19.0.0"` — confirmed React 19 compatible.
- **`clsx` stays:** framework-agnostic.
- **`@floating-ui/dom` stays:** used by `InfoPopover` and `column-filter-popover` — becomes orphaned after spec 2 replaces both with Radix's built-in positioning.
- **Docker + Playwright required** for AC#7 and AC#8 (demo stack and E2E tests).

## Architecture

### Phase 1: State migration (signals → Zustand)

Replace the flat signal bag in `create-app-state.ts` with a single-file Zustand store organized by concern via comment sections. This runs first — while the app is still on Preact — because `@preact/signals` has a hard peerDependency on `preact` and patches Preact's internal `options` hook system. Signals cannot coexist with a React renderer. Zustand is renderer-agnostic and works under Preact, so converting state first gives an independently-green checkpoint before the framework swap.

Install `zustand`. Remove `@preact/signals` at the end of this phase, once all signal consumers are converted (~21 non-test files using global `useAppState()` signals + ~10 test-only signal consumers = ~31 total files importing from `@preact/signals`).

**Store shape** (`src/state/store.ts` — new file, replaces `create-app-state.ts`):

```typescript
interface AppStore {
  // --- connection ---
  connection: ConnectionStatus;
  uptimeSeconds: number | null;
  systemVersion: string | null;
  setConnection: (status: ConnectionStatus) => void;

  // --- telemetry ---
  appStatus: Record<string, AppStatusEntry>;
  serviceStatus: Record<string, ServiceStatusEntry>;
  executionCompleted: WsExecutionCompletedPayload[] | null;
  telemetryDegraded: boolean;
  droppedOverflow: number;
  droppedExhausted: number;
  droppedShutdown: number;
  errorHandlerFailures: number;
  updateAppStatus: (key: string, entry: AppStatusEntry) => void;
  updateServiceStatus: (name: string, entry: ServiceStatusEntry) => void;
  clearServiceStatus: () => void;
  setExecutionCompleted: (data: WsExecutionCompletedPayload[]) => void;
  setTelemetryHealth: (data: Partial<TelemetryHealthFields>) => void;

  // --- preferences ---
  theme: "dark" | "light";
  sidebarCollapsed: boolean;
  setTheme: (t: "dark" | "light") => void;
  setSidebarCollapsed: (v: boolean) => void;

  // --- time window ---
  timePreset: TimePreset;
  urlWindowParam: TimePreset | null;
  tick: number;
  setTimePreset: (p: TimePreset) => void;
  setUrlWindowParam: (p: TimePreset | null) => void;
  incrementTick: () => void;

  // --- logs ---
  logVersion: number;
  logBuffer: RingBuffer<WsLogPayload>;
  sendLogLevel: (level: string) => void;
  setSendLogLevel: (fn: (level: string) => void) => void;
  pushLog: (entry: WsLogPayload) => void;
  clearLogs: () => void;
  getLogEntries: () => WsLogPayload[];

  // --- composite actions (domain events spanning multiple concerns) ---
  handleWsConnected: (data: WsConnectedPayload, isReconnect: boolean) => void;
}
```

**Log ring buffer:** Store the `RingBuffer` instance as a plain field in the logs section of the store. `pushLog` increments `logVersion` and pushes to the buffer. `getLogEntries()` reads from the store's buffer field. Zustand has no serializability requirement (no `persist`/`devtools` middleware in use), so storing the buffer directly is safe. **Test isolation note:** `useAppStore.setState(initialState)` alone does NOT restore buffer isolation — it reassigns the same mutable `RingBuffer` object reference without reconstructing it. The `afterEach` hook must explicitly construct a fresh buffer (see Phase 4).

**Log subscription callback:** `updateLogSubscription` and `setUpdateLogSubscription` are a closure-backed callback pair — the WS handler wires a real implementation via `setUpdateLogSubscription`, and the log table UI calls `updateLogSubscription` to change the streaming log level. In Zustand, store both as plain function fields in the logs section: `sendLogLevel: (level: string) => void` (the outbound callback, initially a no-op) and `setSendLogLevel: (fn) => void` (the wiring action). This collapses the current two-field dance into a direct store field and restores per-test isolation for free via `useAppStore.setState(initialState)`. **Note:** `sendLogLevel` is intentionally *not* referentially stable — its identity changes on every WS connect/reconnect/disconnect via `setSendLogLevel`. Components must read it imperatively at the point of use (`useAppStore.getState().sendLogLevel(level)`), not select it as a rendered value, to avoid invoking a function bound to an already-closed socket.

**Derived state:** `effectiveTimePreset` (currently `computed()`) becomes an inline selector:
```typescript
const effectiveTimePreset = useAppStore(s => s.urlWindowParam ?? s.timePreset);
```

**Context removal:** Delete `src/state/context.ts` (`AppStateContext`, `useAppState()`). Components import `useAppStore` directly from the store module.

**WebSocket handler** (`src/hooks/use-websocket.ts`): Replace `batch()` calls with Zustand actions. Access the store via `useAppStore.getState()` for non-component code (the WS handler runs inside a `useEffect`). The `connected` case currently wraps updates spanning connection, log, and telemetry fields in one `batch()` — replace this with a composite action `handleWsConnected(data)` implemented as a single `useAppStore.setState()` call that writes all affected fields atomically. This names the domain event explicitly rather than relying on implicit React 18+ auto-batching, which would break if an `await` were inserted between separate action calls.

**Stale-closure rule (general):** Any `.value` read or global-state write inside a callback registered via `addEventListener`, `setTimeout`, or `setInterval` within a `useEffect` must use `useAppStore.getState().field` — not a top-level selector — because the callback closure captures the render-time value and goes stale. Known sites requiring this pattern:
- `use-websocket.ts` — WS handler (already called out above)
- `app.tsx:106-111` — keydown handler (reads `sidebarCollapsed`)
- `use-telemetry-health.ts:27-66` — `setInterval`-driven health poller that writes 5 global fields (`telemetryDegraded`, `droppedOverflow`, `droppedExhausted`, `droppedShutdown`, `errorHandlerFailures`)
- `app.tsx:55-58` — `setInterval` tick updater

Before starting Phase 1, grep for all three mechanisms: `grep -rn "addEventListener\|setTimeout\|setInterval" --include='*.ts' --include='*.tsx' src/ | grep -B2 -A2 '\.value'` (scoped to files with `useEffect`) to build the complete list. Do not grep for `addEventListener` alone — the rule names three trigger mechanisms and the audit must match.

**Global signal consumer migration** (~20 non-test files that read global `AppState` signals via `useAppState()`): Replace each `state.X.value` read with an individual `useAppStore(s => s.X)` selector call — one call per field, never a multi-field object selector (`s => ({ a: s.a, b: s.b })`). Multi-field object selectors create a new object on every store update, fail `Object.is`, and cause unnecessary re-renders (Zustand docs warn this can produce infinite update loops). Sites that currently destructure multiple fields from `useAppState()` (e.g., `apps.tsx` reads 4 fields, `time-preset-selector.tsx` reads 3) must be split into N individual `useAppStore()` calls. Delete all `useSubscribe()` calls.

**`useSubscribe` hook** (`src/hooks/use-subscribe.ts`): Delete entirely. With Zustand, components re-render automatically when their selected state changes.

**`useSignalEffect` migration** (3 files — structural rewrites, not mechanical selector conversion): `useSignalEffect` is a Preact reactive-effect primitive with no 1:1 Zustand equivalent. These files use it for side-effect triggers keyed off signal changes, not render-time reads:

- `use-query-invalidator.ts` — Change signature from `(signal: ReadonlySignal<T>, ...)` to `(value: T, ...)`. Replace `useSignalEffect(() => { const value = signal.value; ...})` with `useEffect(() => {...}, [value])`. Drop the internal `Object.is`/`peek()` staleness guard (the dependency array already gates re-entry). 8 call sites across 6 files need updated argument forms. The debounced cache invalidation behavior is an explicit INVARIANT in the source (`create-app-state.ts:104-109`) — it must remain independent from immediate reconnect invalidation.
- `use-log-data.ts` (`useThrottledLogVersion`) — Replace `useSignalEffect` with `useEffect` + dependency on `logVersion`. Preserve the throttle to prevent render storms during log floods.
- `use-log-table.tsx` — Replace `useSignalEffect` with `useEffect` + dependency on the filter level value. Calls `useAppStore.getState().sendLogLevel(level)` imperatively (see `sendLogLevel` referential-stability note above).

### Phase 2: React framework swap

Replace the Preact runtime with React 19. With all signal consumers already on Zustand (Phase 1), this is a purely mechanical change — no state layer dependencies on Preact remain.

**Package swap:** Remove `preact`, `@preact/preset-vite`, `@tanstack/preact-query`, `@testing-library/preact`, `vite-css-modules`. Install `react`, `react-dom`, `@vitejs/plugin-react`, `@tanstack/react-query`, `@testing-library/react`, `react-error-boundary`.

**Import conversion** (all files in `frontend/src/`):
- `from "preact"` → `from "react"` (types: `ComponentChildren` → `ReactNode`, `JSX` → `React.JSX`)
- `from "preact/hooks"` → `from "react"`
- `from "@tanstack/preact-query"` → `from "@tanstack/react-query"`
- `from "@testing-library/preact"` → `from "@testing-library/react"`

**JSX attribute:** `class=` → `className=` across all TSX files. Use a codemod or targeted sed. The occurrences include static strings (`class="foo"`), template literals (`class={\`...\`}`), and `clsx()` calls (`class={clsx(...)}`). All forms need the same attribute rename.

**Vite config** (`vite.config.ts`): Replace `@preact/preset-vite` with `@vitejs/plugin-react`. Remove `vite-css-modules` plugin (Vite handles CSS Modules natively; `.d.ts` generation is dropped).

**Vitest config** (`vitest.config.ts`): Same plugin swap.

**tsconfig.json:** Change `jsxImportSource` from `"preact"` to `"react-jsx"`. Remove `"preact"` and add `"react"` to compilerOptions as needed.

**Entry point** (`src/main.tsx`): `render(<App />, el)` → `createRoot(el).render(<App />)`.

**Error boundary** (`src/components/layout/error-boundary.tsx`): Replace `useErrorBoundary` (Preact-only) with `react-error-boundary`'s `ErrorBoundary` component. Preserve the existing reset-on-key-change behavior via the `resetKeys` prop.

**Test setup** (`src/test-setup.ts`): Keep all existing polyfills (`requestAnimationFrame`, `cancelAnimationFrame`, `ResizeObserver`, `matchMedia`) and MSW setup. The rAF polyfill is used by application code (`command-palette.tsx:55` calls `requestAnimationFrame` for autofocus), not just Preact internals — jsdom doesn't provide it natively.

**Local signal migration** (~16 non-test files using `useSignal()` for per-component state): Replace `useSignal(init)` with React's `useState(init)`. These are local UI state (sort order, drawer open/close, filter values) — they must NOT go into the global Zustand store. Replace `.value` reads with the state variable and `.value =` writes with the setter. (Note: `useSignal` depends on `preact/hooks` and cannot be converted in Phase 1 while Preact is still the renderer — it must wait for the React swap.)

### Phase 3: Tailwind CSS v4 + shadcn init

**Tailwind setup:**
- Install `tailwindcss` and `@tailwindcss/vite`.
- Add `tailwindcss()` to Vite plugins in `vite.config.ts`.
- Import Tailwind **without Preflight** to avoid colliding with the existing hand-rolled reset (`styles/reset.css`): `@import "tailwindcss/theme.css" layer(theme); @import "tailwindcss/utilities.css" layer(utilities);` — this skips `preflight.css`, preserving the current visual appearance. Spec 2 can evaluate adopting Preflight when the existing reset is removed.
- No `tailwind.config.js` needed — Tailwind v4 uses CSS-based configuration via `@theme`.

**shadcn init:**
- Run `npx shadcn@latest init` — select New York style, configure `components.json` with `@/components/ui` as the component directory.
- shadcn generates theme CSS variables (`--background`, `--foreground`, `--primary`, etc.).

**Token mapping:** Deferred to spec 2. No shadcn components render in this spec (it's an explicit non-goal), so writing token aliases now would be dead code that needs re-verification against real rendered output anyway. The `shadcn init` CLI generates a default theme file; spec 2 writes the real alias mapping when the first shadcn component actually needs to look right against live content.

### Phase 4: Test infrastructure update

**`renderWithAppState`** (`src/test/render-helpers.tsx`): Rewrite to wrap components in `QueryClientProvider` only — Zustand doesn't need a context provider. Provide a `storeOverrides` option that calls `useAppStore.setState(overrides)` before each test.

**Test cleanup hook:** Add `afterEach(() => useAppStore.setState({ ...initialState, logBuffer: new RingBuffer(LOG_BUFFER_CAPACITY) }))` to reset store between tests. Plain `setState(initialState)` is insufficient for class-instance fields — it reassigns the same mutable `RingBuffer` object without reconstructing it, leaking entries across tests.

**`src/test/render-helpers.tsx` — mockMediaQueryMatches:** Keep as-is (framework-agnostic).

**MSW handlers** (`src/test/handlers.ts`, `src/test/server.ts`): No changes — MSW is framework-agnostic.

## Implementation Preferences

- **React 19** (latest stable) with `@vitejs/plugin-react`.
- **Zustand** for state management — single-file store with comment-sectioned fields, organized by concern.
- **Tailwind CSS v4** via `@tailwindcss/vite` plugin — no PostCSS config, no `tailwind.config.js`.
- **shadcn/ui** New York style — `components.json` with `@/components/ui` as component directory.
- **`react-error-boundary`** for error boundaries (replaces Preact's `useErrorBoundary`).
- **No React StrictMode** in this spec.
- **`class=` → `className=` via codemod** — a dedicated commit for reviewability.
- **Keep `@floating-ui/dom`** — still used by `InfoPopover` until spec 2.

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `preact`, `preact/hooks` | `react`, `react-dom` | Remove package, update all imports |
| `@preact/preset-vite` | `@vitejs/plugin-react` | Remove package, update vite configs |
| `@preact/signals` | `zustand` | Remove package, rewrite state layer |
| `@tanstack/preact-query` | `@tanstack/react-query` | Remove package, update imports |
| `@testing-library/preact` | `@testing-library/react` | Remove package, update imports |
| `vite-css-modules` | (Vite native CSS Modules) | Remove package, remove from vite config |
| `src/state/create-app-state.ts` | `src/state/store.ts` (Zustand) | Delete old, create new |
| `src/state/context.ts` | Direct `useAppStore` imports | Delete file |
| `src/hooks/use-subscribe.ts` | (not needed with Zustand) | Delete file |
| `src/hooks/use-signal.ts` | `React.useState` (local component state) | Delete file; convert ~16 consumer files to `useState` |

## Convention Examples

### Zustand single-file store (target convention)

**Source:** Zustand docs — single store

```typescript
const useAppStore = create<AppStore>()((set, get) => ({
  // --- connection ---
  connection: "connecting" as ConnectionStatus,
  uptimeSeconds: null,
  systemVersion: null,
  setConnection: (status) => set({ connection: status }),

  // --- telemetry ---
  // ... fields and actions ...

  // --- composite actions ---
  handleWsConnected: (data, isReconnect) => set({
    connection: "connected",
    uptimeSeconds: data.uptime_seconds,
    systemVersion: data.version ?? null,
    // Only clear stale data on reconnect, not first connect
    ...(isReconnect && {
      logBuffer: new RingBuffer(LOG_BUFFER_CAPACITY),
      logVersion: 0,
      serviceStatus: {},
    }),
  }),
}));
```

### Zustand selector usage (target convention)

**Source:** Zustand docs — selectors

```typescript
// DO: one useAppStore call per field — always
const connection = useAppStore((s) => s.connection);
const theme = useAppStore((s) => s.theme);
const tick = useAppStore((s) => s.tick);

// DON'T: destructure the whole store
const { connection, theme, tick } = useAppStore();

// DON'T: multi-field object selector (new object every update, fails Object.is)
const { connection, theme } = useAppStore((s) => ({ connection: s.connection, theme: s.theme }));
```

### React error boundary (target convention)

**Source:** react-error-boundary docs + existing `error-boundary.tsx` fallback

```typescript
import { ErrorBoundary } from "react-error-boundary";

function ErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  const message = error instanceof Error ? error.message : "An unexpected error occurred";
  return (
    <Card role="alert" data-testid="error-card">
      <h2>Something went wrong</h2>
      <p>{message}</p>
      <Button onClick={resetErrorBoundary}>Try again</Button>
    </Card>
  );
}

<ErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[location]}>
  <Routes />
</ErrorBoundary>
```

Preserve the existing fallback's visual treatment (`Card`, heading, `Button`, `data-testid="error-card"`) and `instanceof Error` guard. Add `role="alert"` for accessibility.

### Existing API client (convention to preserve)

**Source:** `frontend/src/api/client.ts`

```typescript
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    // error handling...
    throw new ApiError(response.status, response.statusText, detail);
  }
  return response.json() as Promise<T>;
}
```

This file is framework-agnostic and must not be modified during the migration.

## Alternatives Considered

### Stay on Preact, add a headless UI library

Use a headless component library compatible with Preact (e.g., Kobalte for Solid, or a Preact-specific fork). **Rejected:** No mature headless library targets Preact. The ecosystem gap is the problem — staying on Preact means staying in the gap.

### Preact + preact/compat + shadcn

Use Preact's React compatibility layer to run shadcn components. **Rejected:** `preact/compat` doesn't fully support Radix UI primitives (they use React internals like `flushSync`, portal context, and ref patterns that break under compat). The compat layer papers over the ecosystem gap without closing it.

### React + Zustand + CSS Modules (no Tailwind)

Switch to React and Zustand but keep CSS Modules for styling. **Rejected:** The agent consistency benefit comes from shadcn + Tailwind, not just React. Keeping CSS Modules means keeping the custom design token system and the CSS lint tooling. Tailwind is part of the solution.

### @preact/signals-react (bridge library)

Use `@preact/signals-react` to keep signal code working under React. **Rejected:** This library has had stability issues and adds a dependency that would be removed anyway once Zustand is in place. A clean Zustand conversion is simpler long-term.

## Test Strategy

### Required Test Types

- **Unit/integration (vitest):** All 104 existing test files (74 `.test.tsx` + 30 `.test.ts`) must pass. Test infrastructure (imports, render helpers) changes; test assertions stay.
- **E2E (Playwright):** The existing suite (`nox -s e2e`) validates real browser rendering. Run at the end to confirm visual parity.
- **Manual smoke test:** Run the demo stack and verify all 7 pages render correctly (apps, handlers, logs, config, diagnostics, app-detail, design). Catches signal-to-Zustand misses that unit tests won't find.

### Existing Tests to Adapt

All 104 test files need import updates:
- `from "@testing-library/preact"` → `from "@testing-library/react"` (all `.test.tsx` files)
- `from "preact/hooks"` → `from "react"` (test files using hooks)
- `from "@preact/signals"` → removed (test files that create signals for test state)
- `renderWithAppState` helper rewritten — `stateOverrides` becomes `storeOverrides` using Zustand's `setState` API

**Tests requiring structural rewrites** (directly construct `createAppState()` — not just import changes):
- `src/hooks/use-websocket.test.ts` — constructs `createAppState()` in every test case (~22 instances). Rewrite to seed the Zustand store via `useAppStore.setState()` or a test helper.
- `src/hooks/use-scoped-query.test.ts` — constructs `createAppState()` (~11 instances). Same Zustand seeding pattern.
- `src/hooks/use-telemetry-health.test.ts` — constructs `createAppState()` (~11 instances).
- `src/hooks/use-relative-time.test.ts` — constructs `createAppState()` (~4 instances).
- `src/hooks/use-breadcrumbs.test.tsx` — constructs `createAppState()` and spreads with a `computed` signal override.
- `src/components/app-detail/unified-handler-row.test.tsx` — wraps in `AppStateContext.Provider` with `createAppState()`.
- `src/components/shared/log-table/use-log-table.test.tsx` — constructs `createAppState()`.
- `src/components/shared/log-table/use-log-data.test.ts` — constructs `createAppState()` (~2 instances).
- `src/state/create-app-state.test.ts` — tests the old factory directly. This file is deleted (see Tests to Remove) and replaced if store-level tests are desired.

E2E tests (`tests/e2e/*.py`): **No changes needed.** All selectors use `data-testid`, ARIA roles, and text content — zero CSS class selectors.

### New Test Coverage

No new test files. The migration preserves behavior; existing tests verify it. The Zustand store is exercised through component tests that already test state-dependent rendering.

### Tests to Remove

- `src/state/create-app-state.test.ts` — replaced by the Zustand store (if store-level tests are desired, write them against the new store shape, but component tests already cover the behavior).

## Documentation Updates

- **`CLAUDE.md`:** Update the CSS Architecture section to note Tailwind + CSS Modules coexistence. Update the `package.json` dependencies description. Note that `class=` is now `className=`.
- **`frontend/README.md`** (if it exists): Update setup instructions for React + Tailwind.
- No changelog entry (this is `chore:` — internal migration, no user-facing change).

## Impact

### Changed Files

**Cross-cutting (high risk):**
- modify `frontend/package.json` — swap all Preact deps for React equivalents, add Tailwind + Zustand
- modify `frontend/vite.config.ts` — swap Preact plugin for React + Tailwind plugins
- modify `frontend/vitest.config.ts` — swap Preact plugin for React plugin
- modify `frontend/tsconfig.json` — change jsxImportSource from preact to react-jsx

**State layer:**
- delete `frontend/src/state/create-app-state.ts` — replaced by Zustand store
- delete `frontend/src/state/create-app-state.test.ts` — test for old state factory
- delete `frontend/src/state/context.ts` — AppStateContext/useAppState no longer needed
- create `frontend/src/state/store.ts` — single-file Zustand store organized by concern
- delete `frontend/src/hooks/use-subscribe.ts` — not needed with Zustand
- delete `frontend/src/hooks/use-signal.ts` — not needed with Zustand
- modify `frontend/src/hooks/use-websocket.ts` — Zustand actions replace signal mutation

**Framework swap (mechanical, all TSX/TS in `frontend/src/`):**
- modify non-test `.tsx`/`.ts` files — import path changes, `class=`→`className=`, signal→useState/Zustand
- modify all 104 test files — import path changes, render helper updates; ~9 test files need structural rewrites (see Test Strategy)

**Tailwind + shadcn (additive):**
- modify `frontend/src/global.css` — add `@import "tailwindcss"`
- create `frontend/src/components/ui/` — shadcn component directory (empty initially)
- create `frontend/components.json` — shadcn configuration

**Error boundary:**
- modify `frontend/src/components/layout/error-boundary.tsx` — replace useErrorBoundary with react-error-boundary

**Entry point:**
- modify `frontend/src/main.tsx` — createRoot API
- modify `frontend/src/app.tsx` — remove signal reads, use Zustand selectors

**Test infrastructure:**
- modify `frontend/src/test/render-helpers.tsx` — rewrite for Zustand + React
- modify `frontend/src/test-setup.ts` — remove Preact-specific polyfills

### Behavioral Invariants

- All 7 pages render with the same data and layout (apps, handlers, logs, config, diagnostics, app-detail, design).
- WebSocket connection lifecycle (connect, reconnect, backoff) is unchanged.
- TanStack Query cache invalidation on reconnect is unchanged.
- Log ring buffer behavior (capacity, push, clear) is unchanged.
- Theme toggle persists to localStorage and applies on reload.
- Sidebar collapse state persists to localStorage.
- Time preset persists to localStorage; URL `?window=` override takes priority.
- Command palette keyboard shortcut (Ctrl+K) works.
- Debounced WS-triggered cache invalidation remains independent from immediate reconnect invalidation (source INVARIANT at `create-app-state.ts:104-109`).
- Log-table rendering stays throttled during high-volume log streaming (prevents render storms).
- E2E test selectors (data-testid, ARIA roles) continue to match.

### Blast Radius

- **Backend:** Zero impact. The backend serves the SPA bundle and API; neither changes.
- **Doc screenshots:** The `capture_screenshots.py` tool runs against the built SPA. If the SPA renders identically (AC#7), screenshots don't change.
- **CI:** `npm run build` and `npm run test:coverage` in `.github/workflows/tests.yml` — commands unchanged, just a different framework under the hood. `npm run types` (openapi-typescript) — unchanged. The CSS lint CI jobs (`check_dead_global_css.py`, `check_global_css_allowlist.py`, etc.) — unchanged in this spec (spec 2 removes them).

## Open Questions

None — all items resolved during discovery and investigation.
