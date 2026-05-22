---
task_id: "T04"
title: "Migrate ConfigPage and DiagnosticsPage to useQuery"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1"]
---

## Summary

Migrate the two simplest pages — ConfigPage and DiagnosticsPage — from `useApi` to `useQuery`. These are the tracer bullet: no scoped queries, no WS invalidation, no stale-ref patterns. They prove the basic `useApi → useQuery` migration pattern works end-to-end, including the test migration from hook mocks to MSW.

## Prompt

### 1. Migrate `frontend/src/pages/config.tsx`

Read the full file. The current pattern (lines 25-28):
```tsx
const result = useApi(getConfig);
const config = result.data.value;
const loading = result.loading.value;
const error = result.error.value;
```

Replace with:
```tsx
const { data: config, isPending: loading, error } = useQuery({
  queryKey: ["config"],
  queryFn: getConfig,
});
```

Update error display from `{error}` (string) to `{error?.message}` (Error object). Search the file for all occurrences of the error variable in JSX and update each one.

Remove the `useApi` import. Add `useQuery` import from `@tanstack/preact-query`.

### 2. Migrate `frontend/src/pages/config.test.tsx`

Read the full file. Remove the `vi.mock("../hooks/use-api")` block and the `fakeApiResult` helper. Tests should now use the MSW handlers already defined in `frontend/src/test/handlers.ts` to control API responses.

Key changes:
- Remove all `vi.mock` and `useApi.mockReturnValue(...)` calls
- Use `renderWithAppState(<ConfigPage />)` (which now includes QueryClientProvider via T01)
- Replace synchronous assertions with async: `await findByText(...)`, `waitFor(...)`
- Test loading state by verifying spinner appears before data loads
- Test error state by overriding the MSW handler with `server.use(http.get(..., () => HttpResponse.json(null, { status: 500 })))` and checking for error message display
- Test populated data by letting the default MSW handler respond

### 3. Migrate `frontend/src/pages/diagnostics.tsx`

Same pattern as config.tsx. Read the full file, replace `useApi` with `useQuery`, update error display.

Query key: `["system-status"]` (see design doc query key table).

### 4. Migrate `frontend/src/pages/diagnostics.test.tsx`

Same pattern as config.test.tsx. Remove hook mocks, use MSW handlers, switch to async assertions.

## Focus

- ConfigPage and DiagnosticsPage are the simplest consumers — no `deps`, no `lazy`, no WS events.
- The error display change is critical. The current pattern renders `{error}` where `error` is a string. After migration, `error` is an `Error` object. Rendering `{error}` directly would show `[object Error]`. TypeScript should catch this (type mismatch in JSX), but truthiness-guarded patterns like `{error && <div>{error}</div>}` may not trigger a type error.
- The MSW handlers in `frontend/src/test/handlers.ts` already provide default responses for API endpoints. Read the file to see what's available. If the config or diagnostics endpoints aren't covered, add handlers.
- The test setup in `frontend/src/test-setup.ts` (lines 49-59) handles MSW lifecycle: `server.listen()`, `server.resetHandlers()`, `server.close()`.
- After this task, `useApi` still has consumers (command-palette.tsx uses it). Do NOT delete `use-api.ts` — that happens in T09.

## Verify

- [ ] FR#1: `config.tsx` and `diagnostics.tsx` use `useQuery` instead of `useApi` — verified by grep showing no `useApi` import in either file
