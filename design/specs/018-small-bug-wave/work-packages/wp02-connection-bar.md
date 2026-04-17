# WP02: Connection bar initial state (#349)

**Lane:** todo
**Closes:** #349

## Summary

Add `"connecting"` to the WebSocket connection state machine. Show a subtle grey "Connecting..." indicator on initial load instead of flashing red "Disconnected". Move the `"connected"` signal from `onopen` to the application-level `"connected"` message. Handle first-connection failure correctly.

## Acceptance Criteria

- [ ] Page refresh shows grey "Connecting..." dot (not red "Disconnected") before WS connects
- [ ] After successful connection, shows green "Connected" with breathing pulse dot
- [ ] If server is unreachable on first load, transitions to red "Disconnected" after first failed attempt
- [ ] Reconnection after a prior successful connection still shows "Reconnecting..."
- [ ] `scheduleReconnect()` is called in all failure paths (both first-failure and reconnection)
- [ ] Grey dot uses `--ht-text-dim` token from design direction

## Files to Change

| File | Change |
|------|--------|
| `frontend/src/state/create-app-state.ts` | Add `"connecting"` to `ConnectionStatus` union, change initial value |
| `frontend/src/components/layout/status-bar.tsx` | Early return for `"connecting"` with grey dot + "Connecting...". Refactor ternary to state map |
| `frontend/src/hooks/use-websocket.ts` | Move `state.connection.value = "connected"` from `onopen` (line 27) to `case "connected"` in `onmessage`. Keep `backoffRef.current = INITIAL_BACKOFF_MS` in `onopen` (backoff reset is a transport concern). In `onclose`: check `hasConnectedRef.current` — if false, set `"disconnected"`; if true, set `"reconnecting"` |

## State Machine

```
Initial:     "connecting"
onmessage "connected":  → "connected"  (hasConnectedRef = true)
onclose (first time):   → "disconnected" + scheduleReconnect
onclose (after connect): → "reconnecting" + scheduleReconnect
unmount:     → "disconnected"
```

## Automated Tests

Add a test for the WebSocket state machine transitions in the frontend test suite. At minimum:
- `connecting → connected` (on receiving `"connected"` message)
- `connecting → disconnected` (on first close without prior connect)
- `connected → reconnecting` (on close after prior connect)

## Verification

```bash
# Build frontend
cd frontend && npm run build && npm test

# Visual check: refresh page, observe grey dot → green dot transition
# Visual check: stop hassette backend, refresh page, observe grey dot → red dot
```
