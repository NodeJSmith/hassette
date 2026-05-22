/**
 * Test utilities for components and hooks that use TanStack Query.
 *
 * Use `createTestQueryClient()` to get an isolated QueryClient per test.
 * Use `renderHookWithProviders` for hooks that need both AppStateContext and
 * QueryClientProvider (e.g., hooks that call useQueryClient() internally).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/preact-query";
import { renderHook } from "@testing-library/preact";
import type { ComponentChildren } from "preact";

import { AppStateContext } from "../state/context";
import { type AppState, createAppState } from "../state/create-app-state";

/**
 * Returns a fresh QueryClient suitable for use in tests.
 *
 * Disables retry and sets staleTime to 0 so tests get deterministic,
 * synchronous-friendly behavior without network retries.
 * Create a new instance per test for proper isolation.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 0,
      },
    },
  });
}

interface RenderHookWithProvidersOptions {
  stateOverrides?: Partial<AppState>;
  queryClient?: QueryClient;
}

/**
 * Wraps `renderHook` with both QueryClientProvider and AppStateContext.Provider.
 *
 * Use for hooks that call useQueryClient() or useQuery() internally and also
 * need access to AppState (e.g., use-websocket.ts after adding invalidateQueries).
 */
export function renderHookWithProviders<T>(
  hook: () => T,
  { stateOverrides, queryClient }: RenderHookWithProvidersOptions = {},
) {
  const client = queryClient ?? createTestQueryClient();
  const state: AppState = { ...createAppState(), ...stateOverrides };

  function Wrapper({ children }: { children: ComponentChildren }) {
    return (
      <QueryClientProvider client={client}>
        <AppStateContext.Provider value={state}>{children}</AppStateContext.Provider>
      </QueryClientProvider>
    );
  }

  return renderHook(hook, { wrapper: Wrapper });
}
