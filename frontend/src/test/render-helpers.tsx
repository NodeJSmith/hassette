/**
 * Shared render helpers for components that require AppStateContext.
 *
 * Use `renderWithAppState` when testing components that call `useAppState()`.
 * Components that do not use context can use `render` from @testing-library/preact
 * directly.
 */

import { type QueryClient, QueryClientProvider } from "@tanstack/preact-query";
import { render } from "@testing-library/preact";
import type { ComponentChildren } from "preact";
import { vi } from "vitest";

import { AppStateContext } from "../state/context";
import { type AppState, createAppState } from "../state/create-app-state";
import { createTestQueryClient } from "./query-test-utils";

/**
 * Forces `useMediaQuery` to report mobile or desktop.
 *
 * jsdom has no `matchMedia`; `test-setup.ts` stubs it to always report desktop, so any
 * test exercising a responsive branch has to override it. Pair with
 * `afterEach(() => vi.restoreAllMocks())`.
 */
export function mockMediaQueryMatches(matches: boolean) {
  vi.spyOn(window, "matchMedia").mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

interface RenderWithAppStateOptions {
  stateOverrides?: Partial<AppState>;
  queryClient?: QueryClient;
}

/**
 * Renders a Preact component tree wrapped in QueryClientProvider and
 * AppStateContext.Provider.
 *
 * A fresh AppState and QueryClient are created for each call. Pass
 * `stateOverrides` to replace individual signals or methods on the default
 * state.
 *
 * The QueryClient uses test defaults (retry: false, staleTime: 0) so existing
 * tests that don't touch queries are unaffected. Tests for components that call
 * useQuery will go through normal query lifecycle backed by MSW handlers.
 */
export function renderWithAppState(
  ui: ComponentChildren,
  { stateOverrides, queryClient }: RenderWithAppStateOptions = {},
) {
  const state: AppState = { ...createAppState(), ...stateOverrides };
  const client = queryClient ?? createTestQueryClient();

  return render(
    <QueryClientProvider client={client}>
      <AppStateContext.Provider value={state}>{ui}</AppStateContext.Provider>
    </QueryClientProvider>,
  );
}
