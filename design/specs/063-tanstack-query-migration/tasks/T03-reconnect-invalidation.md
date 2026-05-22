---
task_id: "T03"
title: "Add reconnect invalidation to WebSocket handler"
status: "done"
depends_on: ["T01"]
implements: ["FR#6", "AC#11"]
---

## Summary

Wire the global reconnect invalidation into `use-websocket.ts`. When the WebSocket reconnects (not first connect), call `queryClient.invalidateQueries()` with no filter to invalidate all active query caches immediately. This fires alongside the existing `reconnectVersion` increment — both mechanisms coexist during the migration period. The `reconnectVersion` increment is removed later in T09 after all consumers are deleted.

## Prompt

### 1. Modify `frontend/src/hooks/use-websocket.ts`

Read the full file (187 lines). The reconnect handler is at lines 76-84:

```typescript
if (hasConnectedRef.current) {
  state.logs.clear();
  state.serviceStatus.value = {};
  state.reconnectVersion.value = state.reconnectVersion.value + 1;
} else {
  hasConnectedRef.current = true;
}
```

Add `queryClient.invalidateQueries()` inside the `if (hasConnectedRef.current)` block — AFTER the existing lines. Do NOT remove the `reconnectVersion` increment yet (other hooks still consume it until T09).

To access the query client, the hook needs `useQueryClient()` from `@tanstack/preact-query`. The `useWebSocket` function currently accepts `(state: AppState)` as its parameter. Add `useQueryClient()` at the top of the hook body:

```typescript
const queryClient = useQueryClient();
```

This works because `WebSocketProvider` renders inside `QueryClientProvider` in `app.tsx` (see T01). No signature change needed.

The `invalidateQueries()` call with no arguments invalidates ALL active queries. This is intentional — on reconnect, all server data should be considered stale.

### 2. Update `frontend/src/hooks/use-websocket.test.ts`

Read the full test file. All existing tests use bare `renderHook` with no provider wrapper. Every test must be updated to use the `renderHookWithProviders` helper from `frontend/src/test/query-test-utils.ts` (created in T01) so that `useQueryClient()` has a provider.

Add two new test cases:
- **On reconnect** (`hasConnectedRef.current` is true): verify `queryClient.invalidateQueries()` is called with no filter. Use `vi.spyOn(queryClient, 'invalidateQueries')`.
- **On first connect**: verify `invalidateQueries()` is NOT called.

For the spy setup: create a test query client via `createTestQueryClient()`, spy on its `invalidateQueries` method, and pass it to `renderHookWithProviders`.

## Focus

- `use-websocket.ts` imports are at lines 1-5. Add `import { useQueryClient } from "@tanstack/preact-query";`.
- The hook signature is `export function useWebSocket(state: AppState): void` — do NOT change it.
- The reconnect block is inside a `case "connected":` of a switch statement inside a `useEffect` callback. The `useQueryClient()` call must be at the hook's top level (React rules of hooks), not inside the effect.
- There are 20 existing tests in `use-websocket.test.ts`. Each one needs the provider wrapper added. This is a bulk update — every `renderHook(() => useWebSocket(state))` becomes `renderHookWithProviders(() => useWebSocket(state), { stateOverrides: ... })` (or equivalent).
- The test file uses `vi.fn()` for mock WebSocket construction. The existing test patterns should guide how to add the new reconnect test.

## Verify

- [ ] FR#6: on WebSocket reconnect, `queryClient.invalidateQueries()` is called with no filter — verified by spy-based unit test; additionally, first connect does NOT call `invalidateQueries()` — verified by separate test case
- [ ] AC#11: after WebSocket reconnection, `queryClient.invalidateQueries()` fires and all active queries are marked stale — verified by spy-based unit test confirming the spy is called on reconnect (not first connect) with no filter argument
