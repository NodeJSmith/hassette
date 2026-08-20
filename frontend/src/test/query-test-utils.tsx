/**
 * Test utilities for components and hooks that use TanStack Query.
 *
 * Use `createTestQueryClient()` to get an isolated QueryClient per test.
 * Use `renderHookWithProviders` for hooks that need QueryClientProvider
 * (e.g., hooks that call useQueryClient() internally). Pass `storeOverrides`
 * to seed the Zustand store before the hook runs.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, vi } from "vitest";

import type { AppStore } from "../state/store";
import { useAppStore } from "../state/store";

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

interface RenderHookWithProvidersOptions<TProps> {
  storeOverrides?: Partial<AppStore>;
  queryClient?: QueryClient;
  initialProps?: TProps;
}

/**
 * Wraps `renderHook` with QueryClientProvider. Seeds the Zustand store with
 * `storeOverrides` (via `useAppStore.setState`) before the hook runs.
 *
 * Use for hooks that call useQueryClient() or useQuery() internally and also
 * need access to the app store (e.g., use-websocket.ts after adding invalidateQueries).
 *
 * Pass `initialProps` when the hook under test needs to receive new arguments via
 * `rerender(props)` (renderHook forwards `initialProps` and each `rerender` call to it).
 */
export function renderHookWithProviders<T, TProps = undefined>(
  hook: (props: TProps) => T,
  { storeOverrides, queryClient, initialProps }: RenderHookWithProvidersOptions<TProps> = {},
) {
  if (storeOverrides) useAppStore.setState(storeOverrides);
  const client = queryClient ?? createTestQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }

  return renderHook(hook, { wrapper: Wrapper, initialProps: initialProps as TProps });
}

/**
 * Renders a value-driven invalidator-style hook (e.g. `useQueryInvalidator`) with an
 * isolated QueryClient and a ready-made `invalidateQueries` spy, wired up via
 * `renderHookWithProviders` with `{ value }` as the rerender prop.
 *
 * `hook` receives the current `value` on each render/rerender — pass a closure over the
 * hook under test (and its other, non-varying arguments) since those differ per test.
 * Call `rerender({ value: nextValue })` on the returned result to simulate a value change.
 */
export function renderInvalidatorHook<T>(hook: (value: T) => void, initialValue: T) {
  const queryClient = createTestQueryClient();
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

  const renderResult = renderHookWithProviders<void, { value: T }>(({ value }) => hook(value), {
    queryClient,
    initialProps: { value: initialValue },
  });

  return { queryClient, invalidateSpy, ...renderResult };
}

/**
 * Installs Vitest fake timers for each test in the enclosing `describe` block and restores real
 * timers afterward. Call once at the top of a `describe(...)` body whose tests need a
 * controllable clock (e.g. debounce/timeout assertions).
 *
 * Generic Vitest lifecycle helper — has no TanStack Query dependency, so it's usable from any
 * hook test file, not just Query-based ones.
 */
export function useFakeTimersForEachTest(): void {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });
}
