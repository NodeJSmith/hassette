---
task_id: "T04"
title: "Add log_hint WS handler and clean up store dead code"
status: "done"
depends_on: ["T01"]
implements: ["FR#6", "FR#7"]
---

## Summary
Add a `log_hint` case to the frontend WS message dispatch in `use-websocket.ts`, add a `logHintVersion` counter to the Zustand store that the hint increments, and remove the now-dead WS log content path from the store (`pushLog`, `logBuffer`, `getLogEntries`, `logVersion`, `WsLogPayload`). The existing `case "log":` dispatch is replaced by `case "log_hint":`.

## Target Files
- modify: `frontend/src/hooks/use-websocket.ts`
- modify: `frontend/src/state/store.ts`
- modify: `frontend/src/hooks/use-websocket.test.ts`
- modify: `frontend/src/state/store.test.ts`
- read: `frontend/src/api/ws-types.ts` (regenerated in T01, will have `LogHintWsMessage` type)
- read: `design/specs/114-ws-log-notify-fetch/design.md`

## Prompt
In `frontend/src/hooks/use-websocket.ts`:

1. Replace the `case "log":` block (lines 131-133) which calls `useAppStore.getState().pushLog(msg.data)` with a new `case "log_hint":` block that increments the store's `logHintVersion` counter:
```typescript
case "log_hint":
  useAppStore.getState().bumpLogHint();
  break;
```

2. The WS validator (`ws-validator.generated.ts`) will be regenerated in T01/T06 to recognize `log_hint` — the switch case just needs to match the new type string.

In `frontend/src/state/store.ts`:

3. Add a `logHintVersion` counter (number, starts at 0) and a `bumpLogHint` action that increments it. This is the signal that `use-log-data.ts` (T05) will subscribe to for triggering debounced REST fetches.

4. Remove the dead WS log content symbols:
   - `pushLog` action
   - `logBuffer` (RingBuffer)
   - `getLogEntries` selector
   - `logVersion` counter
   - `WsLogPayload` type import (from `ws-types.ts`)
   - `clearLogs` action (if it only serves the buffer path)
   - `LOG_BUFFER_CAPACITY` constant (if only used by `logBuffer`)

5. Update the reconnect handler (`handleConnected` or equivalent) — it currently clears `logBuffer` and resets `logVersion` on reconnect. Replace with resetting `logHintVersion` if needed, or remove the log-specific reconnect logic entirely (the cursor-based fetch in T05 handles reconnect recovery).

6. Update `frontend/src/hooks/use-websocket.test.ts` — remove or update tests that:
   - Assert `pushLog` is called on `"log"` messages (line 401+)
   - Assert `getLogEntries()` returns pushed entries (line 414+)
   - Add a test that `bumpLogHint` is called on a `"log_hint"` message

7. Update `frontend/src/state/store.test.ts` — remove tests for:
   - `pushLog / clearLogs` describe block (line 133+)
   - `logBuffer` isolation between store instances (line 38-42)
   - `logVersion` assertions in reconnect tests (lines 76, 85, 107, 116)
   - Add tests for the new `bumpLogHint` action and `logHintVersion` counter

## Focus
- `RingBuffer` import may become unused after removing `logBuffer` — check if anything else uses it.
- `initialState()` in store.ts constructs the initial state — `logBuffer`, `logVersion` are seeded there. Remove them and add `logHintVersion: 0`.
- The reconnect handler in `store.ts` or `use-websocket.ts` currently calls `clearLogs()` — this is part of the "clear stale WS data on reconnect" logic. After this change, there's no WS log buffer to clear. The reconnect recovery is handled by the cursor-based fetch in T05 instead.
- `frontend/src/test-setup.ts` may reference `logBuffer` or `logVersion` in test reset logic — check and update if needed.
- `frontend/src/test/log-data-test-utils.ts` imports `WsLogPayload` and builds test data around the WS merge pattern — this file is addressed in T05/T06 but be aware of the dependency.

## Verify
- [ ] FR#6: On receiving a `log_hint` WS message, the store's `logHintVersion` counter increments (triggering downstream effects in T05)
- [ ] FR#7: Multiple rapid `log_hint` messages each increment `logHintVersion` (coalescing happens downstream in T05's debounce, not here)
