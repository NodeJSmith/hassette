# Context: Frontend Foundation Migration (Preact → React 19)

## Problem & Motivation

Every frontend session is a fight. Preact's ecosystem is thin — every interactive primitive (popovers, dialogs, tooltips, command palette) must be hand-built with bespoke CSS, focus management, and keyboard handling. AI agents produce inconsistent frontend output because there is no shared component vocabulary. React + shadcn/ui eliminates both problems: shadcn is heavily represented in training data, so agents produce consistent UI with minimal specification, and the React ecosystem provides the primitives Preact lacks.

The flat signal-based state architecture (`create-app-state.ts` — a bag of ~18 signals) compounds the maintenance burden. Zustand replaces it with a store organized by concern.

## Visual Artifacts

None.

## Key Decisions

1. **Zustand first, React second.** `@preact/signals` has a hard peerDependency on `preact` and patches Preact's internal `options` hook system. Signals cannot coexist with a React renderer. Zustand is renderer-agnostic and works under Preact, so the state migration runs first while Preact is still the renderer. This gives two independently-green checkpoints.
2. **Single-file Zustand store with comment sections** — not formal multi-file slices. ~17 fields, one developer. The `StateCreator` generic ceremony is unnecessary at this scale.
3. **Individual selectors per field** — one `useAppStore(s => s.X)` call per field, never multi-field object selectors. Multi-field selectors create new objects on every store update, fail `Object.is`, and cause unnecessary re-renders.
4. **RingBuffer and log-subscription callback stored as plain store fields** — Zustand has no serializability requirement (no `persist`/`devtools` middleware). Per-test isolation requires explicit `RingBuffer` reconstruction in the afterEach hook — `setState(initialState)` alone reuses the same mutable buffer instance.
5. **`sendLogLevel` is not referentially stable** — its identity changes on every WS connect/reconnect/disconnect. Must be read imperatively via `useAppStore.getState().sendLogLevel(level)`, not selected.
6. **Composite `handleWsConnected(data, isReconnect)` action** — single `setState()` spanning connection, log, and telemetry fields. Only clears stale data on reconnect, not first connect.
7. **`useSignalEffect` → `useEffect` + dependency arrays** for 3 files (use-query-invalidator, use-log-data, use-log-table). These are reactive side-effect triggers, not render-time reads.
8. **Tailwind imported without Preflight** — `@import "tailwindcss/theme.css" layer(theme); @import "tailwindcss/utilities.css" layer(utilities);` skips `preflight.css` to preserve the existing hand-rolled reset.
9. **shadcn token mapping deferred to spec 2** — no shadcn components render in this spec.

## Constraints & Anti-Patterns

- Do NOT port the flat signal bag 1:1. The Zustand store must organize state by concern.
- Do NOT enable React StrictMode — spec 2 handles StrictMode compatibility.
- Do NOT modify CSS Module files — they must continue working as-is.
- Do NOT remove `tokens.css` — shadcn theme variables will alias existing token values in spec 2.
- Do NOT use multi-field object selectors: `s => ({ a: s.a, b: s.b })` — always one selector per field.
- Do NOT use `useShallow` — individual selectors are simpler and sufficient.
- Do NOT add `@preact/signals-react` (bridge library) — rejected in Alternatives Considered.
- Do NOT remove CSS lint tooling (`tools/frontend/check_*.py`) — spec 2 handles that.
- Do NOT change the routing library (wouter works with React).
- Do NOT rewrite the WebSocket protocol or API client.

## Design Doc References

- `## Architecture` — four-phase migration plan with sequencing rationale
- `## Store shape` (inside Architecture, Phase 1) — full AppStore interface with comment-sectioned fields
- `## Stale-closure rule` — known sites requiring `useAppStore.getState()` pattern
- `## useSignalEffect migration` — structural rewrite patterns for 3 reactive-effect files
- `## Convention Examples` — Zustand store, selector usage, error boundary code samples
- `## Replacement Targets` — table mapping old→new for every package and file
- `## Test Strategy` — which test files need structural rewrites vs. import changes
- `## Behavioral Invariants` — 12 behaviors that must not change

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
    throw new ApiError(response.status, response.statusText, detail);
  }
  return response.json() as Promise<T>;
}
```

This file is framework-agnostic and must not be modified during the migration.
