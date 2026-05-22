---
task_id: "T01"
title: "Add query client factory, provider setup, and test utilities"
status: "planned"
depends_on: []
implements: ["FR#2", "FR#3", "AC#3"]
---

## Summary

Create the TanStack Query infrastructure that all subsequent tasks depend on. This includes the query client factory with project-wide defaults (staleTime, retry, gcTime), the QueryClientProvider wrapping in app.tsx, and test utilities (test query client factory, render helpers with provider wrapping). No page migrations happen here — this is purely foundational plumbing.

## Prompt

Install `@tanstack/preact-query` and create the query client infrastructure.

### 1. Install the package

Add `@tanstack/preact-query` to `frontend/package.json` dependencies and run `npm install` in the `frontend/` directory.

### 2. Create `frontend/src/lib/query-client.ts`

The `frontend/src/lib/` directory does not exist — create it.

Export a `createQueryClient()` factory function that returns a new `QueryClient` with these defaults:

```typescript
defaultOptions: {
  queries: {
    staleTime: 30_000,
    gcTime: 300_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: (failureCount, error) => {
      // Don't retry 4xx errors — they're permanent failures
      if (error instanceof Error && 'status' in error && typeof error.status === 'number' && error.status >= 400 && error.status < 500) {
        return false;
      }
      return failureCount < 2;
    },
  },
}
```

Check how the existing `apiFetch` function in `frontend/src/api/endpoints.ts` throws errors — the retry function must detect HTTP status from whatever error type `apiFetch` produces. If `apiFetch` throws a plain `Error` with no `.status`, you may need to create a small `HttpError` class that preserves the status code, or check TanStack Query's error handling docs for how the adapter surfaces HTTP errors.

### 3. Create `frontend/src/lib/query-client.test.ts`

Test scenarios from design doc section "Test Strategy > New unit tests > query-client.test.ts":
- Factory returns a `QueryClient` with `staleTime: 30_000`
- Retry function returns false for 4xx errors (no retry)
- Retry function returns true for 5xx errors (up to 2 attempts)
- Retry function returns true for network errors (non-HTTP failures)
- `refetchOnWindowFocus` is false
- `refetchOnReconnect` is false

### 4. Create `frontend/src/test/query-test-utils.ts`

Export:
- `createTestQueryClient()` — returns a `QueryClient` with `retry: false`, `staleTime: 0` for test isolation. Create a fresh client per test.
- `renderHookWithProviders(hook, options?)` — wraps `renderHook` with both `AppStateContext.Provider` and `QueryClientProvider`. Accepts optional `stateOverrides` and `queryClient`.

Reference the existing `renderWithAppState` in `frontend/src/test/render-helpers.tsx` (lines 26-29) for the AppState wrapping pattern.

### 5. Update `frontend/src/test/render-helpers.tsx`

Add `QueryClientProvider` wrapping to `renderWithAppState`. Import `createTestQueryClient` from `./query-test-utils`. The provider tree should be:
```tsx
<QueryClientProvider client={queryClient}>
  <AppStateContext.Provider value={state}>
    {ui}
  </AppStateContext.Provider>
</QueryClientProvider>
```

Create a fresh test query client per `renderWithAppState` call. This affects all 15 test files that use `renderWithAppState` — the change should be transparent since the test client has `retry: false` and `staleTime: 0`.

### 6. Update `frontend/src/app.tsx`

Wrap the existing `AppStateContext.Provider` with `QueryClientProvider`. Create the client via `useMemo(() => createQueryClient(), [])`.

```tsx
import { QueryClientProvider } from "@tanstack/preact-query";
import { createQueryClient } from "./lib/query-client";

// In the App component:
const queryClient = useMemo(() => createQueryClient(), []);

return (
  <QueryClientProvider client={queryClient}>
    <AppStateContext.Provider value={state}>
      {/* existing children unchanged */}
    </AppStateContext.Provider>
  </QueryClientProvider>
);
```

Do NOT remove `ManifestProvider` yet — that happens in T05.

## Focus

- The `frontend/src/lib/` directory does not exist. Create it before writing `query-client.ts`.
- The existing `apiFetch` in `frontend/src/api/endpoints.ts` is the HTTP client wrapper. Read it to understand what error type it throws — the retry function depends on this.
- `frontend/src/test/render-helpers.tsx` currently wraps only with `AppStateContext.Provider` (lines 26-29). Adding `QueryClientProvider` here is the minimal change that enables all subsequent tasks.
- `frontend/src/app.tsx` currently has the provider tree at lines 73-154. The `QueryClientProvider` wraps OUTSIDE `AppStateContext.Provider` so that hooks inside the tree (like `useWebSocket`, which will call `useQueryClient()` in T03) can access the query client.
- All 15 test files using `renderWithAppState` are indirectly affected. The test query client (`retry: false`, `staleTime: 0`) makes wrapping transparent for tests that don't touch queries.
- Follow the import pattern used in existing files: relative imports like `../lib/query-client`, `./query-test-utils`.

## Verify

- [ ] FR#2: `createQueryClient()` sets `staleTime: 30_000` — verified by unit test
- [ ] FR#3: retry function returns false for 4xx, true for 5xx (up to 2), true for network errors — verified by unit tests
- [ ] AC#3: retry function allows 5xx→200 recovery — verified by unit test showing retry returns true for 5xx then the query can succeed on next attempt
