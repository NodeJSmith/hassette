---
task_id: "T01"
title: "Create Zustand store with all fields and actions"
status: "planned"
depends_on: []
implements: ["FR#3", "FR#11"]
---

## Summary

Create the new Zustand store file (`src/state/store.ts`) that replaces the flat signal bag in `create-app-state.ts`. This is the foundation — all subsequent tasks depend on it. The store defines all fields organized by concern (connection, telemetry, preferences, time-window, logs), all actions, and the composite `handleWsConnected` action. No consumers are migrated in this task; the store is created alongside the existing signal state.

## Target Files

- create: `frontend/src/state/store.ts`
- read: `frontend/src/state/create-app-state.ts`
- read: `frontend/src/utils/ring-buffer.ts`
- read: `design/specs/020-frontend-foundation-migration/design.md`

## Prompt

Create `frontend/src/state/store.ts` — a single-file Zustand store implementing the `AppStore` interface defined in the design doc (Architecture > Phase 1 > Store shape). Install `zustand` via `cd frontend && npm install zustand`.

The store replaces `create-app-state.ts` but does NOT delete it — consumers are migrated in T02. Both files coexist temporarily.

**Implementation details:**

1. Define the `AppStore` interface with all fields organized by comment sections: `// --- connection ---`, `// --- telemetry ---`, `// --- preferences ---`, `// --- time window ---`, `// --- logs ---`, `// --- composite actions ---`.

2. Fields and actions — copy the full interface from the design doc's Store shape code block. Key points:
   - `logBuffer: RingBuffer<WsLogPayload>` — store the RingBuffer instance directly as a plain field (Zustand has no serializability requirement)
   - `sendLogLevel: (level: string) => void` — initially a no-op. Identity changes on every WS connect/disconnect; NOT referentially stable
   - `setSendLogLevel: (fn: (level: string) => void) => void` — wiring action
   - `getLogEntries: () => WsLogPayload[]` — reads from the store's buffer field
   - `clearServiceStatus: () => void` — full-record reset for reconnect path
   - `handleWsConnected: (data: WsConnectedPayload, isReconnect: boolean) => void` — composite action spanning connection, log, and telemetry fields. Only clears stale data (logBuffer, logVersion, serviceStatus) on reconnect, not first connect.

3. Export `useAppStore` (the hook) and `initialState` (a factory function that returns a fresh state object including `new RingBuffer(LOG_BUFFER_CAPACITY)`).

4. Import types from existing type files. The `WsLogPayload`, `WsConnectedPayload`, `WsExecutionCompletedPayload`, `ConnectionStatus`, `AppStatusEntry`, `ServiceStatusEntry`, `TimePreset`, and `TelemetryHealthFields` types should already exist or be derivable from `create-app-state.ts` and the WebSocket types.

5. Use `create<AppStore>()((set, get) => ({ ... }))` — see the Convention Examples in context.md for the exact pattern.

## Focus

- Read `frontend/src/state/create-app-state.ts` carefully — it defines the current signal bag with all field names, initial values, and the `LOG_BUFFER_CAPACITY` constant. Mirror every field.
- Read `frontend/src/utils/ring-buffer.ts` — it's a plain mutable class with `push`, `toArray`, `clear`, `count`, and `capacity`. Import and use it directly.
- The `effectiveTimePreset` computed signal becomes a derived selector: `useAppStore(s => s.urlWindowParam ?? s.timePreset)` — this is consumed inline by components, not stored in the store.
- Theme and sidebarCollapsed persist to localStorage in the current code. The Zustand store itself does not persist — localStorage read/write happens in the component layer (unchanged in this task).
- Do NOT add Zustand middleware (`persist`, `devtools`, `immer`). The store is intentionally plain.

## Verify

- [ ] FR#3: `frontend/src/state/store.ts` exists and exports `useAppStore` and `initialState`. The store has comment-sectioned fields for connection, telemetry, preferences, time-window, logs, and composite actions.
- [ ] FR#11: `logBuffer` is a `RingBuffer` instance stored as a plain field. `sendLogLevel` and `setSendLogLevel` are plain function fields. `initialState()` returns a fresh `RingBuffer` on each call.
