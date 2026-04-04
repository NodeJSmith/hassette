# 014: WebSocket Reconnect Stability & Auto-Refresh

**Status:** archived

## Problem

Two related issues in the Preact SPA's WebSocket infrastructure:

1. **Reconnect loop (#366)**: `useWebSocket` includes `options` in its `useEffect` dependency array (`[state, options]`). Passing an inline object creates a new reference every render, causing the effect to tear down and reconnect the WebSocket on every render cycle. Currently masked because `WebSocketProvider` passes no options.

2. **Stale data after reconnect (#361)**: After a WebSocket disconnection and reconnection, all REST-fetched data (dashboard KPIs, app health, handler/job telemetry) remains stale. The `useWebSocket` hook has an `onReconnect` option that fires on the `"connected"` message, but nothing wires it up. Pages need to refetch their data automatically after reconnection.

## Architecture

### Signal-based reconnect notification

Add a `reconnectVersion: signal(0)` to `AppState`. When `useWebSocket` receives a `"connected"` message after a reconnection (not the first connect), it increments this signal. `useApi` reads the signal internally via `useAppState()` context and auto-refetches when it changes.

Key design decisions (from two rounds of adversarial critique):

- **useApi reads reconnectVersion internally** — not passed through `deps` by each call site. This makes it impossible to forget and keeps reconnect-awareness in the data layer. Every `useApi` instance gets it for free with zero page changes.
- **Use `useSignalEffect` to observe the signal** — auto-tracks signal reads without causing component re-renders, preserving `useApi`'s contract of storing state in refs/signals to avoid re-renders. (`.peek()` was considered but rejected — it doesn't trigger re-renders, so `useEffect` would never re-run.)
- **Distinguish first connect from reconnect** — `hasConnectedRef` in `useWebSocket` prevents doubling initial page load requests.
- **Dashboard's appStatus refetch is preserved** — reconnect and live status updates are orthogonal requirements. The existing `useEffect` that refetches `appGrid` on `app_status_changed` events stays as-is.

### Data flow

```
WS "connected" message
  → useWebSocket checks hasConnectedRef (first connect? skip)
  → increments state.reconnectVersion
  → useApi's internal useSignalEffect fires (reconnectVersion > 0)
  → all mounted useApi instances refetch
```

## Files Changed

| File | Change |
|------|--------|
| `frontend/src/hooks/use-websocket.ts` | Store options in useRef, remove from deps; add hasConnectedRef; increment reconnectVersion on reconnect; remove UseWebSocketOptions interface |
| `frontend/src/state/create-app-state.ts` | Add `reconnectVersion: signal(0)` |
| `frontend/src/hooks/use-api.ts` | Import useAppState, read reconnectVersion via .peek(), add useEffect for auto-refetch |

### Files NOT changed (by design)

- `frontend/src/pages/dashboard.tsx` — appStatus refetch preserved
- `frontend/src/pages/app-detail.tsx` — no changes needed
- `frontend/src/pages/apps.tsx` — no changes needed
- `frontend/src/pages/logs.tsx` — no changes needed
- `frontend/src/app.tsx` — WebSocketProvider already calls `useWebSocket(state)` with no options

## Alternatives Considered

### Manual deps threading
Every page adds `reconnectVersion.value` to their `useApi` deps. Rejected: 10+ call sites, impossible to enforce, the plan itself missed `FailedAppsAlert` during design — proving the approach is error-prone.

### Callback-based refresh
`onReconnect` callback wired from WebSocketProvider through to pages. Rejected: requires prop drilling or new context; more complex than signal approach.

## Risks

- **useApi gains a context dependency**: It now calls `useAppState()` internally, making it unusable outside the `AppStateContext.Provider` tree. Acceptable because all call sites are inside the provider. Documented in JSDoc.
- **Reconnect request stampede**: All mounted useApi instances (4-8) fire simultaneously. Acceptable — the async Python backend handles concurrent requests fine, and the request ID counter in useApi discards stale responses.
- **Dashboard double-refetch of appGrid**: The appStatus-driven refetch + reconnectVersion refetch both fire after reconnect. Harmless — request ID counter handles the race.

## Commit Strategy

1. `fix: stabilize useWebSocket options ref to prevent reconnect loop` — closes #366
2. `feat: auto-refresh all useApi data on WebSocket reconnection` — closes #361
